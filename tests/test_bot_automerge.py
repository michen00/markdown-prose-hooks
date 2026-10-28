"""Run bot auto-merge's provenance step the way Actions runs it.

The step decides whether every commit on a bot's pull request came from GitHub
and from the bot, and nothing below it arms auto-merge unless it says so. A
merge commit is exempt from the match against the pull request's author, so
that a catch-up merge passes, and GitHub signs a merge a person resolves in its
web conflict editor as well, which can carry any content. These run the step
against a `gh` that answers its two reads with rows already in the shape its
`--jq` filter produces: the origin, the kind, and the author's login.
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


def _trusted(tmp_path: Path, *rows: str) -> str:
    """Run the provenance step over ``rows``, and return what it set ``trusted`` to."""
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding='utf-8'))
    (step,) = [
        step
        for step in workflow['jobs']['bot-automerge']['steps']
        if step.get('id') == 'provenance'
    ]
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
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
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
    return line.removeprefix('trusted=')


def test_a_merge_a_bot_authored_passes(tmp_path: Path) -> None:
    """A catch-up merge authored by a bot does not hold the pull request."""
    assert (
        _trusted(
            tmp_path,
            'github|plain|dependabot[bot]',
            'github|merge|github-actions[bot]',
        )
        == 'true'
    )


@pytest.mark.parametrize('author', ['michen00', '<none>'])
def test_a_merge_a_person_authored_holds(tmp_path: Path, author: str) -> None:
    """A merge authored by a person, or by nobody GitHub can name, holds."""
    assert (
        _trusted(
            tmp_path,
            'github|plain|dependabot[bot]',
            f'github|merge|{author}',
        )
        == 'false'
    )
