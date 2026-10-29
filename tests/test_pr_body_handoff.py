"""Run the body surface's hand-off between its two jobs the way Actions runs it.

Each half of the body surface runs the action in a job that holds no scope and
writes with a job that runs no action, so the transformed body and the drafted
report cross from one job to the other as job outputs. The first job writes
them to `GITHUB_OUTPUT` as multi-line values, the runner parses that file, and
the second job reads the parsed value through `env:`. A body is byte-exact
data: the edit compares it with the author's copy and sends it back whole, so a
lost carriage return or trailing newline is a change nobody made. These run the
exporting step and the writing step from this tree's own workflow text, with
the output file parsed the way the runner parses it and a `gh` that serves one
pull request.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# The steps run on ubuntu-latest. On a Windows runner `bash` resolves to WSL's
# launcher, which tests the launcher rather than the step, and a runner without
# the tools the steps call cannot say anything about them.
pytestmark = pytest.mark.skipif(
    sys.platform == 'win32' or not all(map(shutil.which, ('bash', 'jq', 'sha256sum'))),
    reason='the steps need bash, jq and sha256sum, as ubuntu-latest has them',
)

_WORKFLOWS = Path(__file__).resolve().parents[1] / '.github' / 'workflows'
_REPOSITORY = 'owner/repository'
_NUMBER = '7'

# Any call the steps under test are not expected to make exits 2, so a test
# cannot pass by way of a request the fake was never meant to answer.
_GH = f"""\
#!/usr/bin/env bash
case "$*" in
  'api repos/{_REPOSITORY}/pulls/{_NUMBER}')
    cat "$FAKE_DIR/current.json" ;;
  'api repos/{_REPOSITORY}/issues/{_NUMBER}/comments?per_page=100 --paginate')
    echo '[]' ;;
  'api --method PATCH repos/{_REPOSITORY}/pulls/{_NUMBER} --input payload.json --jq .html_url')
    cp payload.json "$FAKE_DIR/patched.json" ;;
  'api --method POST repos/{_REPOSITORY}/issues/{_NUMBER}/comments --input payload.json --jq .html_url')
    cp payload.json "$FAKE_DIR/posted.json" ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 2 ;;
esac
"""  # noqa: E501


def _parse_outputs(text: str) -> dict[str, str]:
    """Return the values in a ``GITHUB_OUTPUT`` file, read as the runner reads it.

    A port of the Linux path through ``EnvFileKeyValuePairs`` in
    ``src/Runner.Worker/FileCommandManager.cs`` of ``actions/runner``, as of
    4197182ef8f39c719f66038c1bc9b34cd9e9ac9a. A ``name<<delimiter`` line opens
    a value that ends at the newline before the first line equal to the
    delimiter; any other line is ``name=value``. Only a line feed ends a line
    there, so a carriage return stays in the value.
    """
    outputs: dict[str, str] = {}
    lines = text.split('\n')
    # Each line's offset, so a value is sliced out of the text rather than
    # joined back together from the lines.
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    position = 0
    while position < len(lines):
        line = lines[position]
        position += 1
        if not line:
            continue
        equals, heredoc = line.find('='), line.find('<<')
        if equals >= 0 and (heredoc < 0 or equals < heredoc):
            name, value = line.split('=', 1)
            outputs[name] = value
            continue
        name, delimiter = line.split('<<', 1)
        start = end = offsets[position]
        while lines[position] != delimiter:
            # The runner refuses a value whose last line has no newline after
            # it, and one whose delimiter never comes.
            assert position + 1 < len(lines), f'{name} is never closed'
            end = offsets[position + 1] - 1
            position += 1
        position += 1
        outputs[name] = text[start:end] if end > start else ''
    return outputs


_Run = tuple[subprocess.CompletedProcess[str], dict[str, str]]


def _step(filename: str, job: str, key: str) -> dict[str, Any]:
    """Return the step of ``job`` whose id or name is ``key``."""
    workflow = yaml.safe_load((_WORKFLOWS / filename).read_text(encoding='utf-8'))
    steps: list[dict[str, Any]] = workflow['jobs'][job]['steps']
    (step,) = [step for step in steps if key in (step.get('id'), step.get('name'))]
    return step


def _workspace(tmp_path: Path, job: str) -> Path:
    """Return the workspace of ``job``, which no other job's runner shares."""
    workspace = tmp_path / job / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _run(
    tmp_path: Path, job: str, step: dict[str, Any], environment: dict[str, str]
) -> _Run:
    """Run ``step`` as ``shell: bash`` does, and return what it set as outputs."""
    bin_dir = tmp_path / 'bin'
    if not bin_dir.exists():
        bin_dir.mkdir()
        gh = bin_dir / 'gh'
        gh.write_text(_GH, encoding='utf-8')
        gh.chmod(0o755)
    workspace = _workspace(tmp_path, job)
    runner_temp = tmp_path / job / 'runner-temp'
    runner_temp.mkdir(exist_ok=True)
    output = tmp_path / job / 'output'
    output.write_text('', encoding='utf-8')
    script = tmp_path / job / 'step.sh'
    script.write_text(str(step['run']), encoding='utf-8')
    # The step's own `env:` values that are literals, such as the marker; the
    # ones that are expressions are what each test supplies.
    literals = {
        key: str(value)
        for key, value in (step.get('env') or {}).items()
        if '${{' not in str(value)
    }
    # The script is this tree's own workflow text, run the way `shell: bash`
    # runs it, with bash coming off PATH as it does on the runner.
    done = subprocess.run(  # noqa: S603
        ['bash', '--noprofile', '--norc', '-eo', 'pipefail', str(script)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        cwd=workspace,
        env={
            **os.environ,
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'FAKE_DIR': str(tmp_path),
            'GITHUB_OUTPUT': str(output),
            'GITHUB_STEP_SUMMARY': str(tmp_path / job / 'summary.md'),
            'GITHUB_REPOSITORY': _REPOSITORY,
            'GITHUB_WORKSPACE': str(workspace),
            'RUNNER_TEMP': str(runner_temp),
            'GH_TOKEN': 'unused',
            **literals,
            **environment,
        },
    )
    parsed = _parse_outputs(output.read_bytes().decode('utf-8'))
    return done, parsed


def _sent(tmp_path: Path, name: str) -> str | None:
    """Return the body the fake was sent under ``name``, or None when none was."""
    path = tmp_path / name
    if not path.exists():
        return None
    return str(json.loads(path.read_text(encoding='utf-8'))['body'])


def _edit(tmp_path: Path, original: str, tidied: str, current: str) -> _Run:
    """Hand ``tidied`` from the transform to the edit, and run the edit."""
    body = _workspace(tmp_path, 'transform') / 'pr-body.md'
    body.write_bytes(tidied.encode('utf-8'))
    exported, outputs = _run(
        tmp_path, 'transform', _step('unwrap-pr-body.yml', 'transform', 'export'), {}
    )
    assert exported.returncode == 0, exported.stderr
    (tmp_path / 'current.json').write_text(
        json.dumps({'body': current}), encoding='utf-8'
    )
    written, _ = _run(
        tmp_path,
        'edit',
        _step('unwrap-pr-body.yml', 'edit', 'write'),
        {
            'NUMBER': _NUMBER,
            'ORIGINAL': original,
            'TIDIED': outputs['body'],
            'TIDIED_SHA256': outputs['sha256'],
        },
    )
    return written, outputs


# What a body can carry that a careless hand-off would lose or change: the
# CRLF a browser-written body uses, a trailing newline and the lack of one,
# blank lines at the end, a line that looks like a delimiter, and text a shell
# would read as syntax.
_BODIES = (
    'one line with no newline',
    'a CRLF body\r\nwith a trailing CRLF\r\n',
    'trailing blank lines\n\n\n',
    'EOF\nbody<<EOF\nname=value\n',
    '$(touch pwned) `uname` ${HOME} \\n "quoted" \'single\'\n',
    'non-ASCII: café, 中文, emoji 🎉\n',
)


@pytest.mark.parametrize('tidied', _BODIES)
def test_the_edit_writes_the_body_the_transform_produced(
    tmp_path: Path, tidied: str
) -> None:
    """The body the edit sends is the transform's file, byte for byte."""
    original = 'a hard-wrapped\nbody'
    written, outputs = _edit(tmp_path, original, tidied, current=original)
    assert written.returncode == 0, written.stderr
    assert outputs['body'] == tidied
    assert _sent(tmp_path, 'patched.json') == tidied


def test_the_edit_leaves_an_unchanged_body_alone(tmp_path: Path) -> None:
    """A body the transform did not change is not written."""
    body = 'a body with nothing to join\r\n'
    written, _ = _edit(tmp_path, body, body, current=body)
    assert written.returncode == 0, written.stderr
    assert _sent(tmp_path, 'patched.json') is None


def test_the_edit_leaves_a_body_edited_meanwhile_alone(tmp_path: Path) -> None:
    """A body the author changed while the run was queued is not overwritten."""
    written, _ = _edit(
        tmp_path, 'a hard-wrapped\nbody', 'a hard-wrapped body', current='retyped'
    )
    assert written.returncode == 0, written.stderr
    assert _sent(tmp_path, 'patched.json') is None


def test_the_edit_refuses_a_body_that_did_not_arrive(tmp_path: Path) -> None:
    """An output lost on the way reads as empty, and is refused, not written."""
    (tmp_path / 'current.json').write_text(
        json.dumps({'body': 'a hard-wrapped\nbody'}), encoding='utf-8'
    )
    written, _ = _run(
        tmp_path,
        'edit',
        _step('unwrap-pr-body.yml', 'edit', 'write'),
        {
            'NUMBER': _NUMBER,
            'ORIGINAL': 'a hard-wrapped\nbody',
            'TIDIED': '',
            'TIDIED_SHA256': hashlib.sha256(b'a hard-wrapped body').hexdigest(),
        },
    )
    assert written.returncode != 0
    assert _sent(tmp_path, 'patched.json') is None


def _report(
    tmp_path: Path, tidied: str, *, lose_it: bool = False
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Draft the report from ``tidied`` in the transform, and post it."""
    workspace = _workspace(tmp_path, 'transform')
    (workspace / 'pr-body.md').write_bytes(tidied.encode('utf-8'))
    drafted, outputs = _run(
        tmp_path,
        'transform',
        _step('unwrap-pr-body-check.yml', 'transform', 'draft'),
        {'COMMAND': f'gh pr view {_NUMBER} --json body'},
    )
    assert drafted.returncode == 0, drafted.stderr
    report = (workspace / 'body.md').read_bytes().decode('utf-8')
    posted, _ = _run(
        tmp_path,
        'report',
        _step(
            'unwrap-pr-body-check.yml', 'report', 'Post, update or withdraw the comment'
        ),
        {
            'NUMBER': _NUMBER,
            'WRAPPED': 'true',
            'COMMENT': 'true',
            'REPORT': '' if lose_it else outputs['report'],
            'REPORT_SHA256': outputs['sha256'],
        },
    )
    return posted, report


def test_the_report_posts_the_comment_the_transform_drafted(tmp_path: Path) -> None:
    """The comment posted is the draft, byte for byte."""
    posted, report = _report(tmp_path, 'a tidied body\r\nwith ``` fences\r\n')
    assert posted.returncode == 0, posted.stderr
    assert report.startswith('<!-- unwrap-pr-body -->\n')
    assert _sent(tmp_path, 'posted.json') == report


def test_the_report_refuses_a_draft_that_did_not_arrive(tmp_path: Path) -> None:
    """A draft lost on the way is refused rather than posted as an empty comment."""
    posted, _ = _report(tmp_path, 'a tidied body\n', lose_it=True)
    assert posted.returncode != 0
    assert _sent(tmp_path, 'posted.json') is None
