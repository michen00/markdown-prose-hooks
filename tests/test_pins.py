"""Hold the two ruff pins level, because two bots move them independently.

`make check` runs `uv run ruff`, which resolves from `uv.lock`. The pre-commit
hook runs whichever ruff its `rev:` names, which pre-commit builds for itself.
Nothing connects the two: pre-commit.ci bumps the `rev:` on its own monthly
schedule and Dependabot bumps the lock in a separate pull request, so the gate
and the hook can come to answer from different rule sets without either bump
looking wrong on its way in.

That is a description of something that already happened rather than a worry.
The two had drifted two minor versions apart, and it surfaced only because a
selector this repository's configuration uses did not exist in the older one.
`.pre-commit-config.yaml` states the intent to keep them level; this is the
part that checks it, so the claim is measured rather than remembered.

Both files are read literally rather than through a TOML or YAML parser. The
floor is 3.10, which has no `tomllib`, and neither file earns a dependency to
read two version strings out of. A file that changes shape therefore fails
here rather than being skipped in silence, which is the rule
`scripts/bump_version.py` already follows for the release pins.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# The `rev:` on the ruff hook repository, which is the version pre-commit
# builds. Anchored to the repository line above it so a `rev:` belonging to
# some other hook cannot answer in its place.
_HOOK_RUFF = re.compile(
    r'- repo: https://github\.com/astral-sh/ruff-pre-commit\n\s*rev: v(\S+)',
)

# The version uv resolved, which is the one `uv run ruff` executes. The lock
# states it directly under the package name, so the pair identifies it without
# needing to understand the file.
_LOCKED_RUFF = re.compile(r'\[\[package\]\]\nname = "ruff"\nversion = "([^"]+)"')


def _sole_capture(pattern: re.Pattern[str], path: Path, what: str) -> str:
    """Return what ``pattern`` captures in ``path``, failing if it matches nothing."""
    match = pattern.search(path.read_text(encoding='utf-8'))
    if match is None:
        message = (
            f'{path.name} no longer states {what} in the shape this test reads. '
            f'Fix the pattern rather than dropping the check.'
        )
        raise AssertionError(message)
    return match.group(1)


def test_the_hook_and_the_gate_run_one_ruff() -> None:
    """The ruff the pre-commit hook pins is the ruff `make check` resolves."""
    hook = _sole_capture(
        _HOOK_RUFF,
        _REPO / '.pre-commit-config.yaml',
        "the ruff hook's revision",
    )
    locked = _sole_capture(_LOCKED_RUFF, _REPO / 'uv.lock', 'the ruff it resolved')
    assert hook == locked, (
        f'.pre-commit-config.yaml pins ruff v{hook} while uv.lock resolves '
        f'{locked}, so the hook and `make check` enforce different rule sets. '
        f'Move both in one change rather than letting either bump land alone.'
    )
