//! The line state machine: the pass that actually rewrites the document.
//!
//! Python holds this state in closure variables that a nested `flush()` mutates
//! from inside the loop. Rust cannot express that shape, so the state lives in a
//! struct and `flush` is a method — but the *order* of the branches below is the
//! specification, not a style choice, and it is reproduced exactly. Two
//! orderings look arbitrary and are not: the HTML-block branch runs before the
//! blank-line branch, which is the only thing that lets a blank line close a
//! non-raw block; and the list-marker branch flushes unconditionally where the
//! blockquote branch does not.
//!
//! Every expected value in the tests below came from running the Python, and
//! `tests/corpus.rs` judges the whole of it against the conformance corpus.

use crate::UnwrapResult;
use crate::code_span::contains_unmasked_pipe;
use crate::label::{is_label_line, is_speaker_prefix, is_whole_line_bold};
use crate::links::link_block_indexes;
use crate::scan::{
    has_hard_break, is_alpha_list_line, is_closing_fence, is_gfm_alert, is_link_reference,
    is_list_line, is_raw_html_tag, is_setext_line, is_thematic_break, match_blockquote,
    match_list_marker, match_opening_fence, match_opening_html_block,
    match_opening_html_literal_terminator, py_splitlines_keepends, py_trim, py_trim_end,
    py_trim_start, split_eol, starts_front_matter,
};

/// Prefixes that carry their own block-level grammar wherever they appear.
///
/// Shared by both predicates below because the Python spells the same tuple
/// twice, minus one entry: `_is_prose_line` also rejects `-->`, and
/// `_is_container_structural_break` does not.
const STRUCTURAL_PREFIXES: [&str; 10] = ["#", "<", ">", ":", "!!!", "???", "{%", "{{", "%}", "}}"];

/// `_is_container_structural_break`: content that must not unwrap as prose.
///
/// Asked of what is left after a blockquote marker or a list marker comes off.
/// The fence test matters here and not in the main loop: a list marker pushes
/// content past column 3, where the loop's own fence matcher stops looking.
#[must_use]
pub fn is_container_structural_break(content: &str) -> bool {
    let stripped = py_trim(content);
    stripped.is_empty()
        || content.starts_with("    ")
        || content.starts_with('\t')
        || STRUCTURAL_PREFIXES
            .iter()
            .any(|prefix| stripped.starts_with(prefix))
        || is_gfm_alert(stripped)
        || contains_unmasked_pipe(stripped)
        || is_list_line(stripped)
        || is_alpha_list_line(stripped)
        || is_setext_line(stripped)
        || is_thematic_break(stripped)
        || match_opening_fence(stripped).is_some()
        || is_whole_line_bold(stripped)
        || is_link_reference(stripped)
}

/// `_is_prose_line`: a top-level line eligible to be joined with its neighbors.
///
/// Not the negation of the predicate above. This one rejects any leading
/// whitespace and any hard break, ignores fences and alerts and bold labels —
/// the main loop reaches those first — and carries one extra prefix, `-->`.
#[must_use]
pub fn is_prose_line(body: &str) -> bool {
    let stripped = py_trim(body);
    !(stripped.is_empty()
        || body != py_trim_start(body)
        || has_hard_break(body)
        || stripped.starts_with("-->")
        || STRUCTURAL_PREFIXES
            .iter()
            .any(|prefix| stripped.starts_with(prefix))
        || contains_unmasked_pipe(stripped)
        || is_list_line(stripped)
        || is_alpha_list_line(stripped)
        || is_setext_line(stripped)
        || is_thematic_break(stripped)
        || is_link_reference(stripped))
}

/// Which container a buffered paragraph belongs to.
///
/// Spelled out rather than left as a string, for the reason the Python spells it
/// out with a `Literal`: these three are the whole domain, and a typo would be
/// silent — the branch that reads it never fires, and the symptom is a paragraph
/// that quietly stops unwrapping.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Kind {
    Top,
    Blockquote,
    ListItem,
}

/// An in-progress paragraph buffer for top-level, blockquote or list-item prose.
struct Paragraph<'a> {
    kind: Kind,
    first_line: &'a str,
    first_prefix: &'a str,
    first_content: &'a str,
    last_eol: &'a str,
    content_col: usize,
    /// `(raw_line, post_prefix_content)`. The raw is needed because the
    /// label-row branch emits lines verbatim rather than joining their content.
    extras: Vec<(&'a str, &'a str)>,
}

/// Everything the loop carries from one line to the next.
///
/// `Option<(char, usize)>` collapses Python's `in_fence` / `fence_char` /
/// `fence_len` triple into one value that cannot be half-set, and the same for
/// the blockquote-scoped copy of it.
struct Unwrapper<'a> {
    output: String,
    paragraph: Option<Paragraph<'a>>,
    paragraphs_unwrapped: usize,
    line_breaks_removed: usize,
    html_literal_terminator: Option<&'static str>,
    html_block_tag: Option<String>,
    fence: Option<(char, usize)>,
    bq_html_literal_terminator: Option<&'static str>,
    bq_html_block_tag: Option<String>,
    bq_fence: Option<(char, usize)>,
}

/// Return Markdown with soft wraps in paragraph contexts joined.
#[must_use]
pub fn unwrap_markdown_prose(text: &str) -> UnwrapResult {
    let lines = py_splitlines_keepends(text);
    let bodies: Vec<&str> = lines.iter().map(|line| split_eol(line).0).collect();
    // Measured up front because a badge block is structural only as a *run*, and
    // the loop below sees one line at a time.
    let link_block = link_block_indexes(&bodies);
    let mut in_front_matter = starts_front_matter(&lines);
    let mut state = Unwrapper {
        output: String::with_capacity(text.len()),
        paragraph: None,
        paragraphs_unwrapped: 0,
        line_breaks_removed: 0,
        html_literal_terminator: None,
        html_block_tag: None,
        fence: None,
        bq_html_literal_terminator: None,
        bq_html_block_tag: None,
        bq_fence: None,
    };

    for (index, line) in lines.iter().enumerate() {
        let body = bodies[index];
        let eol = split_eol(line).1;

        // 1 and 2. Front matter passes through whole. The first line cannot
        // close it, or a document opening `---` would leave immediately.
        if in_front_matter {
            state.flush();
            state.output.push_str(line);
            if index > 0 && matches!(body, "---" | "...") {
                in_front_matter = false;
            }
            continue;
        }

        // 3. A raw HTML literal — comment, PI, CDATA, declaration.
        if let Some(terminator) = state.html_literal_terminator {
            state.flush();
            state.output.push_str(line);
            if body.contains(terminator) {
                state.html_literal_terminator = None;
            }
            continue;
        }

        // 4. An HTML block, which a blank line closes unless its tag holds
        // literal text. This branch runs before the blank-line branch below for
        // exactly that reason; reorder them and `<div>` blocks never close.
        if let Some(tag) = state.html_block_tag.take() {
            state.flush();
            state.output.push_str(line);
            let closed = body.to_lowercase().contains(&format!("</{tag}>"))
                || (!is_raw_html_tag(&tag) && py_trim(body).is_empty());
            if !closed {
                state.html_block_tag = Some(tag);
            }
            continue;
        }

        // 5. A fenced code block.
        if let Some((fence_char, fence_len)) = state.fence {
            state.flush();
            state.output.push_str(line);
            if is_closing_fence(body, fence_char, fence_len) {
                state.fence = None;
            }
            continue;
        }

        // 6. Container-scoped state armed by an opener inside a blockquote.
        // While armed, every quoted body line passes through raw so multi-line
        // code and HTML survive intact. A line without the marker means the
        // blockquote ended without a closer, so the state drops and the line is
        // reprocessed — the one branch that does not `continue`.
        if state.bq_fence.is_some()
            || state.bq_html_literal_terminator.is_some()
            || state.bq_html_block_tag.is_some()
        {
            if let Some((_, rest)) = match_blockquote(body) {
                state.output.push_str(line);
                state.close_blockquote_state(rest);
                continue;
            }
            state.bq_fence = None;
            state.bq_html_literal_terminator = None;
            state.bq_html_block_tag = None;
        }

        // 7. A blank line ends whatever was open.
        if py_trim(body).is_empty() {
            state.flush();
            state.output.push_str(line);
            continue;
        }

        // 8. A line inside a run of link-only lines is structure, so it neither
        // joins its neighbors nor absorbs the prose either side of it. The
        // guards above run first, which keeps a badge-shaped line inside a
        // fence, front matter or an HTML block on its existing path.
        if link_block[index] {
            state.flush();
            state.output.push_str(line);
            continue;
        }

        // 9. A fence opener.
        if let Some(opening) = match_opening_fence(body) {
            state.flush();
            state.fence = Some(opening);
            state.output.push_str(line);
            continue;
        }

        // 10. Hard-break-terminated lines and whole-line-bold labels both carry
        // visual intent that joining would destroy.
        if has_hard_break(body) || is_whole_line_bold(body) {
            state.flush();
            state.emit_pass_through(line, body);
            continue;
        }

        // 11. A blockquote.
        if let Some((prefix, rest)) = match_blockquote(body) {
            if is_container_structural_break(rest) {
                state.flush();
                state.output.push_str(line);
                // Arm container-scoped state when the break opens a fence or an
                // HTML block. Without this the `> ...` lines below it fold back
                // into a new blockquote paragraph and are joined.
                state.arm_blockquote_state(rest);
                continue;
            }
            // A speaker prefix opens a row of its own rather than continuing the
            // quoted paragraph above it.
            match &mut state.paragraph {
                Some(paragraph)
                    if paragraph.kind == Kind::Blockquote && !is_speaker_prefix(rest) =>
                {
                    paragraph.extras.push((line, rest));
                    paragraph.last_eol = eol;
                }
                _ => {
                    state.flush();
                    state.paragraph = Some(Paragraph {
                        kind: Kind::Blockquote,
                        first_line: line,
                        first_prefix: prefix,
                        first_content: rest,
                        last_eol: eol,
                        content_col: 0,
                        extras: Vec::new(),
                    });
                }
            }
            continue;
        }

        // 12. A list marker. This flushes unconditionally where branch 11 does
        // not, and symmetrizing the two changes behavior.
        if let Some((prefix, content_col, rest)) = match_list_marker(body) {
            state.flush();
            if is_container_structural_break(rest) {
                state.output.push_str(line);
                continue;
            }
            state.paragraph = Some(Paragraph {
                kind: Kind::ListItem,
                first_line: line,
                first_prefix: prefix,
                first_content: rest,
                last_eol: eol,
                content_col,
                extras: Vec::new(),
            });
            continue;
        }

        // 13. Ordinary top-level prose.
        if is_prose_line(body) {
            match &mut state.paragraph {
                Some(paragraph) if !is_speaker_prefix(body) => {
                    paragraph.extras.push((line, body));
                    paragraph.last_eol = eol;
                }
                _ => {
                    state.flush();
                    state.paragraph = Some(Paragraph {
                        kind: Kind::Top,
                        first_line: line,
                        first_prefix: "",
                        first_content: body,
                        last_eol: eol,
                        content_col: 0,
                        extras: Vec::new(),
                    });
                }
            }
            continue;
        }

        // 14. A line indented to a list item's content column continues it.
        if let Some(paragraph) = &mut state.paragraph {
            if paragraph.kind == Kind::ListItem {
                // ASCII spaces only, not any whitespace, and the same number of
                // bytes as characters on both sides of the comparison.
                let indent = body.len() - body.trim_start_matches(' ').len();
                if indent >= paragraph.content_col {
                    let inner = &body[indent..];
                    if !is_container_structural_break(inner) {
                        paragraph.extras.push((line, inner));
                        paragraph.last_eol = eol;
                        continue;
                    }
                }
            }
        }

        state.flush();
        state.emit_pass_through(line, body);
    }

    state.flush();
    UnwrapResult {
        content: state.output,
        paragraphs_unwrapped: state.paragraphs_unwrapped,
        line_breaks_removed: state.line_breaks_removed,
    }
}

impl<'a> Unwrapper<'a> {
    /// Emit the buffered paragraph, joining a multi-line buffer into one line.
    fn flush(&mut self) {
        let Some(paragraph) = self.paragraph.take() else {
            return;
        };
        if paragraph.extras.is_empty() {
            self.output.push_str(paragraph.first_line);
            return;
        }
        if is_label_line(paragraph.first_content) {
            self.flush_label_rows(&paragraph);
            return;
        }
        self.output.push_str(paragraph.first_prefix);
        self.output.push_str(py_trim(paragraph.first_content));
        for (_, content) in &paragraph.extras {
            let tail = py_trim(content);
            if !tail.is_empty() {
                self.output.push(' ');
                self.output.push_str(tail);
            }
        }
        self.output.push_str(paragraph.last_eol);
        self.paragraphs_unwrapped += 1;
        self.line_breaks_removed += paragraph.extras.len();
    }

    /// Emit a label-shaped paragraph as rows, joining only wrapped tails.
    ///
    /// Each line matching a label shape opens a row; a line carrying no label is
    /// the soft-wrapped tail of the row above and joins it. Requiring *every*
    /// line to be a label instead collapsed the whole block as soon as one value
    /// wrapped, which is the common shape for the last field.
    fn flush_label_rows(&mut self, paragraph: &Paragraph<'a>) {
        let mut rows: Vec<Vec<(&str, &str)>> =
            vec![vec![(paragraph.first_line, paragraph.first_content)]];
        for (raw, content) in &paragraph.extras {
            if is_label_line(content) {
                rows.push(vec![(raw, content)]);
            } else {
                rows.last_mut()
                    .expect("rows opens with one row")
                    .push((raw, content));
            }
        }
        let mut joined_any = false;
        for row in &rows {
            let (head_raw, _) = row[0];
            if row.len() == 1 {
                self.output.push_str(head_raw);
                continue;
            }
            // Joined onto the head's raw line, so its prefix — blockquote
            // marker, list indent — carries over without being rebuilt, which
            // keeps every container shape working the same way.
            self.output.push_str(py_trim_end(split_eol(head_raw).0));
            for (_, content) in &row[1..] {
                let tail = py_trim(content);
                if !tail.is_empty() {
                    self.output.push(' ');
                    self.output.push_str(tail);
                }
            }
            self.output.push_str(split_eol(row[row.len() - 1].0).1);
            self.line_breaks_removed += row.len() - 1;
            joined_any = true;
        }
        if joined_any {
            self.paragraphs_unwrapped += 1;
        }
    }

    /// Emit `raw` unchanged and arm any HTML literal or block state it opens.
    fn emit_pass_through(&mut self, raw: &str, body: &str) {
        self.output.push_str(raw);
        if let Some(terminator) = match_opening_html_literal_terminator(body) {
            self.html_literal_terminator = Some(terminator);
            return;
        }
        if let Some(tag) = match_opening_html_block(body) {
            self.html_block_tag = Some(tag);
        }
    }

    /// Arm blockquote-scoped state for a structural break inside a quote.
    fn arm_blockquote_state(&mut self, rest: &str) {
        if let Some(terminator) = match_opening_html_literal_terminator(rest) {
            self.bq_html_literal_terminator = Some(terminator);
        } else if let Some(opening) = match_opening_fence(rest) {
            self.bq_fence = Some(opening);
        } else if let Some(tag) = match_opening_html_block(rest) {
            self.bq_html_block_tag = Some(tag);
        }
    }

    /// Clear whichever blockquote-scoped state `rest` closes, at most one.
    fn close_blockquote_state(&mut self, rest: &str) {
        if let Some(terminator) = self.bq_html_literal_terminator {
            if rest.contains(terminator) {
                self.bq_html_literal_terminator = None;
            }
            return;
        }
        if let Some((fence_char, fence_len)) = self.bq_fence {
            if is_closing_fence(rest, fence_char, fence_len) {
                self.bq_fence = None;
            }
            return;
        }
        if let Some(tag) = self.bq_html_block_tag.take() {
            let closed = rest.to_lowercase().contains(&format!("</{tag}>"))
                || (!is_raw_html_tag(&tag) && py_trim(rest).is_empty());
            if !closed {
                self.bq_html_block_tag = Some(tag);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn content(text: &str) -> String {
        unwrap_markdown_prose(text).content
    }

    #[test]
    fn a_soft_wrapped_paragraph_joins_into_one_line() {
        let result = unwrap_markdown_prose("one\ntwo\nthree\n");
        assert_eq!(result.content, "one two three\n");
        assert_eq!(result.paragraphs_unwrapped, 1);
        assert_eq!(result.line_breaks_removed, 2);
    }

    #[test]
    fn a_blank_line_separates_paragraphs() {
        let result = unwrap_markdown_prose("one\ntwo\n\nthree\nfour\n");
        assert_eq!(result.content, "one two\n\nthree four\n");
        assert_eq!(result.paragraphs_unwrapped, 2);
        assert_eq!(result.line_breaks_removed, 2);
    }

    #[test]
    fn a_single_line_paragraph_is_emitted_verbatim() {
        let result = unwrap_markdown_prose("just one line\n");
        assert_eq!(result.content, "just one line\n");
        assert_eq!(result.paragraphs_unwrapped, 0);
        assert_eq!(result.line_breaks_removed, 0);
    }

    #[test]
    fn line_endings_survive_the_join() {
        assert_eq!(content("one\r\ntwo\r\n"), "one two\r\n");
        assert_eq!(content("one\rtwo\r"), "one two\r");
        assert_eq!(content("one\ntwo"), "one two");
    }

    #[test]
    fn the_last_line_decides_the_terminator() {
        // `last_eol` is the buffer's, so a paragraph ending without one joins
        // to a line that ends without one.
        assert_eq!(content("one\ntwo\nthree"), "one two three");
    }

    #[test]
    fn a_fence_and_its_body_pass_through() {
        let text = "```\nnot\nprose\n```\n";
        assert_eq!(content(text), text);
    }

    #[test]
    fn an_html_block_closes_on_a_blank_line_when_its_tag_is_not_raw() {
        // Branch 4 running before branch 7 is what makes this true.
        let text = "<div>\na\nb\n\nc\nd\n";
        assert_eq!(content(text), "<div>\na\nb\n\nc d\n");
    }

    #[test]
    fn a_raw_tag_holds_its_blank_line() {
        let text = "<pre>\na\n\nb\n</pre>\n\nc\nd\n";
        assert_eq!(content(text), "<pre>\na\n\nb\n</pre>\n\nc d\n");
    }

    #[test]
    fn front_matter_passes_through_and_the_body_does_not() {
        let text = "---\ntitle: x\n---\n\none\ntwo\n";
        assert_eq!(content(text), "---\ntitle: x\n---\n\none two\n");
    }

    #[test]
    fn a_bare_thematic_break_is_not_front_matter() {
        // No closer below it, so the rest of the document still unwraps.
        assert_eq!(content("---\none\ntwo\n"), "---\none two\n");
    }

    #[test]
    fn a_quoted_paragraph_joins_and_keeps_one_marker() {
        let result = unwrap_markdown_prose("> one\n> two\n");
        assert_eq!(result.content, "> one two\n");
        assert_eq!(result.paragraphs_unwrapped, 1);
        assert_eq!(result.line_breaks_removed, 1);
    }

    #[test]
    fn a_list_item_absorbs_its_indented_continuation() {
        let result = unwrap_markdown_prose("- one\n  two\n");
        assert_eq!(result.content, "- one two\n");
        assert_eq!(result.line_breaks_removed, 1);
        // Short of the content column, so it is not a continuation.
        assert_eq!(content("12. one\n  two\n"), "12. one\n  two\n");
        assert_eq!(content("12. one\n    two\n"), "12. one two\n");
    }

    #[test]
    fn a_table_is_never_joined() {
        let text = "| a | b |\n| - | - |\n";
        assert_eq!(content(text), text);
        // A pipe inside a code span is literal text, so this one does join.
        assert_eq!(content("a `x | y`\nb\n"), "a `x | y` b\n");
    }

    #[test]
    fn label_rows_keep_their_layout_but_wrapped_tails_still_join() {
        let result = unwrap_markdown_prose("**A:** one\n**B:** two\n");
        assert_eq!(result.content, "**A:** one\n**B:** two\n");
        assert_eq!(result.paragraphs_unwrapped, 0);
        assert_eq!(result.line_breaks_removed, 0);

        let result = unwrap_markdown_prose("**A:** one\n**B:** two\nwrapped\n");
        assert_eq!(result.content, "**A:** one\n**B:** two wrapped\n");
        assert_eq!(result.paragraphs_unwrapped, 1);
        assert_eq!(result.line_breaks_removed, 1);
    }

    #[test]
    fn a_speaker_prefix_opens_a_paragraph_of_its_own() {
        let text = "Alex: one\nJordan: two\n";
        assert_eq!(content(text), text);
    }

    #[test]
    fn a_hard_break_is_preserved() {
        let text = "one  \ntwo\n";
        assert_eq!(content(text), text);
        assert_eq!(content("one\\\ntwo\n"), "one\\\ntwo\n");
    }

    #[test]
    fn a_badge_run_stays_on_its_own_lines() {
        let text = "[a](x)\n[b](y)\n[c](z)\n";
        assert_eq!(content(text), text);
        // One link-only line is a wrap point rather than a block.
        assert_eq!(content("prose\n[a](x)\n"), "prose [a](x)\n");
    }

    #[test]
    fn a_quoted_fence_survives_its_container() {
        let text = "> ```\n> a\n>\n> b\n> ```\n";
        assert_eq!(content(text), text);
    }

    #[test]
    fn the_empty_document_is_left_alone() {
        let result = unwrap_markdown_prose("");
        assert_eq!(result.content, "");
        assert_eq!(result.paragraphs_unwrapped, 0);
        assert_eq!(result.line_breaks_removed, 0);
    }

    #[test]
    fn the_two_predicates_are_not_each_others_negation() {
        // Leading whitespace disqualifies prose and does not, on its own, make
        // a container break.
        assert!(!is_prose_line("  indented"));
        assert!(!is_container_structural_break("  indented"));
        // A closing comment marker is prose to one and not to the other.
        assert!(!is_prose_line("--> x"));
        assert!(!is_container_structural_break("--> x"));
    }
}
