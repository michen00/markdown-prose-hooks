"""Hold every committed chart to the matplotlib that is meant to draw it.

Two matplotlib versions lay a chart out differently enough to rewrite every
path coordinate in the SVG. A notebook re-executed against a different
matplotlib therefore produces several hundred lines of chart diff without
moving a single figure, and nothing else catches it: the parity check reads
the JSON beside the notebook rather than the chart, and a diff that large is
exactly the kind a reviewer waves through.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LOCK = _REPO / 'uv.lock'
_CHARTS = tuple(sorted((_REPO / 'docs/notebooks').rglob('*.svg')))

# One stanza per version the lock resolves. A lock that resolves several has
# forked matplotlib by interpreter, and the pin in CONTRIBUTING.md then decides
# which one draws the charts, so this test has to learn that fork's marker.
_LOCKED = re.compile(
    r'^\[\[package\]\]\nname = "matplotlib"\nversion = "(?P<version>[^"]+)"',
    re.MULTILINE,
)
_DREW = re.compile(r'Matplotlib v(?P<version>[0-9][^<,\s]*)')


def _locked_matplotlib() -> str:
    """Return the one matplotlib `uv.lock` resolves."""
    found = {
        match.group('version')
        for match in _LOCKED.finditer(_LOCK.read_text(encoding='utf-8'))
    }
    if not found:
        pytest.fail('uv.lock resolves no matplotlib.')
    if len(found) > 1:
        pytest.fail(
            f'uv.lock resolves several matplotlib versions: {sorted(found)}. '
            'Make this test read the one the interpreter CONTRIBUTING.md pins '
            'resolves, then re-execute the notebooks with that pin.'
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
        f'uv.lock resolves {locked}. Re-execute that notebook with the '
        'pinned command in CONTRIBUTING.md and commit what it wrote.'
    )
