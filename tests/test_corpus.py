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
        self.expected = _read_verbatim(directory / 'expected.md')

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


def _load_corpus() -> list[Case]:
    """Return every case in the corpus, ordered by slug."""
    return [Case(d) for d in sorted(_CORPUS.iterdir()) if d.is_dir()]


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
