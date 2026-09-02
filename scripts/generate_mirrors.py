#!/usr/bin/env python3
"""Build the two mirror repositories from this tree.

`markdown-prose-hooks-py` and `markdown-prose-hooks-rs` each serve two of the
four hook ids and nothing else, so a consumer of one downloads one
implementation rather than two plus the corpus that specifies them. They are
generated and replaced wholesale, never hand-edited: a hook manifest maintained
in two places is a manifest that eventually disagrees with itself.

Two kinds of file go into a mirror, and the distinction is the whole design.

Templated. The hook manifest, the build manifest, the readme and the contributing
note, in `mirrors/<kind>/`, with `@VERSION@` substituted. These are authored
because they say different things than this repository's do -- the `-rs` one
describes a wrapper crate that does not exist here at all, and the contributing
note says the opposite of this repository's, since a pull request against a
generated tree cannot be merged.

The hook manifest used to be a third kind, filtered out of a copy this
repository served itself so that an id or an `entry:` was written once and could
not drift between the two. That copy is gone: this repository stopped serving
hook ids, the mirrors hold the only ones, and the two sets are disjoint. So
there is nothing left for the derivation to keep in step, and authoring each
mirror's manifest removes the last duplicate rather than adding one.

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
    'py': (
        # Named without the leading dot for the same reason the `-rs` gitignore
        # is: a manifest called `.pre-commit-hooks.yaml` here would make this
        # repository serve hook ids again, which is the thing it stopped doing.
        ('pre-commit-hooks.yaml', '.pre-commit-hooks.yaml'),
        ('pyproject.toml.in', 'pyproject.toml'),
        ('README.md', 'README.md'),
        ('CONTRIBUTING.md', 'CONTRIBUTING.md'),
    ),
    'rs': (
        ('pre-commit-hooks.yaml', '.pre-commit-hooks.yaml'),
        ('Cargo.toml.in', 'Cargo.toml'),
        ('README.md', 'README.md'),
        ('CONTRIBUTING.md', 'CONTRIBUTING.md'),
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
        match = re.search(r"""^version = ['"]([^'"]+)['"]""", text, re.MULTILINE)
        if not match:
            message = f'no version in {name}'
            raise SystemExit(message)
        found[name] = match.group(1)
    if len(set(found.values())) != 1:
        message = f'manifests disagree on the version: {found}'
        raise SystemExit(message)
    return next(iter(found.values()))


def build(kind: str, destination: Path, *, lockfile: bool = True) -> None:
    """Write one mirror's whole tree into ``destination``."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

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
        completed = subprocess.run(
            ['cargo', 'generate-lockfile', '--quiet'],
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
