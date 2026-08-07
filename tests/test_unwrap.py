"""Tests for the Markdown prose unwrap script.

The script removes manual (soft-wrap) line breaks from paragraph prose while
leaving every structural element — code fences, lists, blockquotes' shape, YAML
front matter, hard breaks, and bold-label rows — untouched. Each test pins one
of those guarantees, so the conservative boundary is exercised directly.
"""

import json

from markdown_prose_hooks.unwrap import main, unwrap_markdown_prose

# -- what it unwraps --


def test_soft_wrapped_paragraph_joins_into_one_line() -> None:
    """A soft-wrapped paragraph collapses to a single line."""
    result = unwrap_markdown_prose("A wrapped\nparagraph here.\n")
    assert result.content == "A wrapped paragraph here.\n"
    assert result.paragraphs_unwrapped == 1
    assert result.line_breaks_removed == 1


def test_blank_line_separates_paragraphs() -> None:
    """A blank line keeps two paragraphs distinct, each joined on its own."""
    text = "First para\nline two.\n\nSecond para\nline two.\n"
    assert unwrap_markdown_prose(text).content == (
        "First para line two.\n\nSecond para line two.\n"
    )


def test_prose_inside_a_blockquote_joins_but_keeps_the_marker() -> None:
    """Blockquote prose unwraps while the '>' prefix is preserved."""
    result = unwrap_markdown_prose("> quoted line\n> and its wrap\n")
    assert result.content == "> quoted line and its wrap\n"


def test_prose_that_merely_ends_in_a_link_still_unwraps() -> None:
    """Ending in a link is not enough to be structural; the whole line must be links."""
    text = "See the [architecture doc](docs/architecture.md)\nfor the rationale.\n"
    assert unwrap_markdown_prose(text).content == (
        "See the [architecture doc](docs/architecture.md) for the rationale.\n"
    )


def test_one_link_only_line_inside_a_paragraph_still_unwraps() -> None:
    """A lone link-only line is a wrap point, because a block takes two in a row."""
    text = "Recorded in\n[the plan](docs/plan.md)\nand worth reading first.\n"
    assert unwrap_markdown_prose(text).content == (
        "Recorded in [the plan](docs/plan.md) and worth reading first.\n"
    )


def test_a_pipe_inside_inline_code_still_unwraps() -> None:
    """A pipe in a code span is literal text, not table syntax, so prose joins."""
    text = "Alpha beta with a `... | last` terminal that yields\nnull on no match.\n"
    assert unwrap_markdown_prose(text).content == (
        "Alpha beta with a `... | last` terminal that yields null on no match.\n"
    )


def test_a_pipe_inside_a_double_backtick_span_still_unwraps() -> None:
    """A span delimited by ``` `` ``` may hold a lone backtick and still unwrap."""
    text = "Use ``a | b` c`` as the filter\nwhen the value is absent.\n"
    assert unwrap_markdown_prose(text).content == (
        "Use ``a | b` c`` as the filter when the value is absent.\n"
    )


# -- what it leaves alone --


def test_fenced_code_block_is_untouched() -> None:
    """Lines inside a fenced code block are never joined."""
    text = "```python\nx = 1\ny = 2\n```\n"
    assert unwrap_markdown_prose(text).content == text


def test_fence_character_and_length_variants_are_untouched() -> None:
    """Tilde and longer backtick fences preserve their complete bodies."""
    for text in ("~~~\na\nb\n~~~\n", "````python\na\nb\n````\n"):
        assert unwrap_markdown_prose(text).content == text


def test_flat_list_is_untouched() -> None:
    """Distinct list items stay on their own lines."""
    text = "- one\n- two\n- three\n"
    assert unwrap_markdown_prose(text).content == text


def test_bold_label_rows_are_preserved() -> None:
    """Consecutive bold-label rows keep their line breaks (softbreak-as-<br>)."""
    text = "**Detect:** reads the title\n**Action:** blocks the merge\n"
    assert unwrap_markdown_prose(text).content == text


def test_a_wrapped_last_label_value_joins_without_collapsing_the_block() -> None:
    """A trailing soft wrap joins its own row; the rows above keep their breaks."""
    text = (
        "**Date:** 2026-08-06\n"
        "**Status:** Draft\n"
        "**Scope:** the whole pipeline including\n"
        "the parts nobody owns yet.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "**Date:** 2026-08-06\n"
        "**Status:** Draft\n"
        "**Scope:** the whole pipeline including the parts nobody owns yet.\n"
    )


def test_a_wrapped_middle_label_value_joins_only_its_own_row() -> None:
    """A wrap under a middle label joins that row and leaves the others alone."""
    text = (
        "**Date:** 2026-08-06\n"
        "**Scope:** the whole pipeline including\n"
        "the parts nobody owns yet.\n"
        "**Status:** Draft\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "**Date:** 2026-08-06\n"
        "**Scope:** the whole pipeline including the parts nobody owns yet.\n"
        "**Status:** Draft\n"
    )


def test_a_wrapped_label_value_is_counted_as_one_unwrap() -> None:
    """Joining label-row tails reports the block once, with its breaks removed."""
    result = unwrap_markdown_prose(
        "**Scope:** the whole pipeline including\nthe parts nobody owns yet.\n",
    )
    assert result.paragraphs_unwrapped == 1
    assert result.line_breaks_removed == 1


def test_a_badge_block_keeps_every_link_on_its_own_line() -> None:
    """Consecutive link-only lines are a block, so the run is never joined."""
    text = (
        "[![Alpha](https://img.example.com/a.svg?style=plastic)][ref]\n"
        "[![Bravo](https://img.example.com/b.svg)](https://example.com/b)\n"
        "![Charlie](https://img.example.com/c.svg)\n"
    )
    assert unwrap_markdown_prose(text).content == text


def test_a_badge_block_does_not_absorb_the_prose_beneath_it() -> None:
    """A badge block ends where prose starts, and that prose unwraps on its own."""
    text = (
        "[![Alpha](https://img.example.com/a.svg)][ref]\n"
        "[![Bravo](https://img.example.com/b.svg)][ref]\n"
        "Prose that\nwraps.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "[![Alpha](https://img.example.com/a.svg)][ref]\n"
        "[![Bravo](https://img.example.com/b.svg)][ref]\n"
        "Prose that wraps.\n"
    )


def test_a_blockquoted_badge_block_keeps_its_links_on_their_lines() -> None:
    """A badge block inside a blockquote is still a block; the marker hides nothing."""
    text = (
        "> [![Alpha](https://img.example.com/a.svg)][ref]\n"
        "> [![Bravo](https://img.example.com/b.svg)](https://example.com/b)\n"
        "> ![Charlie](https://img.example.com/c.svg)\n"
    )
    assert unwrap_markdown_prose(text).content == text


def test_a_deeper_quoted_badge_line_stays_in_the_run() -> None:
    """A nested marker does not break the run, so badges keep off the prose below."""
    text = (
        "> > [![Alpha](https://img.example.com/a.svg)][ref]\n"
        "> [![Bravo](https://img.example.com/b.svg)][ref]\n"
        "Prose that\nwraps.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "> > [![Alpha](https://img.example.com/a.svg)][ref]\n"
        "> [![Bravo](https://img.example.com/b.svg)][ref]\n"
        "Prose that wraps.\n"
    )


def test_a_lazily_continued_badge_block_is_preserved() -> None:
    """A badge line lacking the marker is a lazy continuation, so it joins the run."""
    text = (
        "> [![Alpha](https://img.example.com/a.svg)][ref]\n"
        "[![Bravo](https://img.example.com/b.svg)][ref]\n"
    )
    assert unwrap_markdown_prose(text).content == text


def test_a_run_does_not_reach_back_over_a_quote_boundary() -> None:
    """Lazy continuation only follows a quote, so an unquoted run stops at one."""
    text = (
        "Read\n"
        "[the plan](docs/plan.md)\n"
        "> [![Alpha](https://img.example.com/a.svg)][ref]\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "Read [the plan](docs/plan.md)\n"
        "> [![Alpha](https://img.example.com/a.svg)][ref]\n"
    )


def test_a_badge_block_indented_under_a_list_item_is_preserved() -> None:
    """Indentation with no marker in front is an item's content column, not code."""
    text = (
        "- item\n"
        "      [![Alpha](https://img.example.com/a.svg)][ref]\n"
        "      [![Bravo](https://img.example.com/b.svg)][ref]\n"
    )
    assert unwrap_markdown_prose(text).content == text


def test_quoted_indented_code_does_not_open_a_badge_run() -> None:
    """Indentation past the marker is code, as the container logic already reads it."""
    text = ">     [code](url)\n> [the plan](docs/plan.md)\n> and worth reading.\n"
    assert unwrap_markdown_prose(text).content == (
        ">     [code](url)\n> [the plan](docs/plan.md) and worth reading.\n"
    )


def test_one_link_only_line_inside_a_blockquote_still_unwraps() -> None:
    """The run floor holds inside a blockquote, so quoted prose keeps unwrapping."""
    text = "> Recorded in\n> [the plan](docs/plan.md)\n> and worth reading first.\n"
    assert unwrap_markdown_prose(text).content == (
        "> Recorded in [the plan](docs/plan.md) and worth reading first.\n"
    )


def test_yaml_front_matter_is_preserved() -> None:
    """Front matter passes through verbatim; prose beneath it still joins."""
    text = "---\ntitle: x\n---\n\nProse that\nwraps.\n"
    assert unwrap_markdown_prose(text).content == (
        "---\ntitle: x\n---\n\nProse that wraps.\n"
    )


def test_hard_break_line_is_preserved() -> None:
    """A line ending in a Markdown hard break is left intact."""
    text = "line with a break  \nnext line\n"
    assert unwrap_markdown_prose(text).content == text


def test_nested_list_is_preserved() -> None:
    """Nested list items remain distinct from their parent item's prose."""
    text = (
        "- Parent item wrapped\n"
        "  onto two lines.\n"
        "  - Nested item also wrapped\n"
        "    onto two lines.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "- Parent item wrapped onto two lines.\n"
        "  - Nested item also wrapped onto two lines.\n"
    )


def test_ordered_list_continuations_use_marker_width() -> None:
    """Ordered items unwrap at the indentation implied by each marker."""
    text = (
        "1. First item wraps\n"
        "   over two lines.\n"
        "10. Tenth item wraps\n"
        "    over two lines.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "1. First item wraps over two lines.\n10. Tenth item wraps over two lines.\n"
    )


def test_lettered_subitems_remain_structural() -> None:
    """Lettered enumerators stay separate from their ordered parent item."""
    text = (
        "3. For each record:\n"
        "   a. Draw a sentence count.\n"
        "   b. Generate that many sentences.\n"
    )
    assert unwrap_markdown_prose(text).content == text


def test_fenced_code_inside_blockquote_is_preserved() -> None:
    """Every line of a fenced block inside a blockquote remains untouched."""
    text = '> ```python\n> print("hello")\n> second_line()\n> ```\n'
    assert unwrap_markdown_prose(text).content == text


def test_github_alert_marker_stays_on_its_own_line() -> None:
    """A GFM alert marker remains structural while its prose unwraps."""
    text = "> [!NOTE]\n> Alert prose wraps\n> over two lines.\n"
    assert unwrap_markdown_prose(text).content == (
        "> [!NOTE]\n> Alert prose wraps over two lines.\n"
    )


def test_indented_code_inside_blockquote_is_preserved() -> None:
    """Four-space-indented blockquote content remains an indented code block."""
    text = ">     code one\n>     code two\n"
    assert unwrap_markdown_prose(text).content == text


def test_raw_html_inside_blockquote_preserves_internal_blank_line() -> None:
    """A raw blockquote HTML body stays verbatim through its closing tag."""
    text = "> <pre>\n> raw line one\n>\n> raw line two\n> raw line three\n> </pre>\n"
    assert unwrap_markdown_prose(text).content == text


def test_multiline_html_comment_inside_blockquote_is_preserved() -> None:
    """A blockquote comment body remains verbatim through its closing marker."""
    text = "> <!--\n> comment one\n> comment two\n> -->\n"
    assert unwrap_markdown_prose(text).content == text


def test_multiline_html_block_is_preserved() -> None:
    """HTML block contents remain verbatim while surrounding prose unwraps."""
    text = (
        "Leading prose\n"
        "wraps.\n\n"
        "<div>\n"
        "line one\n"
        "line two\n"
        "</div>\n\n"
        "Trailing prose\n"
        "wraps.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "Leading prose wraps.\n\n"
        "<div>\n"
        "line one\n"
        "line two\n"
        "</div>\n\n"
        "Trailing prose wraps.\n"
    )


def test_blank_line_inside_raw_html_block_is_preserved() -> None:
    """Blank lines do not end raw preformatted HTML before its closing tag."""
    text = "<pre>\nraw line one\n\nraw line two\nraw line three\n</pre>\n"
    assert unwrap_markdown_prose(text).content == text


def test_multiline_html_comment_is_preserved() -> None:
    """Comment bodies remain verbatim while surrounding prose unwraps."""
    text = (
        "Leading prose\n"
        "wraps.\n\n"
        "<!--\n"
        "comment line one\n"
        "comment line two\n"
        "-->\n\n"
        "Trailing prose\n"
        "wraps.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "Leading prose wraps.\n\n"
        "<!--\n"
        "comment line one\n"
        "comment line two\n"
        "-->\n\n"
        "Trailing prose wraps.\n"
    )


def test_commonmark_html_literal_blocks_are_preserved() -> None:
    """Processing instructions, declarations, and CDATA stay byte-for-byte."""
    for text in (
        "<?processing\nline one\nline two\n?>\n",
        "<!DOCTYPE\nline one\nline two\n>\n",
        "<![CDATA[\nline one\nline two\n]]>\n",
    ):
        assert unwrap_markdown_prose(text).content == text


def test_cdata_inside_blockquote_is_preserved() -> None:
    """A blockquote CDATA body remains verbatim through its terminator."""
    text = "> <![CDATA[\n> line one\n> line two\n> ]]>\n"
    assert unwrap_markdown_prose(text).content == text


def test_inline_speaker_turns_keep_their_boundaries() -> None:
    """Wrapped speaker turns unwrap within each turn without joining speakers."""
    text = (
        "Alex: First turn wraps\n"
        "over two lines.\n"
        "Sam: Second turn wraps\n"
        "over two lines.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "Alex: First turn wraps over two lines.\n"
        "Sam: Second turn wraps over two lines.\n"
    )


def test_multiword_speaker_turns_keep_their_boundaries() -> None:
    """Multi-word speaker names remain separate while each turn unwraps."""
    text = (
        "Alex Smith: First turn wraps\n"
        "over two lines.\n"
        "Sam Lee: Second turn wraps\n"
        "over two lines.\n"
    )
    assert unwrap_markdown_prose(text).content == (
        "Alex Smith: First turn wraps over two lines.\n"
        "Sam Lee: Second turn wraps over two lines.\n"
    )


def test_a_gfm_table_is_untouched() -> None:
    """Header, delimiter, and body rows all keep their own lines."""
    text = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
    assert unwrap_markdown_prose(text).content == text


def test_a_table_directly_after_a_paragraph_is_untouched() -> None:
    """A paragraph joins up to the table, and the table keeps every row."""
    text = "Intro prose that\nwraps here.\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert unwrap_markdown_prose(text).content == (
        "Intro prose that wraps here.\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    )


def test_a_table_row_whose_cells_hold_code_spans_is_untouched() -> None:
    """Masking code spans still leaves a real row's own pipes visible."""
    text = "| `a|b` | c |\n| --- | --- |\n| `d|e` | f |\n"
    assert unwrap_markdown_prose(text).content == text


def test_a_bare_pipe_in_prose_stays_wrapped() -> None:
    """A bare pipe is ambiguous enough to stay structural, protecting tables."""
    text = "Alpha beta with a plain | pipe that yields\nnull on no match.\n"
    assert unwrap_markdown_prose(text).content == text


def test_an_unterminated_backtick_run_stays_structural() -> None:
    """An unclosed span masks nothing, so its pipe still reads as table syntax."""
    text = "Alpha beta with a `... | last that yields\nnull on no match.\n"
    assert unwrap_markdown_prose(text).content == text


# -- properties --


def test_unwrap_is_idempotent() -> None:
    """Unwrapping an already-unwrapped document changes nothing."""
    once = unwrap_markdown_prose("a\nb\nc\n").content
    assert unwrap_markdown_prose(once).content == once


def test_utf8_bom_front_matter_is_preserved() -> None:
    """A UTF-8 BOM does not hide YAML front matter from the parser."""
    text = "\ufeff---\ntitle: Example\n---\n\nBody prose\nwraps.\n"
    assert unwrap_markdown_prose(text).content == (
        "\ufeff---\ntitle: Example\n---\n\nBody prose wraps.\n"
    )


# -- the command-line interface --


def test_cli_write_rewrites_the_file_and_reports_changed(tmp_path, capsys) -> None:
    """--write rewrites a wrapped file and the JSON summary reports the change."""
    doc = tmp_path / "note.md"
    doc.write_text("A wrapped\nparagraph.\n", encoding="utf-8")
    exit_code = main(["--write", "--json", str(doc)])
    assert exit_code == 0
    assert doc.read_text(encoding="utf-8") == "A wrapped paragraph.\n"
    assert json.loads(capsys.readouterr().out)["changed"] is True


def test_cli_reports_no_change_for_unwrapped_input(tmp_path, capsys) -> None:
    """Already-unwrapped input reports changed=false and does not rewrite."""
    doc = tmp_path / "note.md"
    original = "One clean line.\n"
    doc.write_text(original, encoding="utf-8")
    assert main(["--write", "--json", str(doc)]) == 0
    assert doc.read_text(encoding="utf-8") == original
    assert json.loads(capsys.readouterr().out)["changed"] is False


def test_cli_accepts_newline_delimited_file_list(tmp_path, capsys) -> None:
    """--files-from processes every newline-delimited Markdown path."""
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    file_list = tmp_path / "files.txt"
    first.write_text("One wrapped\nparagraph.\n", encoding="utf-8")
    second.write_text("Two wrapped\nparagraphs.\n", encoding="utf-8")
    file_list.write_text(f"{first}\n{second}\n", encoding="utf-8")

    assert main(["--write", "--json", "--files-from", str(file_list)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    assert first.read_text(encoding="utf-8") == "One wrapped paragraph.\n"
    assert second.read_text(encoding="utf-8") == "Two wrapped paragraphs.\n"


def test_cli_missing_file_list_emits_structured_error(tmp_path, capsys) -> None:
    """A missing --files-from path returns a JSON error instead of a traceback."""
    missing = tmp_path / "missing.txt"

    assert main(["--json", "--files-from", str(missing)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is False
    assert payload["files"] == []
    assert "cannot read --files-from" in payload["errors"][0]


def test_cli_skips_symlinked_markdown(tmp_path, capsys) -> None:
    """A symlink input never causes its target to be rewritten."""
    target = tmp_path / "target.md"
    target.write_text("Wrapped prose\nmust stay.\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)

    assert main(["--write", "--json", str(link)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == []
    assert target.read_text(encoding="utf-8") == "Wrapped prose\nmust stay.\n"


def test_cli_preserves_crlf_line_endings(tmp_path, capsys) -> None:
    """A rewrite removes only soft wraps and retains CRLF endings."""
    doc = tmp_path / "crlf.md"
    doc.write_bytes(b"Wrapped prose\r\nuses CRLF.\r\n")

    assert main(["--write", "--json", str(doc)]) == 0

    capsys.readouterr()
    assert doc.read_bytes() == b"Wrapped prose uses CRLF.\r\n"


def test_cli_skips_transcript_like_markdown(tmp_path, capsys) -> None:
    """Repeated speaker turns protect transcript source evidence from rewrites."""
    doc = tmp_path / "notes.md"
    original = (
        "MC:\n\n"
        "First source-evidence line.\n"
        "Second source-evidence line.\n\n"
        "JR:\n\n"
        "Third source-evidence line.\n"
        "Fourth source-evidence line.\n"
    )
    doc.write_text(original, encoding="utf-8")

    assert main(["--write", "--json", str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is False
    assert doc.read_text(encoding="utf-8") == original


def test_cli_skips_timestamped_transcript_turns(tmp_path, capsys) -> None:
    """Timestamped speaker headings protect transcript evidence from rewrites."""
    doc = tmp_path / "timestamped.md"
    original = (
        "MC 0:15\n"
        "First source-evidence line.\n"
        "Second source-evidence line.\n\n"
        "JR 0:28\n"
        "Third source-evidence line.\n"
        "Fourth source-evidence line.\n"
    )
    doc.write_text(original, encoding="utf-8")

    assert main(["--write", "--json", str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is False
    assert doc.read_text(encoding="utf-8") == original


def test_cli_unwraps_long_prose_with_sparse_colon_intros(tmp_path, capsys) -> None:
    """Sparse colon headings do not misclassify a long prose document."""
    doc = tmp_path / "design.md"
    filler = "".join(
        f"Paragraph {index} wraps across two lines that the pass\n"
        "must join into one line.\n\n"
        for index in range(25)
    )
    original = f"# Design\n\nConcretely:\n\n{filler}Final note:\n"
    doc.write_text(original, encoding="utf-8")

    assert main(["--write", "--json", str(doc)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    assert "the pass must join into one line." in doc.read_text(encoding="utf-8")


def test_cli_non_utf8_file_list_emits_structured_error(tmp_path, capsys) -> None:
    """A non-UTF-8 file list returns JSON diagnostics without a traceback."""
    file_list = tmp_path / "files.txt"
    file_list.write_bytes(b"\xff\xfe")

    assert main(["--json", "--files-from", str(file_list)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert "cannot read --files-from" in payload["errors"][0]


def test_cli_non_utf8_markdown_emits_structured_error(tmp_path, capsys) -> None:
    """A non-UTF-8 Markdown input returns JSON diagnostics without a traceback."""
    doc = tmp_path / "bad.md"
    doc.write_bytes(b"\xff\xfe")

    assert main(["--json", str(doc)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert "not valid UTF-8" in payload["errors"][0]


def test_cli_fail_on_change_exits_nonzero_without_writing(tmp_path, capsys) -> None:
    """The gate reports a pending change and leaves the file as it found it."""
    doc = tmp_path / "doc.md"
    doc.write_text("Prose that\nwraps.\n", encoding="utf-8")

    assert main(["--json", "--fail-on-change", str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert doc.read_text(encoding="utf-8") == "Prose that\nwraps.\n"


def test_cli_fail_on_change_exits_zero_when_already_unwrapped(tmp_path, capsys) -> None:
    """Nothing to do is a pass, which is what makes the flag usable as a gate."""
    doc = tmp_path / "doc.md"
    doc.write_text("Prose that does not wrap.\n", encoding="utf-8")

    assert main(["--json", "--fail-on-change", str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)["changed"] is False


def test_cli_fail_on_change_still_rewrites_with_write(tmp_path, capsys) -> None:
    """Rewriting and failing compose, so a fixing run still stops the build."""
    doc = tmp_path / "doc.md"
    doc.write_text("Prose that\nwraps.\n", encoding="utf-8")

    assert main(["--json", "--write", "--fail-on-change", str(doc)]) == 1

    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert doc.read_text(encoding="utf-8") == "Prose that wraps.\n"


def test_cli_without_fail_on_change_reports_change_as_success(tmp_path, capsys) -> None:
    """The default stays report-only, so `pre-commit` decides the run's fate."""
    doc = tmp_path / "doc.md"
    doc.write_text("Prose that\nwraps.\n", encoding="utf-8")

    assert main(["--json", str(doc)]) == 0

    assert json.loads(capsys.readouterr().out)["changed"] is True
