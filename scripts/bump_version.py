#!/usr/bin/env python3
"""Move every version pin in this tree at once.

A release is a tag, and the tag is only correct if the tree it names already
says so everywhere. Six files carry the number and they are not alike: two are
package manifests, two are lockfiles derived from them, and two are pins that a
consumer resolves -- the readme snippets somebody copies, and the `uses:` line
in `unwrap-propose.yml` that the reusable workflow runs.

That last one is why this script exists rather than a sentence in
CONTRIBUTING. The releasing section named the two manifests and stopped there,
so `v0.1.1` shipped with the propose pin still reading `v0.1.0` -- against the
comment directly above it, which states that the pin and the tag agree because
the file carrying the line came from that tag. A consumer calling the workflow
at `v0.1.1` got the previous release's action. Nothing was red, because nothing
was looking.

So the list of sites lives here, where it runs, instead of in prose where it
rotted. Every site is required to match: a file that moves, or a line that
changes shape, fails loudly rather than being skipped in silence. Missing a
pin is the failure this replaces, and a bump that half-succeeds would be the
same failure wearing a script.

Usage: uv run python scripts/bump_version.py 0.1.2
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Each entry is a template rendered with the old and the new version. Both
# renderings are literal, so nothing here is a regex a stray character could
# widen -- a pin is replaced exactly or the run fails.
SITES: tuple[tuple[str, str], ...] = (
    ('pyproject.toml', "version = '{v}'"),
    ('Cargo.toml', 'version = "{v}"'),
    ('README.md', 'v{v}'),
    ('.github/workflows/unwrap-propose.yml', 'markdown-prose-hooks@v{v}'),
)

# Derived from the manifests rather than edited, so they cannot disagree with
# what was just written. Both are offline: the dependency sets are unchanged,
# only this package's own version entry moves.
LOCKFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('uv.lock', ('uv', 'lock', '--offline')),
    ('Cargo.lock', ('cargo', 'update', '--offline', '--workspace')),
)

VERSION = re.compile(r'^\d+\.\d+\.\d+$')


def current_version() -> str:
    """Read the version the tree currently names, from the Python manifest."""
    text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r"^version = '(.+)'$", text, re.MULTILINE)
    if match is None:
        raise SystemExit('pyproject.toml carries no version line')
    return match.group(1)


def plan(old: str, new: str) -> list[tuple[Path, str, str, int]]:
    """Resolve every site before writing any of them.

    A half-bumped tree is worse than an unbumped one: it looks done. So every
    site is read and resolved first, and a single miss aborts before anything
    reaches the disk, naming all of the misses rather than the first.
    """
    resolved, missing = [], []
    for name, template in SITES:
        path = REPO / name
        if not path.is_file():
            missing.append(f'{name} is registered as a version pin but not in the tree')
            continue
        text = path.read_text(encoding='utf-8')
        needle = template.format(v=old)
        count = text.count(needle)
        if count == 0:
            missing.append(f'{name} carries no {needle!r}')
            continue
        resolved.append(
            (path, name, text.replace(needle, template.format(v=new)), count)
        )
    if missing:
        raise SystemExit('nothing written -- ' + '; '.join(missing))
    return resolved


def apply(resolved: list[tuple[Path, str, str, int]]) -> list[str]:
    """Write what plan resolved."""
    written = []
    for path, name, text, count in resolved:
        path.write_text(text, encoding='utf-8')
        written.append(f'{name}: {count}')
    return written


def relock() -> list[str]:
    """Refresh each lockfile from its manifest."""
    done = []
    for name, command in LOCKFILES:
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f'{name}: {" ".join(command)} failed\n{result.stderr}')
        done.append(name)
    return done


def verify(old: str, new: str) -> None:
    """Prove no registered site still names the old version."""
    stale = [
        name
        for name, template in SITES
        if template.format(v=old) in (REPO / name).read_text(encoding='utf-8')
    ]
    if stale:
        raise SystemExit(f'still naming {old}: {", ".join(stale)}')
    for name, _ in LOCKFILES:
        if f'"{new}"' not in (REPO / name).read_text(encoding='utf-8'):
            raise SystemExit(f'{name}: not refreshed to {new}')


def main() -> None:
    if len(sys.argv) != 2 or not VERSION.match(sys.argv[1]):
        raise SystemExit('usage: bump_version.py X.Y.Z')
    new = sys.argv[1]
    old = current_version()
    if old == new:
        raise SystemExit(f'already at {new}')
    for line in apply(plan(old, new)):
        print(line)
    for name in relock():
        print(f'{name}: relocked')
    verify(old, new)
    print(f'{old} -> {new}')


if __name__ == '__main__':
    main()
