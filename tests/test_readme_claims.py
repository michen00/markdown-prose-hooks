"""Hold the README's word-form parity claims to the artifact behind them.

The README states counts out of `docs/prettier-parity.json` in words rather
than numerals, so an added corpus case does not make it stale. A word covers a
band where a numeral carries a value, and that band is what this file asserts.
The parity workflow is what keeps the artifact itself current; this only asks
whether the prose still fits it.
"""

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_README = (_REPO / 'README.md').read_text(encoding='utf-8')
_PARITY = json.loads(
    (_REPO / 'docs' / 'prettier-parity.json').read_text(encoding='utf-8')
)

# Where the words stop being defensible. Nine in ten is a reading of "nearly
# all" anyone would accept and eight in ten is not; "almost none" is the same
# line from the other side. A measurement that crosses one of these is a
# sentence to rewrite rather than a band to widen.
_NEARLY_ALL = 0.9
_ALMOST_NONE = 0.1


def _says(phrase: str) -> None:
    """Fail unless the README still carries the claim being checked."""
    found = _README.count(phrase)
    if found != 1:
        pytest.fail(
            f'README.md carries {found} copies of {phrase!r}, not one. The '
            'band below stands behind that sentence, so the sentence and this '
            'check move together.'
        )


def _agreement(group: str, *path: str) -> float:
    """Return a measured group's agreement share, by path through the JSON."""
    node = _PARITY
    for key in (group, *path):
        node = node[key]
    if not node['cases']:
        pytest.fail(
            f'{".".join((group, *path))} holds no cases, so a share of it '
            'asserts nothing'
        )
    return float(node['agree']) / float(node['cases'])


def test_prettier_joins_fewer_lines_in_one_case() -> None:
    """Fail when a second case runs the direction the README calls unique."""
    _says('the only case in the corpus where it joins fewer lines than this tool does')
    overall = _PARITY['overall']
    assert overall['prettier_joined_less'] == 0, (
        f'{overall["prettier_joined_less"]} cases break the same document '
        'with Prettier keeping more line breaks than this tool, where the '
        'README says the raw HTML block is the only case that runs that way.'
    )
    assert overall['structurally_different'] == 1, (
        f'{overall["structurally_different"]} cases are structurally '
        'different, and the README names one. Read the new one: the sentence '
        'is about the only case where Prettier joins fewer lines, and a case '
        'the comparison cannot rank is where such a case would land.'
    )
    raw_html_case = 'a-kelvin-sign-folds-into-an-html-closing-tag'
    assert raw_html_case in _PARITY['disagreement_examples'], (
        f'the one structurally different case is no longer {raw_html_case}, '
        'so the count above now stands for a different case than the one the '
        'README names. Reword the README rather than the count.'
    )


def test_the_rename_carries_nearly_every_active_marker() -> None:
    """Fail when translating the marker stops buying agreement."""
    _says('nearly all of them agree')
    share = _agreement('axis_2_ignore_directives', 'marker_active_translated')
    assert share >= _NEARLY_ALL, (
        f'{share:.1%} of the cases whose marker Prettier acts on agree once '
        f'it is spelled its way, under the {_NEARLY_ALL:.0%} that "nearly '
        'all" covers. Reword the README rather than the band.'
    )


def test_almost_no_active_marker_agrees_as_written() -> None:
    """Fail when Prettier starts honoring the marker under our spelling."""
    _says('leave the markers as written and almost none do')
    share = _agreement('axis_2_ignore_directives', 'marker_active_as_written')
    assert share <= _ALMOST_NONE, (
        f'{share:.1%} of the cases whose marker Prettier acts on agree with '
        f'it spelled ours, over the {_ALMOST_NONE:.0%} that "almost none" '
        'covers. Reword the README rather than the band.'
    )


def test_a_disagreement_is_nearly_always_the_same_document() -> None:
    """Fail when disagreements stop being Prettier joining further."""
    _says('nearly always joined more of the same document')
    overall = _PARITY['overall']
    assert overall['disagree'], 'the corpus records no disagreement to describe'
    share = overall['prettier_joined_more'] / overall['disagree']
    assert share >= _NEARLY_ALL, (
        f'{share:.1%} of disagreements are the same document with Prettier '
        f'joining more, under the {_NEARLY_ALL:.0%} that "nearly always" '
        'covers. The README tells a reader the two writers settle rather than '
        'undo each other, so reword that before widening this.'
    )
