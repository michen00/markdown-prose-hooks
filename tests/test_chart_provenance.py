"""Hold every committed chart to the matplotlib that is meant to draw it.

`uv.lock` resolves two matplotlib versions, one below Python 3.11 and one at or
above it, and the two lay a chart out differently enough to rewrite every path
coordinate in the SVG. A notebook re-executed on an unpinned interpreter
therefore produces several hundred lines of chart diff without moving a single
figure, and nothing else catches it: the parity check reads the JSON beside the
notebook rather than the chart, and a diff that large is exactly the kind a
reviewer waves through.

CONTRIBUTING.md pins the interpreter in the command it sanctions. This file is
the half of that which fails rather than relies on the command being read.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LOCK = _REPO / 'uv.lock'
_CHARTS = tuple(sorted((_REPO / 'docs').glob('*.svg')))

# The interpreter CONTRIBUTING.md pins a notebook run to. Its matplotlib is
# whichever one uv.lock marks for a python below 3.11, so the marker rather
# than the version is what this file states: the version moves on a dependency
# bump, and the test should then report the charts as stale rather than agree
# with them.
_PINNED_MARKER = "python_full_version < '3.11'"

_LOCKED = re.compile(
    r'^\s*\{\s*name = "matplotlib", version = "(?P<version>[^"]+)".*'
    + re.escape(f'marker = "{_PINNED_MARKER}"'),
    re.MULTILINE,
)
_DREW = re.compile(r'Matplotlib v(?P<version>[0-9][^<,\s]*)')


def _locked_matplotlib() -> str:
    """Return the matplotlib `uv.lock` resolves for the pinned interpreter."""
    found = {
        match.group('version')
        for match in _LOCKED.finditer(_LOCK.read_text(encoding='utf-8'))
    }
    if not found:
        pytest.fail(
            f'uv.lock marks no matplotlib for {_PINNED_MARKER}. If the '
            'supported python floor moved, move the pin in CONTRIBUTING.md '
            'and the marker here together, then re-execute the notebooks.'
        )
    if len(found) > 1:
        pytest.fail(
            f'uv.lock marks several matplotlib versions for {_PINNED_MARKER}: '
            f'{sorted(found)}.'
        )
    return found.pop()


def test_the_docs_ship_charts() -> None:
    """Guard the glob, since a parameterization over nothing passes."""
    assert _CHARTS, 'docs/ holds no SVG, so the test below checks nothing'


@pytest.mark.parametrize('chart', _CHARTS, ids=lambda chart: chart.name)
def test_a_chart_names_the_locked_matplotlib(chart: Path) -> None:
    """Fail when a chart was drawn by a matplotlib the lock does not pin."""
    drew = _DREW.search(chart.read_text(encoding='utf-8'))
    assert drew is not None, f'{chart.name} names no matplotlib'
    locked = _locked_matplotlib()
    assert drew.group('version') == locked, (
        f'{chart.name} was drawn by matplotlib {drew.group("version")}, and '
        f'uv.lock resolves {locked} for the interpreter CONTRIBUTING.md pins. '
        'Re-execute that notebook with the pinned command and commit what it '
        'wrote.'
    )
