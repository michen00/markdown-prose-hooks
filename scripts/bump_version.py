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

It can still half-succeed, because the lockfiles are refreshed by other
programs and either can fail for reasons of its own. So the state that leaves
-- every pin written, both lockfiles behind -- is one this script recognizes
and finishes on the next run, rather than one it reads as a finished release.

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
# what was just written. Only the Cargo side is offline, and the asymmetry is
# deliberate: the crate declares no dependencies, so cargo has nothing to fetch
# and a cold cache cannot fail it. The Python side carries a dev dependency set
# that dependabot moves on its own schedule, and `uv lock --offline` resolves
# from the cache alone -- so a floor raised since this machine last fetched
# fails the lock for a reason that has nothing to do with the version being
# bumped. That is how the bump to 0.1.4 failed here, against the ruff floor
# `67d170e` had raised.
LOCKFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('uv.lock', ('uv', 'lock')),
    ('Cargo.lock', ('cargo', 'update', '--offline', '--workspace')),
)

VERSION = re.compile(r'^\d+\.\d+\.\d+$')

# This package's own entry, which both lockfiles happen to spell the same way.
# Found by name rather than by searching for the number, because a bare version
# string can belong to a dependency that happens to share it -- which would let
# a stale lockfile pass for a refreshed one.
LOCKED = re.compile(r'^name = "markdown-prose-hooks"\nversion = "(.+)"$', re.MULTILINE)


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


def locked_version(name: str) -> str | None:
    """Read this package's own version out of a lockfile."""
    match = LOCKED.search((REPO / name).read_text(encoding='utf-8'))
    return None if match is None else match.group(1)


def stale_lockfiles(new: str) -> list[str]:
    """Name every lockfile that does not yet carry the new version."""
    return [name for name, _ in LOCKFILES if locked_version(name) != new]


def verify_sites(old: str) -> None:
    """Prove no registered pin still names the old version."""
    stale = [
        name
        for name, template in SITES
        if template.format(v=old) in (REPO / name).read_text(encoding='utf-8')
    ]
    if stale:
        raise SystemExit(f'still naming {old}: {", ".join(stale)}')


def verify_lockfiles(new: str) -> None:
    """Prove both lockfiles were refreshed to the new version."""
    stale = stale_lockfiles(new)
    if stale:
        raise SystemExit(f'not refreshed to {new}: {", ".join(stale)}')


def resume(new: str) -> None:
    """Finish a bump whose pins landed and whose lockfiles did not.

    `relock` runs only once every pin is written, so a failure there leaves the
    tree naming the new version everywhere a person would look and the old one
    in both lockfiles -- and leaves this script reading its own output back as
    proof that there is nothing left to do. Refusing on that reading is how a
    half-finished bump becomes a released one, so the refusal is narrowed to
    the tree that has earned it: one that already agrees with itself.
    """
    unwritten = [
        name
        for name, template in SITES
        if template.format(v=new) not in (REPO / name).read_text(encoding='utf-8')
    ]
    if unwritten:
        raise SystemExit(
            f'{new} is written in pyproject.toml but not in '
            f'{", ".join(unwritten)} -- a bump died mid-write, and which '
            'version to replace is no longer readable from the tree; set the '
            'rest by hand'
        )
    stale = stale_lockfiles(new)
    if not stale:
        raise SystemExit(f'already at {new}')
    print(f'pins already at {new}, {", ".join(stale)} left behind')
    for name in relock():
        print(f'{name}: relocked')
    verify_lockfiles(new)
    print(f'finished an interrupted bump to {new}')


def main() -> None:
    if len(sys.argv) != 2 or not VERSION.match(sys.argv[1]):
        raise SystemExit('usage: bump_version.py X.Y.Z')
    new = sys.argv[1]
    old = current_version()
    if old == new:
        resume(new)
        return
    for line in apply(plan(old, new)):
        print(line)
    for name in relock():
        print(f'{name}: relocked')
    verify_sites(old)
    verify_lockfiles(new)
    print(f'{old} -> {new}')


if __name__ == '__main__':
    main()
