"""Tests for the command-line surface of the Markdown prose unwrap.

What the unwrap *does* to a document is specified by the conformance corpus
(`corpus/README.md`) and exercised by `test_corpus.py`, so that behavior is
deliberately absent here. What remains is the surface a corpus cannot describe
because no other implementation shares it: argument handling, file discovery,
the transcript skip, encoding failures, and the exit codes those produce.
"""

import io
import json
import re
import sys
from pathlib import Path

import pytest

from markdown_prose_hooks.unwrap import (
    _collapse_segment,
    _describe_error,
    _is_ignore_block_end,
    _is_ignore_block_start,
    _is_ignore_directive,
    _match_glob_segment,
    _split_components,
    main,
    match_list_marker,
)


def test_cli_write_rewrites_the_file_and_reports_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--write rewrites a wrapped file and the JSON summary reports the change."""
    doc = tmp_path / 'note.md'
    doc.write_text('A wrapped\nparagraph.\n', encoding='utf-8')
    exit_code = main(['--write', '--json', str(doc)])
    assert exit_code == 0
    assert doc.read_text(encoding='utf-8') == 'A wrapped paragraph.\n'
    assert json.loads(capsys.readouterr().out)['changed'] is True


def test_cli_reports_no_change_for_unwrapped_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Already-unwrapped input reports changed=false and does not rewrite."""
    doc = tmp_path / 'note.md'
    original = 'One clean line.\n'
    doc.write_text(original, encoding='utf-8')
    assert main(['--write', '--json', str(doc)]) == 0
    assert doc.read_text(encoding='utf-8') == original
    assert json.loads(capsys.readouterr().out)['changed'] is False


def test_cli_accepts_newline_delimited_file_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--files-from processes every newline-delimited Markdown path."""
    first = tmp_path / 'first.md'
    second = tmp_path / 'second.md'
    file_list = tmp_path / 'files.txt'
    first.write_text('One wrapped\nparagraph.\n', encoding='utf-8')
    second.write_text('Two wrapped\nparagraphs.\n', encoding='utf-8')
    file_list.write_text(f'{first}\n{second}\n', encoding='utf-8')

    assert main(['--write', '--json', '--files-from', str(file_list)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is True
    assert first.read_text(encoding='utf-8') == 'One wrapped paragraph.\n'
    assert second.read_text(encoding='utf-8') == 'Two wrapped paragraphs.\n'


def test_cli_missing_file_list_emits_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing --files-from path returns a JSON error instead of a traceback."""
    missing = tmp_path / 'missing.txt'

    assert main(['--json', '--files-from', str(missing)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is False
    assert payload['files'] == []
    assert 'cannot read --files-from' in payload['errors'][0]


def test_cli_skips_symlinked_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A symlink input never causes its target to be rewritten."""
    target = tmp_path / 'target.md'
    target.write_text('Wrapped prose\nmust stay.\n', encoding='utf-8')
    link = tmp_path / 'link.md'
    link.symlink_to(target)

    assert main(['--write', '--json', str(link)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['files'] == []
    assert target.read_text(encoding='utf-8') == 'Wrapped prose\nmust stay.\n'


def test_cli_preserves_crlf_line_endings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rewrite removes only soft wraps and retains CRLF endings."""
    doc = tmp_path / 'crlf.md'
    doc.write_bytes(b'Wrapped prose\r\nuses CRLF.\r\n')

    assert main(['--write', '--json', str(doc)]) == 0

    capsys.readouterr()
    assert doc.read_bytes() == b'Wrapped prose uses CRLF.\r\n'


def test_cli_skips_transcript_like_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repeated speaker turns protect transcript source evidence from rewrites."""
    doc = tmp_path / 'notes.md'
    original = (
        'MC:\n\n'
        'First source-evidence line.\n'
        'Second source-evidence line.\n\n'
        'JR:\n\n'
        'Third source-evidence line.\n'
        'Fourth source-evidence line.\n'
    )
    doc.write_text(original, encoding='utf-8')

    assert main(['--write', '--json', str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is False
    assert doc.read_text(encoding='utf-8') == original


def test_cli_skips_timestamped_transcript_turns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Timestamped speaker headings protect transcript evidence from rewrites."""
    doc = tmp_path / 'timestamped.md'
    original = (
        'MC 0:15\n'
        'First source-evidence line.\n'
        'Second source-evidence line.\n\n'
        'JR 0:28\n'
        'Third source-evidence line.\n'
        'Fourth source-evidence line.\n'
    )
    doc.write_text(original, encoding='utf-8')

    assert main(['--write', '--json', str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is False
    assert doc.read_text(encoding='utf-8') == original


def test_cli_unwraps_long_prose_with_sparse_colon_intros(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sparse colon headings do not misclassify a long prose document."""
    doc = tmp_path / 'design.md'
    filler = ''.join(
        f'Paragraph {index} wraps across two lines that the pass\n'
        'must join into one line.\n\n'
        for index in range(25)
    )
    original = f'# Design\n\nConcretely:\n\n{filler}Final note:\n'
    doc.write_text(original, encoding='utf-8')

    assert main(['--write', '--json', str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is True
    assert 'the pass must join into one line.' in doc.read_text(encoding='utf-8')


def test_cli_non_utf8_file_list_emits_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-UTF-8 file list returns JSON diagnostics without a traceback."""
    file_list = tmp_path / 'files.txt'
    file_list.write_bytes(b'\xff\xfe')

    assert main(['--json', '--files-from', str(file_list)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert 'cannot read --files-from' in payload['errors'][0]


def test_cli_non_utf8_markdown_emits_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-UTF-8 Markdown input returns JSON diagnostics without a traceback."""
    doc = tmp_path / 'bad.md'
    doc.write_bytes(b'\xff\xfe')

    assert main(['--json', str(doc)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert 'not valid UTF-8' in payload['errors'][0]


def test_cli_fail_on_change_exits_nonzero_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate reports a pending change and leaves the file as it found it."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', '--fail-on-change', str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)['changed'] is True
    assert doc.read_text(encoding='utf-8') == 'Prose that\nwraps.\n'


def test_cli_fail_on_change_exits_zero_when_already_unwrapped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing to do is a pass, which is what makes the flag usable as a gate."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that does not wrap.\n', encoding='utf-8')

    assert main(['--json', '--fail-on-change', str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)['changed'] is False


def test_cli_fail_on_change_still_rewrites_with_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rewriting and failing compose, so a fixing run still stops the build."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', '--write', '--fail-on-change', str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)['changed'] is True
    assert doc.read_text(encoding='utf-8') == 'Prose that wraps.\n'


def test_cli_without_fail_on_change_reports_change_as_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default stays report-only, so `pre-commit` decides the run's fate."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)['changed'] is True


def test_cli_report_uses_lf_whatever_the_platform_translates(tmp_path: Path) -> None:
    """The report's own line endings are the tool's to decide, not the host's.

    A text stream translates on write, so on Windows every report line and the
    whole `--json` payload would leave as CRLF -- making this program's output
    the one thing here whose line endings the platform picks, in a tool built to
    take that choice away. The CLI corpus compares `stdout.txt` byte for byte so
    a second implementation has something exact to match, and that contract only
    means something if both sides agree on the newline.

    A translating stream is substituted rather than the platform simulated,
    because the platform is not available to simulate on a POSIX runner and the
    translation is the whole of what differs.
    """
    doc = tmp_path / 'note.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')
    raw = io.BytesIO()
    translating = io.TextIOWrapper(raw, encoding='utf-8', newline='\r\n')

    saved = sys.stdout
    sys.stdout = translating
    try:
        main([str(doc)])
        translating.flush()
    finally:
        sys.stdout = saved

    written = raw.getvalue()
    assert written.endswith(b': removed 1 manual line break(s)\n')
    assert b'\r' not in written


def test_error_naming_survives_the_platform_choosing_the_exception(
    tmp_path: Path,
) -> None:
    """A directory is named as one however the platform reports it.

    Opening a directory raises `IsADirectoryError` on POSIX and
    `PermissionError` on Windows, so the exception class carries the platform
    just as its message does. The corpus compares the `--json` payload byte for
    byte across implementations, and that only holds if the condition, not the
    host's choice of errno, decides the word.
    """
    directory = tmp_path / 'sub'
    directory.mkdir()

    posix_shaped = IsADirectoryError(21, 'Is a directory')
    posix_shaped.filename = str(directory)
    windows_shaped = PermissionError(13, 'Permission denied')
    windows_shaped.filename = str(directory)

    assert _describe_error(posix_shaped) == 'is a directory'
    assert _describe_error(windows_shaped) == 'is a directory'

    denied = PermissionError(13, 'Permission denied')
    denied.filename = str(tmp_path / 'unreadable.md')
    assert _describe_error(denied) == 'permission denied'


def test_a_glob_star_matches_a_literal_star_in_a_name() -> None:
    """A wildcard still backtracks when the candidate itself contains a star."""
    # This is a matcher property rather than a CLI behavior, so it belongs here
    # and not in `corpus/cli/`: the fixture would need a file literally named
    # `*ax.md`, and Windows forbids `*` in a filename, so the checkout that
    # would have to carry it cannot exist. The Rust port carries the same vector
    # as a unit test of its own — the parity architecture puts matcher tests
    # below the corpus's altitude for exactly this reason.
    #
    # The bug it guards is a branch-order one. Testing the literal branch before
    # the wildcard branch makes `*` match `*` as a literal, so no backtrack
    # point is recorded and the pattern stops matching anything longer.
    assert _match_glob_segment('*x.md', '*ax.md')
    assert _match_glob_segment('a*b.md', 'a**b.md')
    assert _match_glob_segment('*', '**')


def test_a_glob_question_mark_matches_exactly_one_character() -> None:
    """`?` is a counted quantifier, and it counts characters rather than bytes."""
    assert _match_glob_segment('?.md', 'a.md')
    assert not _match_glob_segment('?.md', 'ab.md')
    # Three bytes, one character. A byte-indexing implementation reads this as
    # three and rejects it, which is the divergence the Rust port has to avoid.
    assert _match_glob_segment('?.md', '日.md')


def test_a_pattern_sees_the_path_as_written() -> None:
    """`..` resolves and `.` drops, because a pattern is matched against neither."""
    # Never routed through `Path` first: `Path('a/../b.md').as_posix()` keeps the
    # `..`, so a pattern spelled like the resolved path would not match the file
    # it plainly names.
    assert _split_components('a/../b.md') == ('b.md',)
    assert _split_components('./a//b.md') == ('a', 'b.md')
    assert _split_components('../outside.md') == ('outside.md',)


def test_star_runs_collapse_so_spelling_does_not_change_meaning() -> None:
    """A segment of only stars is `**`; stars beside other characters are one `*`."""
    assert repr(_collapse_segment('***')) == '**'
    assert repr(_collapse_segment('**')) == '**'
    assert _collapse_segment('*') == '*'
    assert _collapse_segment('a**b') == 'a*b'


def test_an_ordered_list_marker_is_ascii_digits_only() -> None:
    r"""CommonMark says 1-9 arabic digits; `\d` said 650, then 680, now 760."""
    # A matcher-level pin rather than only a corpus case, because this is where
    # the rule lives and where a second implementation reads it. The corpus
    # case shows the consequence; this shows the boundary.
    #
    # `\d` was also not one predicate: it is the runtime's `Nd` category, which
    # is 650 code points on 3.10's Unicode 13.0 and 680 on 3.13's 15.1. Both
    # interpreters are supported here, so the tool did not agree with itself,
    # and a second implementation would have had to pin a Unicode version to
    # agree with either one of them.
    assert match_list_marker('1. x') == ('1. ', 3, 'x')
    assert match_list_marker('١. x') is None  # ARABIC-INDIC ONE
    assert match_list_marker('१. x') is None  # DEVANAGARI ONE


def test_the_ignore_directive_is_matched_exactly() -> None:
    """One word in a one-line comment, with the quote markers peeled first."""
    # A matcher-level pin rather than only a corpus case, for the reason the
    # marker test above gives: this is where the boundary lives, and the two
    # implementations have to agree on it character for character. The two
    # degenerate comments at the end are the ones a slice reads as an empty
    # body, because there the opening and closing delimiters overlap.
    assert _is_ignore_directive('<!-- unwrap-ignore -->')
    assert _is_ignore_directive('<!--unwrap-ignore-->')
    assert _is_ignore_directive('  <!--  unwrap-ignore  -->  ')
    assert _is_ignore_directive('> <!-- unwrap-ignore -->')
    assert _is_ignore_directive('>> <!-- unwrap-ignore -->')
    assert not _is_ignore_directive('<!-- unwrap-ignore for now -->')
    assert not _is_ignore_directive('<!-- unwrap-ignore --> trailing')
    assert not _is_ignore_directive('unwrap-ignore')
    assert not _is_ignore_directive('<!-- unwrap-ignore')
    assert not _is_ignore_directive('<!-->')
    assert not _is_ignore_directive('<!---->')
    # The region markers are different words, not longer spellings of this one.
    assert not _is_ignore_directive('<!-- unwrap-ignore-start -->')
    assert not _is_ignore_directive('<!-- unwrap-ignore-end -->')


def test_the_region_markers_are_matched_exactly() -> None:
    """The same rules as the line form, and the three names stay distinct."""
    # Written out per marker rather than looped, because what is being pinned is
    # which string means which thing -- a loop over a table of names would pass
    # just as happily with the two swapped.
    assert _is_ignore_block_start('<!-- unwrap-ignore-start -->')
    assert _is_ignore_block_start('<!--unwrap-ignore-start-->')
    assert _is_ignore_block_start('  <!--  unwrap-ignore-start  -->  ')
    assert _is_ignore_block_start('> <!-- unwrap-ignore-start -->')
    assert not _is_ignore_block_start('<!-- unwrap-ignore-start for now -->')
    assert not _is_ignore_block_start('<!-- unwrap-ignore -->')
    assert not _is_ignore_block_start('<!-- unwrap-ignore-end -->')
    assert not _is_ignore_block_start('<!-- unwrap-ignore-started -->')
    assert _is_ignore_block_end('<!-- unwrap-ignore-end -->')
    assert _is_ignore_block_end('<!--unwrap-ignore-end-->')
    assert _is_ignore_block_end('  <!--  unwrap-ignore-end  -->  ')
    assert _is_ignore_block_end('> <!-- unwrap-ignore-end -->')
    assert not _is_ignore_block_end('<!-- unwrap-ignore -->')
    assert not _is_ignore_block_end('<!-- unwrap-ignore-start -->')
    assert not _is_ignore_block_end('<!-- unwrap-ignore-ended -->')


def test_the_negative_number_rule_is_the_tools_own(tmp_path: Path) -> None:
    r"""A `-`-leading token is classified by this tool's pattern, not argparse's.

    The vectors are the ones `is_negative_number` carries on the Rust side, and
    the point of running them through `main` rather than against the pattern is
    that the pattern alone cannot fail the way this can. `_build_parser` assigns
    `_negative_number_matcher`, and an interpreter that renamed that attribute
    would leave the assignment writing where nothing reads and take argparse's
    own rule back -- silently, and differently per version: through 3.13 argparse
    agrees with this tool, and 3.14's `-\.?\d` stops at the first digit, so
    `-1a` and `-5.` would become paths and `--write` would format the file named
    beside them. Going through `main` is what makes that a red test here rather
    than a divergence found in the CLI tier on one matrix leg.
    """
    doc = tmp_path / 'note.md'
    original = 'A wrapped\nparagraph.\n'

    for token in ('-1a', '-5.', '-١٢'):
        doc.write_text(original, encoding='utf-8')
        with pytest.raises(SystemExit) as raised:
            main(['--write', token, str(doc)])
        assert raised.value.code == 2, token
        assert doc.read_text(encoding='utf-8') == original, token

    # The accepting half, so a pattern narrowed until it matches nothing would
    # not pass this test by rejecting everything. Each token is bound as a path,
    # names no file, and is skipped the way any missing path is -- which leaves
    # exit 0 and the file named beside it formatted, where a token read as an
    # option would have stopped the run at 2 before anything was opened.
    for token in ('-12', '-.5', '-1.5'):
        doc.write_text(original, encoding='utf-8')
        assert main(['--write', token, str(doc)]) == 0, token
        assert doc.read_text(encoding='utf-8') == 'A wrapped paragraph.\n', token

    # The same tokens with a newline on the end. `$` in a Python pattern matches
    # before a token's final newline where the Rust rule reads every byte, so an
    # end anchor that stops one byte early is a divergence rather than a
    # spelling: each of these binds as a path on one implementation and as an
    # unknown option on the other, and `--write` beside a real path formats the
    # tree on the first where the second reports an error and opens nothing.
    for token in ('-12\n', '-.5\n', '-1.5\n'):
        doc.write_text(original, encoding='utf-8')
        with pytest.raises(SystemExit) as raised:
            main(['--write', token, str(doc)])
        assert raised.value.code == 2, token
        assert doc.read_text(encoding='utf-8') == original, token


def test_the_whitespace_set_has_not_moved_under_the_interpreter() -> None:
    r"""`str.strip()` still removes exactly the 29 code points the Rust writes out.

    `str.strip()`, `str.isspace()` and `\s` on a `str` pattern share one set:
    Unicode `White_Space` plus the four C0 separators. All three are checked,
    not just the one the tool calls most: `is_python_space` is pinned as the
    equivalent of all three, and the matcher constants use `\s` directly, so a
    runtime that moved one of them without the others would leave a
    `strip()`-only guard green while the transform had already diverged.
    `is_python_space` in `src/scan.rs` writes those 29 out by hand rather than
    delegating to
    `char::is_whitespace`, which is `White_Space` alone and so 25, and that file
    carries the matching drift detector for its own side. This is the detector for
    this one: the two implementations agree because both are pinned to this list,
    not because two runtimes happen to define it the same way, so an interpreter
    that moves it has to fail here rather than quietly change what the tool reads
    as a blank line.

    Measured identical on 3.10, 3.11, 3.12, 3.13 and 3.14 on 2026-09-04.
    """
    expected = (
        # tab, newline, vertical tab, form feed, carriage return
        0x09,
        0x0A,
        0x0B,
        0x0C,
        0x0D,
        # file, group, record and unit separator: the four Rust does not carry
        0x1C,
        0x1D,
        0x1E,
        0x1F,
        0x20,  # space
        0x85,  # next line
        0xA0,  # no-break space
        0x1680,  # ogham space mark
        0x2000,
        0x2001,
        0x2002,
        0x2003,
        0x2004,
        0x2005,
        0x2006,
        0x2007,
        0x2008,
        0x2009,
        0x200A,
        0x2028,  # line separator
        0x2029,  # paragraph separator
        0x202F,  # narrow no-break space
        0x205F,  # medium mathematical space
        0x3000,  # ideographic space
    )
    apis = (
        ('str.strip()', lambda c: c.strip() == ''),
        ('str.isspace()', lambda c: c.isspace()),
        (r'\s', lambda c: re.fullmatch(r'\s', c) is not None),
    )
    for name, selects in apis:
        found = tuple(cp for cp in range(0x110000) if selects(chr(cp)))
        assert found == expected, (
            f'{name} no longer selects exactly this set; '
            f'gained {[f"U+{c:04X}" for c in set(found) - set(expected)]}, '
            f'lost {[f"U+{c:04X}" for c in set(expected) - set(found)]}'
        )


def test_the_characters_that_fold_into_ascii_have_not_moved() -> None:
    """Lowercasing still maps only these onto ASCII.

    The HTML block matcher lowercases a whole line and looks for an ASCII needle
    such as `</script>`, so a character whose lowercase *contains* ASCII can
    complete one. Twenty-six of those are `A`-`Z`. The other two are the reason the
    line cannot simply be folded with `str.lower`'s ASCII-only counterpart, and the
    reason this set is worth pinning: it is defined by the runtime's case tables,
    which do move -- 1393 code points gained a lowercase mapping by 3.11 and 1460
    by 3.14 -- and none of those additions landed in this set only because none of
    them folded into ASCII.

    `U+0130` is the length-changing one, folding to two code points, which is safe
    here only because the fold feeds a containment test and never an offset.

    Measured on 3.10 through 3.14 on 2026-09-04, and matched by the Rust detector
    in `src/scan.rs`.
    """
    expected = (*range(ord('A'), ord('Z') + 1), 0x0130, 0x212A)
    found = tuple(
        cp
        for cp in range(0x110000)
        if (lowered := chr(cp).lower()) != chr(cp) and any(c.isascii() for c in lowered)
    )
    assert found == expected, (
        'lowercasing now maps a different set onto ASCII; '
        f'gained {[f"U+{c:04X}" for c in set(found) - set(expected)]}, '
        f'lost {[f"U+{c:04X}" for c in set(expected) - set(found)]}'
    )
