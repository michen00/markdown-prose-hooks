"""Run the CLI conformance tier against every built implementation.

The transform tier (`corpus/cases/`) specifies what the unwrap does to a
document, and `test_corpus.py` runs it. This tier specifies what the *program*
does: which files it opens, what it writes, what it prints, and what it exits
with. None of that is reachable from `unwrap_markdown_prose`, so none of it can
be specified by a document-in, document-out case. The format is documented in
`corpus/cli/README.md`.

Parameterization is over (case, runner) rather than over case alone, from the
first commit and before there is a second runner to justify it. Adding the Rust
binary is then one entry in `_runners()` and no change to any test, which is the
difference between a harness that was designed for two implementations and one
that was retrofitted to a second.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CLI_CORPUS = _REPO / 'corpus' / 'cli'


@dataclass(frozen=True)
class Runner:
    """One implementation under test, named and invocable."""

    label: str
    argv: tuple[str, ...]

    def __str__(self) -> str:
        """Return the label, used as the parametrize id."""
        return self.label


def _runners() -> list[Runner]:
    """Return every implementation that is currently built.

    `-m` rather than the console script: a console script lives wherever the
    installer put it, while `-m` resolves through `sys.executable` and works the
    same in a uv venv, a `pre-commit` environment, and a plain user install. The
    two reach the identical `main`, differing only in `sys.argv[0]`, and no case
    asserts a usage message for exactly that reason.

    The Rust binary is skipped rather than failed when it is absent, so a
    Python-only checkout still runs the tier. CI builds it first and sets
    `REQUIRE_RUST_BINARY`, so a build failure there cannot downgrade to a silent
    half-run of the tier.
    """
    runners = [Runner('py', (sys.executable, '-m', 'markdown_prose_hooks'))]
    suffix = '.exe' if sys.platform == 'win32' else ''
    binary = _REPO / 'target' / 'release' / f'unwrap-markdown-prose-rs{suffix}'
    if binary.exists():
        runners.append(Runner('rs', (str(binary),)))
    elif os.environ.get('REQUIRE_RUST_BINARY'):
        message = f'REQUIRE_RUST_BINARY is set but {binary} is absent'
        raise RuntimeError(message)
    return runners


class CliCase:
    """One CLI case: its tree, its expectations, and why it exists."""

    def __init__(self, directory: Path) -> None:
        """Load the case rooted at ``directory``."""
        self.slug = directory.name
        self.directory = directory
        meta = _parse_meta(directory / 'case.txt')
        self.name = meta['name']
        self.why = meta['why']
        self.argv = meta['argv'].split()
        self.exit_code = int(meta['exit_code'])
        # Git stores one executable bit and nothing else, so a case needing a
        # particular mode states it here and the harness applies it to the copy.
        # Comma-separated `path octal` pairs; absent means leave modes alone.
        self.chmod = [
            (parts[0], int(parts[1], 8))
            for entry in meta.get('chmod', '').split(',')
            if len(parts := entry.split()) == 2
        ]
        # Absent means empty, which is the common case and not worth a file.
        stdout = directory / 'stdout.txt'
        self.stdout = stdout.read_bytes() if stdout.exists() else b''

    def __str__(self) -> str:
        """Return the slug, used as the parametrize id."""
        return self.slug


def _parse_meta(path: Path) -> dict[str, str]:
    """Return the ``key: value`` pairs in a case's metadata file."""
    # The same format the transform tier uses, and deliberately not YAML: this
    # package has no dependencies, and every other implementation would need a
    # parser too.
    # `Path.open` rather than `Path.read_text(newline=...)`, which only grew the
    # keyword in 3.13. The floor here is 3.10, and the suite has to run on it.
    meta: dict[str, str] = {}
    with path.open(encoding='utf-8', newline='') as handle:
        contents = handle.read()
    for line in contents.splitlines():
        if not (stripped := line.strip()):
            continue
        key, _, value = stripped.partition(':')
        meta[key.strip()] = value.strip()
    return meta


def _snapshot(root: Path) -> dict[str, object]:
    """Return every entry under ``root`` as posix-relative path to content.

    A regular file maps to its bytes. A symlink maps to its target string,
    never to the bytes it points at — `Path.is_file` follows links, so reading
    through one would compare a symlink against a regular copy of its target
    and call them equal. That is precisely the rewrite the symlink case exists
    to forbid, so dereferencing here would make it pin nothing.

    Bytes rather than text, and every entry rather than the ones the case names:
    a tool that writes a file nobody gave it is a failure no amount of output
    checking would notice.
    """
    snapshot: dict[str, object] = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = f'-> {os.readlink(path)}'
        elif path.is_file():
            snapshot[relative] = path.read_bytes()
    return snapshot


def _apply_modes(case: CliCase, scratch: Path) -> list[tuple[Path, int]]:
    """Apply a case's requested file modes, returning what to restore afterward.

    A mode is a request, not a guarantee. Windows has no POSIX permission bits
    worth the name, and a process running as root reads a mode-000 file
    regardless. In either environment the case would run against a perfectly
    readable file, take the success path, and fail with a diff that says
    nothing about what went wrong — so the mode is checked and the case skipped
    loudly when it did not take.

    The caller must restore these before comparing trees. The mode constrains
    the tool under test, not the harness: leaving it in place makes `_snapshot`
    the thing that cannot read the file, and the case then fails on the
    verifier's permissions rather than on the tool's behavior.
    """
    restore: list[tuple[Path, int]] = []
    for relative, mode in case.chmod:
        target = scratch / relative
        restore.append((target, target.stat().st_mode & 0o777))
        target.chmod(mode)
        if mode & 0o444:
            continue
        try:
            target.read_bytes()
        except OSError:
            continue
        pytest.skip(f'chmod {mode:03o} did not make {relative} unreadable here')
    return restore


def load_cli_corpus() -> list[CliCase]:
    """Return every CLI case, ordered by slug."""
    if not _CLI_CORPUS.is_dir():
        return []
    return [CliCase(d) for d in sorted(_CLI_CORPUS.iterdir()) if d.is_dir()]


CLI_CASES = load_cli_corpus()


def test_the_cli_corpus_is_not_empty() -> None:
    """A wrong corpus path would otherwise make every case silently vanish."""
    # Parametrizing over an empty list collects zero tests and reports success,
    # so the suite has to assert that the corpus was found at all.
    assert CLI_CASES, f'no CLI cases found under {_CLI_CORPUS}'


def test_every_runner_that_was_required_is_present() -> None:
    """A build failure must not downgrade to a silently halved test run."""
    # `_runners()` skips an implementation that is not built, so a checkout
    # without a Rust toolchain still runs the tier. In CI that leniency would
    # let a broken build pass as a skip, so CI sets the variable instead.
    required = os.environ.get('REQUIRE_RUNNERS', '')
    missing = set(required.split()) - {runner.label for runner in _runners()}
    assert not missing, f'REQUIRE_RUNNERS asks for {sorted(missing)}, not built'


@pytest.mark.parametrize('runner', _runners(), ids=str)
@pytest.mark.parametrize('case', CLI_CASES, ids=str)
def test_cli_case(case: CliCase, runner: Runner, tmp_path: Path) -> None:
    """Each case's run produces its expected tree, stdout and exit code."""
    scratch = tmp_path / 'tree'
    shutil.copytree(case.directory / 'tree', scratch, symlinks=True)
    restore = _apply_modes(case, scratch)

    completed = subprocess.run(  # noqa: S603
        [*runner.argv, *case.argv],
        cwd=scratch,
        capture_output=True,
        check=False,
    )

    for target, mode in restore:
        target.chmod(mode)

    if os.environ.get('REGENERATE_CLI_CORPUS') and runner.label == 'py':
        _regenerate(case, scratch, completed)
        return

    # stderr is not asserted — see the parity boundary in corpus/cli/README.md —
    # but it is the only useful thing to read when a case fails, so it rides
    # along in the message rather than being discarded.
    context = f'{case.name} — {case.why}'
    detail = completed.stderr.decode('utf-8', 'replace')
    assert completed.returncode == case.exit_code, f'{context}\nstderr:\n{detail}'
    assert completed.stdout == case.stdout, f'{context}\nstderr:\n{detail}'
    assert _snapshot(scratch) == _snapshot(case.directory / 'expected'), context


def _regenerate(
    case: CliCase,
    scratch: Path,
    completed: subprocess.CompletedProcess[bytes],
) -> None:
    """Rewrite a case's answer key from what the reference run actually did.

    Writing `expected/` or `stdout.txt` by hand pins what their author believed,
    which is the one thing a conformance case must not do. This lives inside the
    harness rather than beside it so that regeneration and verification share
    one copy, one chmod, one invocation and one snapshot: a generator with its
    own copy of that setup can drift from the thing it is generating for, and
    the failure mode is an answer key that no run can reproduce.

    `exit_code` is still read from `case.txt` and still enforced. It is the one
    expectation an author states rather than observes, so it is the one guard
    against regenerating a bug into the specification — the rest of the key is
    reviewed as a diff, which is why regeneration is a separate deliberate run
    rather than something a failing test offers to do for you.
    """
    if completed.returncode != case.exit_code:
        message = (
            f'{case.slug}: case.txt declares exit {case.exit_code}, observed '
            f'{completed.returncode}\n{completed.stderr.decode("utf-8", "replace")}'
        )
        raise AssertionError(message)

    expected = case.directory / 'expected'
    shutil.rmtree(expected, ignore_errors=True)
    shutil.copytree(scratch, expected, symlinks=True)

    stdout_path = case.directory / 'stdout.txt'
    if completed.stdout:
        stdout_path.write_bytes(completed.stdout)
    elif stdout_path.exists():
        stdout_path.unlink()
