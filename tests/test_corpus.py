"""Run the language-neutral conformance corpus against the Python implementation.

The corpus is the specification every implementation answers to, so these tests
deliberately hold no expectations of their own: each case carries its input, its
expected output, and the reasoning for both. A Rust or Go implementation runs the
identical directory, which is what makes cross-language parity checkable rather
than asserted. The format is documented in `corpus/README.md`.
"""

from pathlib import Path

import pytest

from markdown_prose_hooks.unwrap import unwrap_markdown_prose

_CORPUS = Path(__file__).resolve().parents[1] / 'corpus' / 'cases'


class Case:
    """One conformance case: its bytes, its expectations, and why it exists."""

    def __init__(self, directory: Path) -> None:
        """Load the case rooted at ``directory``."""
        self.slug = directory.name
        meta = _parse_meta(directory / 'case.txt')
        self.name = meta['name']
        self.why = meta['why']
        self.paragraphs_unwrapped = int(meta['paragraphs_unwrapped'])
        self.line_breaks_removed = int(meta['line_breaks_removed'])
        # `newline=''` on both reads, because a case may pin CRLF handling and
        # universal-newline translation would quietly rewrite it to LF before
        # the assertion ever ran — turning a real regression into a pass.
        self.input = _read_verbatim(directory / 'input.md')
        answer_key = directory / 'expected.md'
        source = _expected_source(
            self.slug, meta, answer_key_exists=answer_key.is_file()
        )
        self.expected = (
            self.input if source == _FROM_INPUT else _read_verbatim(answer_key)
        )

    def __str__(self) -> str:
        """Return the human-readable name, used as the parametrize id."""
        return self.slug


def _read_verbatim(path: Path) -> str:
    """Return ``path`` with its line endings untranslated."""
    with path.open(encoding='utf-8', newline='') as handle:
        return handle.read()


def _parse_meta(path: Path) -> dict[str, str]:
    """Return the ``key: value`` pairs in a case's metadata file."""
    # Deliberately not YAML: this package has no dependencies, Python ships no
    # YAML parser, and every other implementation would need one too. `key:
    # value` costs a few lines in any language.
    meta: dict[str, str] = {}
    for line in _read_verbatim(path).splitlines():
        if not (stripped := line.strip()):
            continue
        key, _, value = stripped.partition(':')
        meta[key.strip()] = value.strip()
    return meta


_UNCHANGED = 'unchanged'
_FROM_INPUT = 'input'
_FROM_FILE = 'file'
_COUNT_KEYS = ('paragraphs_unwrapped', 'line_breaks_removed')


def _expected_source(
    slug: str, meta: dict[str, str], *, answer_key_exists: bool
) -> str:
    """Return where a case's expected output comes from.

    A case states that output exactly once: either `expected: unchanged` in its
    metadata, or an answer key on disk. Both is a contradiction with no
    defensible tiebreak; neither is a case that asserts nothing. Most of this
    tool is the part that declines to act, so the declaration is the common
    form and an answer key repeating its own input states nothing twice.

    Split from the filesystem so the rule is testable without building a case
    directory: this package takes no dependency beyond the standard library,
    and `tests/corpus.rs` holds the same rule under the same constraint.
    """
    declared = meta.get('expected')
    if declared is None:
        if answer_key_exists:
            return _FROM_FILE
        msg = f'{slug}: states no expected output'
        raise AssertionError(msg)
    if declared != _UNCHANGED:
        msg = f'{slug}: expected: {declared} is not a known relation'
        raise AssertionError(msg)
    if answer_key_exists:
        msg = f'{slug}: states its expected output twice'
        raise AssertionError(msg)
    if moved := [key for key in _COUNT_KEYS if int(meta.get(key, '0'))]:
        msg = f'{slug}: declares {_UNCHANGED} while recording {", ".join(moved)}'
        raise AssertionError(msg)
    return _FROM_INPUT


def _load_corpus() -> list[Case]:
    """Return every case in the corpus, ordered by slug."""
    return [Case(d) for d in sorted(_CORPUS.iterdir()) if d.is_dir()]


def _meta(**overrides: str) -> dict[str, str]:
    """Return a well-formed transform-tier metadata mapping."""
    meta = {
        'name': 'a case',
        'why': 'because',
        'paragraphs_unwrapped': '0',
        'line_breaks_removed': '0',
    }
    meta.update(overrides)
    return meta


def test_a_declared_case_takes_its_input_as_the_answer_key() -> None:
    """`expected: unchanged` says the output equals the input."""
    source = _expected_source(
        'slug', _meta(expected='unchanged'), answer_key_exists=False
    )
    assert source == _FROM_INPUT


def test_an_undeclared_case_reads_its_answer_key() -> None:
    """With no declaration the answer key on disk is the expectation."""
    assert _expected_source('slug', _meta(), answer_key_exists=True) == _FROM_FILE


def test_a_case_stating_its_output_twice_is_rejected() -> None:
    """Declaring `unchanged` and shipping an answer key is a contradiction."""
    with pytest.raises(AssertionError, match='twice'):
        _expected_source('slug', _meta(expected='unchanged'), answer_key_exists=True)


def test_a_case_stating_no_output_is_rejected() -> None:
    """Neither form present is a case that asserts nothing."""
    # Today this surfaces as a file-not-found from the reader. It gets a name
    # because a case with no expectation is a corpus error, not an IO accident.
    with pytest.raises(AssertionError, match='no expected output'):
        _expected_source('slug', _meta(), answer_key_exists=False)


def test_an_unknown_relation_is_rejected() -> None:
    """`unchanged` is the only relation the key names."""
    with pytest.raises(AssertionError, match='not a known relation'):
        _expected_source('slug', _meta(expected='reversed'), answer_key_exists=False)


def test_a_declared_case_recording_a_count_is_rejected() -> None:
    """Nothing changed and a break was removed cannot both be true."""
    # Caught today by the output or counts assertion, whichever the tool
    # disagrees with. Checking it at load time names the contradiction instead
    # of printing a diff.
    meta = _meta(expected='unchanged', line_breaks_removed='1')
    with pytest.raises(AssertionError, match='while recording'):
        _expected_source('slug', meta, answer_key_exists=False)


CASES = _load_corpus()


def test_the_corpus_is_not_empty() -> None:
    """A wrong corpus path would otherwise make every case silently vanish."""
    # Parametrizing over an empty list collects zero tests and reports success,
    # so the suite has to assert that the corpus was found at all.
    assert CASES, f'no conformance cases found under {_CORPUS}'


@pytest.mark.parametrize('case', CASES, ids=str)
def test_corpus_case_output(case: Case) -> None:
    """The unwrap turns each case's input into exactly its expected output."""
    result = unwrap_markdown_prose(case.input)
    assert result.content == case.expected, f'{case.name} — {case.why}'


@pytest.mark.parametrize('case', CASES, ids=str)
def test_corpus_case_counts(case: Case) -> None:
    """Each case's reported paragraph and line-break counts match its record."""
    # Split from the output assertion on purpose: identical content with a wrong
    # count means the reporting drifted from the rewriting, and a single combined
    # assertion would let the first failure hide the second.
    result = unwrap_markdown_prose(case.input)
    assert result.paragraphs_unwrapped == case.paragraphs_unwrapped, case.name
    assert result.line_breaks_removed == case.line_breaks_removed, case.name


@pytest.mark.parametrize('case', CASES, ids=str)
def test_corpus_case_is_idempotent(case: Case) -> None:
    """Re-running the unwrap on its own output changes nothing further."""
    # Free for every case the corpus gains, and it is the property a formatter
    # most needs: a second pre-commit run must not keep rewriting the file.
    once = unwrap_markdown_prose(case.input).content
    assert unwrap_markdown_prose(once).content == once, case.name
