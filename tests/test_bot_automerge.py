"""Run bot auto-merge's provenance step the way Actions runs it.

The step decides whether every commit on a bot's pull request came from GitHub, every
commit that is not a merge from the bot, and every merge from nothing but a clean merge
of two parents. Nothing below it arms auto-merge unless it says so. GitHub signs a
merge a person resolves in its web conflict editor as well, which can carry any
content, so these cases build real repositories and let the step's own `git fetch` and
`git merge-tree` decide: an origin holding the branch at `refs/pull/7/head`, and a
clone of its `main` for the step to run in, as the checkout before it leaves the
runner. The `gh` the step calls answers its two reads with rows built from the
branch's real commits, in the shape its `--jq` filter produces: the origin, the kind,
the author's login, the SHA and the parent SHAs.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# The step runs on ubuntu-latest. On a Windows runner `bash` resolves to WSL's
# launcher, which tests the launcher rather than the step.
pytestmark = pytest.mark.skipif(
    sys.platform == 'win32', reason='bash on Windows runners is the WSL launcher'
)

_WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/bot-automerge.yml'

# Any call besides the two reads exits 2, so a test cannot pass by way of a
# request the fake was never meant to answer.
_GH = """\
#!/usr/bin/env bash
case "$2" in
  repos/owner/repository/pulls/7) printf '%s\\n' "$FAKE_COUNT" ;;
  repos/owner/repository/pulls/7/commits) printf '%s\\n' "$FAKE_ROWS" ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 2 ;;
esac
"""


def _isolated_env() -> dict[str, str]:
    """Return the environment without GIT_* variables or user and system git config.

    A hook runner's GIT_* variables would point git at this repository instead.
    """
    env = {
        key: value for key, value in os.environ.items() if not key.startswith('GIT_')
    }
    return {**env, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


def _git(repo: Path, *args: str, author: str = 'dependabot[bot]') -> str:
    """Run git in ``repo`` as ``author``, with GitHub as the committer."""
    done = subprocess.run(  # noqa: S603
        ['git', *args],  # noqa: S607
        cwd=repo,
        env={
            **_isolated_env(),
            'GIT_AUTHOR_NAME': author,
            'GIT_AUTHOR_EMAIL': f'{author}@example.invalid',
            'GIT_COMMITTER_NAME': 'GitHub',
            'GIT_COMMITTER_EMAIL': 'noreply@github.com',
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _write(repo: Path, name: str, text: str) -> None:
    """Write one line to a file in ``repo``."""
    (repo / name).write_text(f'{text}\n', encoding='utf-8')


def _dependabot_branch(tmp_path: Path) -> Path:
    """Return a repository on a Dependabot-style branch that main has moved on from.

    The branch changes a.txt and main changes b.txt, so merging main is clean.
    """
    repo = tmp_path / 'dev'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    for name in ('a', 'b', 'c'):
        _write(repo, f'{name}.txt', name)
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'chore: start', author='michen00')
    _git(repo, 'switch', '-qc', 'bump')
    _write(repo, 'a.txt', 'a, bumped')
    _git(repo, 'commit', '-qam', 'build: bump a')
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change b', author='michen00')
    _git(repo, 'switch', '-q', 'bump')
    return repo


def _trusted(tmp_path: Path, repo: Path) -> tuple[str, str]:
    """Run the provenance step on ``repo``'s branch as pull request 7.

    Returns what it set ``trusted`` to, and its log.
    """
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding='utf-8'))
    (step,) = [
        step
        for step in workflow['jobs']['bot-automerge']['steps']
        if step.get('id') == 'provenance'
    ]
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'clone', '-q', '--mirror', str(repo), str(origin))
    _git(origin, 'update-ref', 'refs/pull/7/head', _git(repo, 'rev-parse', 'HEAD'))
    runner = tmp_path / 'runner'
    _git(tmp_path, 'clone', '-q', '--branch', 'main', str(origin), str(runner))
    rows = []
    for sha in _git(repo, 'rev-list', '--reverse', 'main..HEAD').split():
        _, *parents = _git(repo, 'rev-list', '--parents', '-n1', sha).split()
        kind = 'merge' if len(parents) >= 2 else 'plain'
        author = _git(repo, 'log', '-1', '--format=%an', sha)
        rows.append(f'github|{kind}|{author}|{sha}|{" ".join(parents)}')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text(_GH, encoding='utf-8')
    gh.chmod(0o755)
    script = tmp_path / 'step.sh'
    script.write_text(str(step['run']), encoding='utf-8')
    output = tmp_path / 'output'
    output.write_text('', encoding='utf-8')
    # The script is this tree's own workflow text, run the way a step with no
    # `shell:` key is, with bash coming off PATH as it does on the runner.
    done = subprocess.run(  # noqa: S603
        ['bash', '-e', str(script)],  # noqa: S607
        cwd=runner,
        capture_output=True,
        text=True,
        check=False,
        env={
            **_isolated_env(),
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GH_TOKEN': 'unused',
            'GH_REPO': 'owner/repository',
            'PR_NUMBER': '7',
            'AUTHOR': 'dependabot[bot]',
            'FAKE_COUNT': str(len(rows)),
            'FAKE_ROWS': '\n'.join(rows),
        },
    )
    assert done.returncode == 0, done.stderr
    (line,) = output.read_text(encoding='utf-8').splitlines()
    return line.removeprefix('trusted='), done.stdout


@pytest.mark.parametrize(
    'merger', ['github-actions[bot]', 'michen00'], ids=['catch-up', 'update-branch']
)
def test_a_clean_merge_passes(tmp_path: Path, merger: str) -> None:
    """A clean merge of two branches passes, whoever authored it.

    pr-catchup.yml merges as github-actions[bot] or as the App, and Update branch as
    the person who clicked it. GitHub makes either only when the merge is clean.
    """
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=merger)
    trusted, log = _trusted(tmp_path, repo)
    assert trusted == 'true', log


def test_a_conflict_resolved_by_hand_holds(tmp_path: Path) -> None:
    """A merge whose conflict a person resolved holds, whatever they typed."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'a.txt', 'a, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change a', author='michen00')
    _git(repo, 'switch', '-q', 'bump')
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, 'merge', '-q', '--no-edit', 'main', author='michen00')
    _write(repo, 'a.txt', 'whatever the resolver typed')
    _git(repo, 'add', 'a.txt')
    _git(repo, 'commit', '-q', '--no-edit', author='michen00')
    trusted, log = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert 'is not a clean merge of two parents; holding.' in log


def test_a_clean_merge_with_an_extra_edit_holds(tmp_path: Path) -> None:
    """An edit amended into a clean merge makes its tree differ from the clean merge."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author='michen00')
    _write(repo, 'c.txt', 'c, edited in the merge')
    _git(repo, 'commit', '-q', '--amend', '--no-edit', '--all', author='michen00')
    trusted, log = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert 'is not a clean merge of two parents; holding.' in log


def test_an_octopus_merge_holds(tmp_path: Path) -> None:
    """A clean merge of three branches has three parents, so it is not mechanical."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'switch', '-qc', 'side', 'main~1')
    _write(repo, 'c.txt', 'c, changed on side')
    _git(repo, 'commit', '-qam', 'build: change c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', 'side', author='michen00')
    trusted, log = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert 'is not a clean merge of two parents; holding.' in log
