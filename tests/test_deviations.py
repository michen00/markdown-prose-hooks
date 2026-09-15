"""Assert that every DEVIATION marker says what it is blocked on.

CLAUDE.md states the convention: a configuration file that cannot yet take its
intended form carries a ``DEVIATION, blocked on`` comment saying so. The
closing section of docs/benchmarks.ipynb reads those comments for its own
summary, and a notebook reports only when a person runs it, so the suite is
where the convention can be checked on every run instead.

Two properties hold here. A marker names what it is blocked on rather than
stopping at the phrase, because a marker with nothing after it records that
something is blocked without recording what would lift it. And the scan covers
the tracked tree rather than a list of filenames, so a file that gains a marker
is covered when it arrives rather than when somebody remembers to list it.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

# The phrase ends on the words it does so that what follows it -- on the same
# line, or in the comment lines under it -- answers 'blocked on what'.
_MARKER = 'DEVIATION, blocked on'


def _deviations(text: str) -> list[str]:
    """Return the comment block each marker in ``text`` introduces, one per marker."""
    lines = text.splitlines()
    blocks: list[str] = []
    append_to_blocks = blocks.append
    for index, line in enumerate(lines):
        # The marker has to sit in a comment rather than anywhere in the line.
        # CLAUDE.md names the phrase while stating the convention and the
        # notebook assigns it to a constant, so a match on the bare phrase
        # would report the two files that describe the marker as carrying one.
        if _MARKER not in line or not line.lstrip().startswith('#'):
            continue
        block: list[str] = []
        append_to_block = block.append
        # From the marker's own line rather than the one after it, so that an
        # explanation written on the same line is collected too.
        for follow in lines[index:]:
            stripped = follow.lstrip()
            if not stripped.startswith('#'):
                break
            append_to_block(stripped.lstrip('#').strip())
        append_to_blocks(' '.join(part for part in block if part))
    # Every marker rather than the first, because a file explaining one and
    # leaving a later one bare would otherwise be read as following the
    # convention on the strength of the first.
    return blocks


def _says_what_blocks_it(block: str) -> bool:
    """Whether a collected block names anything beyond the marker phrase."""
    return bool(block.replace(_MARKER, '').strip())


def _tracked_files() -> tuple[Path, ...]:
    """Return every file git tracks here, as absolute paths."""
    # Tracked rather than walked. A walk descends into .venv, target/ and
    # __pycache__, which are build output rather than part of this tree, and it
    # would read far more than it reported on.
    listing = subprocess.run(
        # git comes off PATH, the same way every other caller here reaches
        # it, and the argv is fixed.
        ['git', 'ls-files', '-z'],  # noqa: S607
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(_REPO / name for name in listing.split('\0') if name)


def _carried_markers() -> Iterator[tuple[Path, str]]:
    """Yield each tracked file carrying a marker, with the block it introduces."""
    for path in _tracked_files():
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            # corpus/ pins bytes rather than prose, and one of its cases is
            # deliberately not valid UTF-8. A file that cannot be decoded
            # carries no comment for the same reason it carries no prose.
            continue
        for block in _deviations(text):
            yield path, block


def test_every_marker_says_what_it_is_blocked_on() -> None:
    """A marker in the tree is followed by what would lift it."""
    silent = sorted(
        {
            str(path.relative_to(_REPO))
            for path, block in _carried_markers()
            if not _says_what_blocks_it(block)
        }
    )
    assert not silent, (
        'these files carry the marker and stop at the phrase, so they record '
        f'that something is blocked but not what would lift it: {silent}'
    )


# The tree carries no marker today, so the scan above passes over an empty set
# and says nothing about whether it would find one. These pin the reading
# itself, which is the part that would be wrong when a marker does arrive.
@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        pytest.param(
            '# DEVIATION, blocked on\n# the 1.0 release of the linter.\nkey = 1\n',
            ['DEVIATION, blocked on the 1.0 release of the linter.'],
            id='explanation-on-the-lines-below',
        ),
        pytest.param(
            '# DEVIATION, blocked on the 1.0 release.\nkey = 1\n',
            ['DEVIATION, blocked on the 1.0 release.'],
            id='explanation-on-the-marker-line',
        ),
        pytest.param(
            '# DEVIATION, blocked on\nkey = 1\n',
            ['DEVIATION, blocked on'],
            id='nothing-after-the-phrase',
        ),
        pytest.param('key = 1\n', [], id='no-marker'),
        pytest.param(
            'A file carries a `DEVIATION, blocked on` comment saying so.\n',
            [],
            id='named-in-prose-rather-than-carried',
        ),
        pytest.param(
            "MARKER = 'DEVIATION, blocked on'\n",
            [],
            id='assigned-to-a-constant-rather-than-carried',
        ),
    ],
)
def test_reading_a_marker(text: str, expected: list[str]) -> None:
    """Each block collected is a marker line and the comment lines under it."""
    assert _deviations(text) == expected


def test_an_earlier_marker_does_not_excuse_a_later_one() -> None:
    """A file explaining its first marker still has to explain the rest."""
    # Reading only the first marker would report this file as following the
    # convention, on the strength of a block the bare marker below has nothing
    # to do with.
    text = (
        '# DEVIATION, blocked on the 1.0 release.\n'
        'key = 1\n'
        '# DEVIATION, blocked on\n'
        'other = 2\n'
    )
    assert [_says_what_blocks_it(block) for block in _deviations(text)] == [True, False]


def test_the_scan_reaches_the_tree() -> None:
    """The tracked listing names real files, rather than resolving to nothing."""
    # Without this, `_tracked_files` returning an empty tuple would leave the
    # scan above passing for the wrong reason, and a marker anywhere in the
    # tree would go unread.
    assert _REPO / 'pyproject.toml' in set(_tracked_files())
