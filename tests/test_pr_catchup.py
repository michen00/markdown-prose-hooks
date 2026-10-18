"""Run the catch-up's update step the way Actions runs it.

The step pipes `gh pr list` into the loop that merges main into each pull
request. Actions runs a `run:` body with no `shell:` key as `bash -e`, which
leaves pipefail off, so unless the body sets it, a listing that fails gives the
loop nothing to read and the step passes with every pull request still behind.
No later step can notice, because each reads what this one wrote. These run the
body under that same invocation, against a `gh` that answers the listing alone.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# The step runs on ubuntu-latest. On a Windows runner `bash` resolves to WSL's
# launcher, which has no distribution installed and exits 1 before reading the
# script, so a run there would test the launcher rather than the step.
pytestmark = pytest.mark.skipif(
    sys.platform == 'win32', reason='bash on Windows runners is the WSL launcher'
)

_WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/pr-catchup.yml'
_STEP = 'Update behind pull request branches'

# Any call besides the listing exits 2, so a test cannot pass by way of a merge
# the fake was never meant to answer.
_GH = """\
#!/usr/bin/env bash
if [ "$1 $2" != 'pr list' ]; then
  echo "unexpected gh call: $*" >&2
  exit 2
fi
if [ "$FAKE_LISTING" = fails ]; then
  echo 'HTTP 503: Service Unavailable (https://api.github.com/graphql)' >&2
  exit 1
fi
"""


def _update_step() -> str:
    """Return the update step's ``run:`` body as the workflow states it."""
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding='utf-8'))
    (step,) = [
        step
        for step in workflow['jobs']['catchup']['steps']
        if step.get('name') == _STEP
    ]
    return str(step['run'])


def _run(tmp_path: Path, listing: str) -> subprocess.CompletedProcess[str]:
    """Run the update step under ``bash -e``, with ``listing`` as the fake's mode."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text(_GH, encoding='utf-8')
    gh.chmod(0o755)
    script = tmp_path / 'step.sh'
    script.write_text(_update_step(), encoding='utf-8')
    # The script is this tree's own workflow text, and bash comes off PATH, the
    # way the runner reaches it.
    return subprocess.run(  # noqa: S603
        ['bash', '-e', str(script)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'GH_TOKEN': 'unused',
            'REPO': 'michen00/markdown-prose-hooks',
            'PR_CATCHUP_DIR': str(tmp_path),
            'FAKE_LISTING': listing,
        },
    )


def test_a_failed_listing_fails_the_step(tmp_path: Path) -> None:
    """A `gh pr list` that fails turns the step red rather than updating nothing."""
    done = _run(tmp_path, 'fails')
    assert done.returncode != 0, (
        'the listing failed and the step still passed, so every pull request '
        'behind main stays behind under a green run'
    )


def test_an_empty_listing_passes_the_step(tmp_path: Path) -> None:
    """With nothing open, the step passes, so the test above fails on the listing."""
    done = _run(tmp_path, 'empty')
    assert done.returncode == 0, done.stderr
