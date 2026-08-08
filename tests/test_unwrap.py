"""Tests for the command-line surface of the Markdown prose unwrap.

What the unwrap *does* to a document is specified by the conformance corpus
(`corpus/README.md`) and exercised by `test_corpus.py`, so that behavior is
deliberately absent here. What remains is the surface a corpus cannot describe
because no other implementation shares it: argument handling, file discovery,
the transcript skip, encoding failures, and the exit codes those produce.
"""

import io
import json
import sys

from markdown_prose_hooks.unwrap import (
    _collapse_segment,
    _describe_error,
    _match_glob_segment,
    _split_components,
    main,
    match_list_marker,
)


def test_cli_write_rewrites_the_file_and_reports_changed(tmp_path, capsys) -> None:
    """--write rewrites a wrapped file and the JSON summary reports the change."""
    doc = tmp_path / 'note.md'
    doc.write_text('A wrapped\nparagraph.\n', encoding='utf-8')
    exit_code = main(['--write', '--json', str(doc)])
    assert exit_code == 0
    assert doc.read_text(encoding='utf-8') == 'A wrapped paragraph.\n'
    assert json.loads(capsys.readouterr().out)['changed'] is True


def test_cli_reports_no_change_for_unwrapped_input(tmp_path, capsys) -> None:
    """Already-unwrapped input reports changed=false and does not rewrite."""
    doc = tmp_path / 'note.md'
    original = 'One clean line.\n'
    doc.write_text(original, encoding='utf-8')
    assert main(['--write', '--json', str(doc)]) == 0
    assert doc.read_text(encoding='utf-8') == original
    assert json.loads(capsys.readouterr().out)['changed'] is False


def test_cli_accepts_newline_delimited_file_list(tmp_path, capsys) -> None:
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


def test_cli_missing_file_list_emits_structured_error(tmp_path, capsys) -> None:
    """A missing --files-from path returns a JSON error instead of a traceback."""
    missing = tmp_path / 'missing.txt'

    assert main(['--json', '--files-from', str(missing)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is False
    assert payload['files'] == []
    assert 'cannot read --files-from' in payload['errors'][0]


def test_cli_skips_symlinked_markdown(tmp_path, capsys) -> None:
    """A symlink input never causes its target to be rewritten."""
    target = tmp_path / 'target.md'
    target.write_text('Wrapped prose\nmust stay.\n', encoding='utf-8')
    link = tmp_path / 'link.md'
    link.symlink_to(target)

    assert main(['--write', '--json', str(link)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload['files'] == []
    assert target.read_text(encoding='utf-8') == 'Wrapped prose\nmust stay.\n'


def test_cli_preserves_crlf_line_endings(tmp_path, capsys) -> None:
    """A rewrite removes only soft wraps and retains CRLF endings."""
    doc = tmp_path / 'crlf.md'
    doc.write_bytes(b'Wrapped prose\r\nuses CRLF.\r\n')

    assert main(['--write', '--json', str(doc)]) == 0

    capsys.readouterr()
    assert doc.read_bytes() == b'Wrapped prose uses CRLF.\r\n'


def test_cli_skips_transcript_like_markdown(tmp_path, capsys) -> None:
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


def test_cli_skips_timestamped_transcript_turns(tmp_path, capsys) -> None:
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


def test_cli_unwraps_long_prose_with_sparse_colon_intros(tmp_path, capsys) -> None:
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


def test_cli_non_utf8_file_list_emits_structured_error(tmp_path, capsys) -> None:
    """A non-UTF-8 file list returns JSON diagnostics without a traceback."""
    file_list = tmp_path / 'files.txt'
    file_list.write_bytes(b'\xff\xfe')

    assert main(['--json', '--files-from', str(file_list)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert 'cannot read --files-from' in payload['errors'][0]


def test_cli_non_utf8_markdown_emits_structured_error(tmp_path, capsys) -> None:
    """A non-UTF-8 Markdown input returns JSON diagnostics without a traceback."""
    doc = tmp_path / 'bad.md'
    doc.write_bytes(b'\xff\xfe')

    assert main(['--json', str(doc)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert 'not valid UTF-8' in payload['errors'][0]


def test_cli_fail_on_change_exits_nonzero_without_writing(tmp_path, capsys) -> None:
    """The gate reports a pending change and leaves the file as it found it."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', '--fail-on-change', str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)['changed'] is True
    assert doc.read_text(encoding='utf-8') == 'Prose that\nwraps.\n'


def test_cli_fail_on_change_exits_zero_when_already_unwrapped(tmp_path, capsys) -> None:
    """Nothing to do is a pass, which is what makes the flag usable as a gate."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that does not wrap.\n', encoding='utf-8')

    assert main(['--json', '--fail-on-change', str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)['changed'] is False


def test_cli_fail_on_change_still_rewrites_with_write(tmp_path, capsys) -> None:
    """Rewriting and failing compose, so a fixing run still stops the build."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', '--write', '--fail-on-change', str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)['changed'] is True
    assert doc.read_text(encoding='utf-8') == 'Prose that wraps.\n'


def test_cli_without_fail_on_change_reports_change_as_success(tmp_path, capsys) -> None:
    """The default stays report-only, so `pre-commit` decides the run's fate."""
    doc = tmp_path / 'doc.md'
    doc.write_text('Prose that\nwraps.\n', encoding='utf-8')

    assert main(['--json', str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)['changed'] is True


def test_cli_report_uses_lf_whatever_the_platform_translates(tmp_path) -> None:
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


def test_error_naming_survives_the_platform_choosing_the_exception(tmp_path) -> None:
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
    """CommonMark says 1-9 arabic digits, and `\\d` said 650 of them, or 680."""
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
