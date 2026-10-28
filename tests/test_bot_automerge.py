"""Run bot auto-merge's provenance step the way Actions runs it.

The step decides whether every commit on a bot's pull request came from GitHub, every
commit that is not a merge from the bot, and every merge either from nothing but a
clean merge of two parents or from a repository admin. Nothing below it arms auto-merge
unless it says so. GitHub signs a merge a person resolves in its web conflict editor
as well, which can carry any content, so these cases build real repositories and let
the step's own `git fetch` and `git merge-tree` decide: an origin holding the branch at
`refs/pull/7/head`, and a clone of its `main` for the step to run in, as the checkout
before it leaves the runner. The `gh` the step calls answers its two reads with rows
built from the branch's real commits, in the shape its `--jq` filter produces: the
origin, the kind, the author's login, the SHA and the parent SHAs. It answers the
permission lookup from `_ADMIN`, `_FLAKY` and write, and records each one.
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

# Who the fake says each merge author is: `_ADMIN` is an admin, `_FLAKY`'s lookup
# fails, and anyone else has write. `<none>` stands for an author GitHub cannot name;
# the fixtures write it as `no-account`, since git strips `<` and `>` from a name.
_ADMIN = 'michen00'
_NON_ADMIN = 'contributor'
_FLAKY = 'flaky-lookup'

# Any call besides the three reads exits 2, so a test cannot pass by way of a
# request the fake was never meant to answer.
_GH = f"""\
#!/usr/bin/env bash
case "$2" in
  repos/owner/repository/pulls/7) printf '%s\\n' "$FAKE_COUNT" ;;
  repos/owner/repository/pulls/7/commits) printf '%s\\n' "$FAKE_ROWS" ;;
  repos/owner/repository/collaborators/*/permission)
    login=${{2#*/collaborators/}}; login=${{login%/permission}}
    echo "$login" >>"$LOOKUP_LOG"
    case $login in
      {_ADMIN}) echo admin ;;
      {_FLAKY}) echo "gh: Server Error (HTTP 502)" >&2; exit 1 ;;
      *) echo write ;;
    esac ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 2 ;;
esac
"""

_HELD = "is neither a clean merge of two parents nor an admin's; holding."


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
    _git(repo, 'commit', '-qm', 'chore: start', author=_ADMIN)
    _git(repo, 'switch', '-qc', 'bump')
    _write(repo, 'a.txt', 'a, bumped')
    _git(repo, 'commit', '-qam', 'build: bump a')
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change b', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    return repo


def _edited_merge(repo: Path, author: str) -> None:
    """Merge main cleanly as ``author``, then amend an extra edit into the merge."""
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=author)
    _write(repo, 'c.txt', f'c, edited in the merge by {author}')
    _git(repo, 'commit', '-q', '--amend', '--no-edit', '--all', author=author)


def _resolved_merge(repo: Path, author: str) -> None:
    """Merge a conflicting main as ``author``, resolved by hand with an extra edit."""
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'a.txt', 'a, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change a', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, 'merge', '-q', '--no-edit', 'main', author=author)
    _write(repo, 'a.txt', 'whatever the resolver typed')
    _write(repo, 'c.txt', 'and an edit elsewhere')
    _git(repo, 'add', 'a.txt', 'c.txt')
    _git(repo, 'commit', '-q', '--no-edit', author=author)


def _run(
    tmp_path: Path, repo: Path, count: str | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    """Run the provenance step on ``repo``'s branch as pull request 7.

    The fake reports the commit count as ``count`` when one is given, and as the
    number of rows otherwise. Returns the finished step, the lines it wrote to
    ``GITHUB_OUTPUT``, and the logins it looked up.
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
        author = '<none>' if author == 'no-account' else author
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
    lookups = tmp_path / 'lookups'
    lookups.write_text('', encoding='utf-8')
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
            'FAKE_COUNT': str(len(rows)) if count is None else count,
            'FAKE_ROWS': '\n'.join(rows),
            'LOOKUP_LOG': str(lookups),
        },
    )
    lines = output.read_text(encoding='utf-8').splitlines()
    return done, lines, lookups.read_text(encoding='utf-8').split()


def _trusted(tmp_path: Path, repo: Path) -> tuple[str, str, list[str]]:
    """Run the provenance step, which must succeed, on ``repo``'s branch.

    Returns what it set ``trusted`` to, its log, and the logins it looked up.
    """
    done, lines, looked_up = _run(tmp_path, repo)
    assert done.returncode == 0, done.stderr
    (line,) = lines
    return line.removeprefix('trusted='), done.stdout, looked_up


@pytest.mark.parametrize(
    'merger',
    ['github-actions[bot]', _NON_ADMIN, _ADMIN],
    ids=['catch-up', 'update-branch-by-a-non-admin', 'update-branch-by-an-admin'],
)
def test_a_clean_merge_passes(tmp_path: Path, merger: str) -> None:
    """A clean merge of two branches passes, whoever authored it, with no lookup.

    pr-catchup.yml merges as github-actions[bot] or as the App, and Update branch as
    the person who clicked it. GitHub makes either only when the merge is clean.
    """
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=merger)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == []


def test_an_admins_resolved_merge_with_extra_edits_passes(tmp_path: Path) -> None:
    """An admin's merge passes even when it resolves a conflict and edits more."""
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _ADMIN)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


def test_an_admin_is_looked_up_once_for_several_merges(tmp_path: Path) -> None:
    """Two edited merges by one admin both pass on a single permission lookup."""
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, _ADMIN)
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main again')
    _git(repo, 'commit', '-qam', 'feat: change b again', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    _edited_merge(repo, _ADMIN)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


@pytest.mark.parametrize(
    ('merger', 'lookups'),
    [(_NON_ADMIN, [_NON_ADMIN]), (_FLAKY, [_FLAKY]), ('no-account', [])],
    ids=['non-admin', 'failed-lookup', 'no-account'],
)
def test_an_edited_merge_by_anyone_but_an_admin_holds(
    tmp_path: Path, merger: str, lookups: list[str]
) -> None:
    """An extra edit in a merge holds it unless an admin made it.

    A failed lookup, or an author GitHub cannot name, counts as not an admin, and the
    latter is never looked up.
    """
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, merger)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log
    assert looked_up == lookups


def test_a_conflict_a_non_admin_resolved_by_hand_holds(tmp_path: Path) -> None:
    """A merge whose conflict a non-admin resolved holds, whatever they typed."""
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _NON_ADMIN)
    trusted, log, _ = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


def test_an_octopus_merge_by_a_non_admin_holds(tmp_path: Path) -> None:
    """A clean merge of three branches has three parents, so it is not mechanical."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'switch', '-qc', 'side', 'main~1')
    _write(repo, 'c.txt', 'c, changed on side')
    _git(repo, 'commit', '-qam', 'build: change c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', 'side', author=_NON_ADMIN)
    trusted, log, _ = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


@pytest.mark.parametrize('count', ['null', '3abc', ''])
def test_a_commit_count_that_is_not_an_integer_holds(
    tmp_path: Path, count: str
) -> None:
    """A count that is not an integer fails the step, leaving ``trusted`` unset.

    Unguarded, the `-gt` and `-ne` tests error inside `if`, read as false, and the step
    falls through to trusting the pull request.
    """
    repo = _dependabot_branch(tmp_path)
    done, lines, _ = _run(tmp_path, repo, count=count)
    assert done.returncode != 0
    assert lines == []
    assert "could not read the PR's commit count; holding." in done.stdout
