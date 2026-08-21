#!/usr/bin/env python3
"""Build the two mirror repositories from this tree.

`markdown-prose-hooks-py` and `markdown-prose-hooks-rs` each serve two of the
four hook ids and nothing else, so a consumer of one downloads one
implementation rather than two plus the corpus that specifies them. They are
generated and replaced wholesale, never hand-edited: a hook manifest maintained
in two places is a manifest that eventually disagrees with itself.

Three kinds of file go into a mirror, and the distinction is the whole design.

Derived. `.pre-commit-hooks.yaml` is filtered out of this repository's own
manifest, so an id, an `entry:` or a description is written once here and cannot
drift. Only the comment above the ids is authored per mirror, in
`mirrors/<kind>/hooks-preamble.yaml`.

Templated. The build manifest and the readme, in `mirrors/<kind>/`, with
`@VERSION@` substituted. These are authored because they say different things
than this repository's do -- the `-rs` one describes a wrapper crate that does
not exist here at all.

Verbatim. The implementation and the license, copied. Nothing is rewritten on
the way, so a mirror runs the same bytes this repository tested.

The `-rs` mirror also gets a `Cargo.lock`, which needs cargo and the network:
the wrapper's one dependency is the published crate, and pinning it is what
makes the tree build the version its commit names.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATES = _REPO / 'mirrors'
_PLACEHOLDER = '@VERSION@'

# Copied without rewriting, as `source -> destination in the mirror`. The `-rs`
# entry is the binary rather than the library: the mirror wraps the published
# crate instead of carrying a second copy of it, which is the one structural
# difference between the two mirrors.
_VERBATIM = {
    'py': (
        ('LICENSE', 'LICENSE'),
        ('src/markdown_prose_hooks', 'src/markdown_prose_hooks'),
    ),
    'rs': (
        ('LICENSE', 'LICENSE'),
        (
            'src/bin/unwrap-markdown-prose-rs.rs',
            'src/bin/unwrap-markdown-prose-rs.rs',
        ),
    ),
}

# `<template in mirrors/<kind>/> -> <path in the mirror>`. A template is read
# for `@VERSION@` whether or not it holds one, so adding a version to a readme
# later needs no change here.
_TEMPLATED = {
    'py': (('pyproject.toml.in', 'pyproject.toml'), ('README.md', 'README.md')),
    'rs': (
        ('Cargo.toml.in', 'Cargo.toml'),
        ('README.md', 'README.md'),
        # Named without the dot in this repository, where a real `.gitignore`
        # would apply to the templates beside it.
        ('gitignore', '.gitignore'),
    ),
}


def version() -> str:
    """Return the version both manifests name, refusing to guess if they differ.

    Two implementations answering to one corpus are one tool, so a version
    meaning something different in each language is a question every consumer
    has to ask twice. The mirrors would encode the disagreement -- the `-rs`
    wrapper pins the crate exactly -- so it is caught here instead.
    """
    found = {}
    for name in ('Cargo.toml', 'pyproject.toml'):
        text = (_REPO / name).read_text(encoding='utf-8')
        match = re.search(r"""^version = ['"]([^'"]+)['"]""", text, re.M)
        if not match:
            message = f'no version in {name}'
            raise SystemExit(message)
        found[name] = match.group(1)
    if len(set(found.values())) != 1:
        message = f'manifests disagree on the version: {found}'
        raise SystemExit(message)
    return next(iter(found.values()))


def hook_blocks() -> dict[str, str]:
    """Return this repository's hook definitions, keyed by id.

    Line-oriented rather than parsed as YAML, for the reason the corpus metadata
    is: this package takes no dependency, and a parser would be the first.
    """
    text = (_REPO / '.pre-commit-hooks.yaml').read_text(encoding='utf-8')
    blocks: dict[str, str] = {}
    current: list[str] = []
    identifier = ''
    for line in text.splitlines(keepends=True):
        if line.startswith('- id: '):
            if identifier:
                blocks[identifier] = ''.join(current)
            identifier = line[len('- id: ') :].strip()
            current = [line]
        elif identifier:
            current.append(line)
    if identifier:
        blocks[identifier] = ''.join(current)
    return blocks


def manifest(kind: str) -> str:
    """Return the mirror's `.pre-commit-hooks.yaml`, derived rather than written.

    The two ids for one implementation are exactly `unwrap-markdown-prose-<kind>`
    and its `-check` companion. Naming them here rather than pattern-matching
    means a fifth id added upstream lands in neither mirror until somebody
    decides which mirror it belongs to.
    """
    blocks = hook_blocks()
    wanted = (f'unwrap-markdown-prose-{kind}', f'unwrap-markdown-prose-{kind}-check')
    missing = [identifier for identifier in wanted if identifier not in blocks]
    if missing:
        message = f'.pre-commit-hooks.yaml has no {missing}'
        raise SystemExit(message)
    preamble = (_TEMPLATES / kind / 'hooks-preamble.yaml').read_text(encoding='utf-8')
    bodies = (blocks[identifier].rstrip('\n') for identifier in wanted)
    # A blank line between blocks, which is how the manifest this was filtered
    # out of separates them.
    return preamble + '\n\n'.join(bodies) + '\n'


def build(kind: str, destination: Path, *, lockfile: bool = True) -> None:
    """Write one mirror's whole tree into ``destination``."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    (destination / '.pre-commit-hooks.yaml').write_text(
        manifest(kind), encoding='utf-8'
    )

    released = version()
    for template, target in _TEMPLATED[kind]:
        text = (_TEMPLATES / kind / template).read_text(encoding='utf-8')
        (destination / target).write_text(
            text.replace(_PLACEHOLDER, released), encoding='utf-8'
        )

    for source, target in _VERBATIM[kind]:
        origin = _REPO / source
        landing = destination / target
        landing.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            # `__pycache__` is the one thing a source tree grows that a mirror
            # must not carry: it is build output, and it would differ per run.
            shutil.copytree(
                origin, landing, ignore=shutil.ignore_patterns('__pycache__', '*.pyc')
            )
        else:
            shutil.copy2(origin, landing)

    if kind == 'rs' and lockfile:
        completed = subprocess.run(  # noqa: S603
            ['cargo', 'generate-lockfile', '--quiet'],  # noqa: S607
            cwd=destination,
            check=False,
        )
        if completed.returncode:
            # Almost always one thing, and a traceback says none of it: the
            # wrapper pins this version exactly, so the lockfile cannot resolve
            # until that version is on crates.io. Between a version bump and the
            # tag that publishes it, this is the expected answer rather than a
            # fault, which is why the message names the cause.
            message = (
                f'cargo could not resolve a lockfile for {released}. '
                f'markdown-prose-hooks {released} is probably not on crates.io '
                'yet, which is the state between a version bump and the tag that '
                'publishes it. Pass --no-lockfile to generate the rest anyway.'
            )
            raise SystemExit(message)


def main(argv: list[str] | None = None) -> int:
    """Generate both mirrors under the given directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='directory to write py/ and rs/ into')
    parser.add_argument(
        '--no-lockfile',
        action='store_true',
        help='skip `cargo generate-lockfile`, which needs cargo and the network',
    )
    arguments = parser.parse_args(argv)
    for kind in ('py', 'rs'):
        build(
            kind,
            arguments.output / kind,
            lockfile=not arguments.no_lockfile,
        )
        print(f'{kind}: {arguments.output / kind}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
