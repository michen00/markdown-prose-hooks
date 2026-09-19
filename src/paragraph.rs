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
    COMMENT_CLOSE, COMMENT_OPEN, IGNORE_BLOCK_END, IGNORE_BLOCK_START, IGNORE_DIRECTIVE,
    has_hard_break, is_alpha_list_line, is_closing_fence, is_gfm_alert, is_ignore_block_end,
    is_ignore_block_start, is_ignore_directive, is_link_reference, is_list_line, is_raw_html_tag,
    is_setext_line, is_thematic_break, match_blockquote, match_list_marker, match_opening_fence,
    match_opening_html_block, match_opening_html_literal_terminator, py_splitlines_keepends,
    py_trim, py_trim_end, py_trim_start, split_blockquote_stack, split_eol, starts_front_matter,
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
    /// Set from the directive armed when this paragraph opened, rather than read
    /// at flush time: the directive is spent by the line that opens the
    /// paragraph, so by the time the paragraph ends the flag is already gone.
    exempt: bool,
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
    /// How many blockquote levels the line that armed `bq_fence` or
    /// `bq_html_block_tag` carried. One field for both, because the arming
    /// branch is an either/or and only one of them is ever live. It means
    /// nothing while neither is armed and is left where it was rather than
    /// cleared, since a second place to clear it is a second place to forget.
    bq_depth: usize,
    directive_armed: bool,
    /// The opening marker's 1-based line while a region is open, 0 otherwise. A
    /// line number rather than a flag so an unclosed region can be reported
    /// against the marker that opened it.
    ignore_block_line: usize,
    /// The inner content of a comment that opened on an earlier line, one entry
    /// per line it has covered so far, or `None` when no comment is open or the
    /// open literal is not one. A directive written across lines cannot be acted
    /// on until the comment closes, because until then its content is not known,
    /// so the content is carried here and read at the closing line.
    comment_parts: Option<Vec<&'a str>>,
    /// The 1-based line the open comment began on, so a region a multi-line
    /// marker opens is reported against the marker's first line rather than its
    /// last — the whole comment is the marker.
    comment_line: usize,
    /// How many blockquote levels the line the open comment began on carried.
    /// Every later line of that comment has to carry the same number, or the
    /// comment is no marker: see `continue_comment_run`.
    comment_depth: usize,
}

/// Return Markdown with soft wraps in paragraph contexts joined.
// Suppressed on this function alone, matching the Python side, which carries
// the same suppression for the same reason: the branches here are the
// contexts the corpus pins, and splitting them to satisfy a line count would
// spread that behavior across call sites without clarifying any of it.
#[allow(clippy::too_many_lines)]
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
        bq_depth: 0,
        directive_armed: false,
        ignore_block_line: 0,
        comment_parts: None,
        comment_line: 0,
        comment_depth: 0,
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
                // Read here rather than at the opening line, because a
                // comment's content is only known once it closes. This is
                // where a multi-line directive is armed and where a multi-line
                // closing marker ends a region.
                state.close_comment_run(body);
            } else {
                state.continue_comment_run(body);
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
        // code and HTML survive intact. A line carrying no marker, or fewer of
        // them than the container was armed at, means that quote ended without
        // a closer, so the state drops and the line is reprocessed — the one
        // branch that does not `continue`.
        if state.bq_fence.is_some()
            || state.bq_html_literal_terminator.is_some()
            || state.bq_html_block_tag.is_some()
        {
            // A line quoted less deeply than the container was armed at is
            // no line of it: the quote the container lives in ended there,
            // exactly as it ends at a line carrying no marker at all, so
            // both drop the state and reprocess the line. Closing at the
            // container's own depth without dropping at it too left those
            // two meaning different things, and only the shallower one lost
            // anything — a live marker under such a line was read as code
            // and the break its author had marked was joined away. A line
            // quoted more deeply is content rather than a boundary, which is
            // why this is `<` and not `!=`: inside a fence every line is
            // literal, and CommonMark reads the deeper line the same way.
            // The comment run is the exception the closing tests already
            // make, for the same reason — where a comment ends is fixed by
            // its delimiter rather than by quoting.
            if match_blockquote(body).is_some()
                && (state.bq_html_literal_terminator.is_some()
                    || split_blockquote_stack(body).0 >= state.bq_depth)
            {
                state.output.push_str(line);
                state.close_blockquote_state(body);
                continue;
            }
            state.bq_fence = None;
            state.bq_html_literal_terminator = None;
            state.bq_html_block_tag = None;
            // The quote ended before the comment did, so the comment never
            // closes and what it had accumulated is not a marker of any kind.
            state.comment_parts = None;
        }

        // 7. Inside an exempt region every line goes back as the bytes it
        // arrived as, so nothing buffers and nothing counts. No `flush()` here:
        // the opening marker flushed, and no branch below this one runs while
        // the region is open.
        if state.ignore_block_line != 0 {
            if is_ignore_block_end(body) {
                state.output.push_str(line);
                state.ignore_block_line = 0;
                continue;
            }
            // A fence opened inside a region is still tracked, and that is the
            // whole of why a closing marker quoted inside one does not close the
            // region: the guards above consume those lines before this branch
            // sees them. Without this the three inert contexts would hold for
            // the line form and not for the region form.
            if let Some(opening) = match_opening_fence(body) {
                state.fence = Some(opening);
                state.output.push_str(line);
                continue;
            }
            // And a quoted one, or the rule would read "inert inside a fence,
            // unless the fence is inside a blockquote". The closing marker is
            // tested above this, so `> <!-- unwrap-ignore-end -->` still closes
            // the region -- what this guards is a marker quoted inside a
            // container opened within one.
            if let Some((_, rest)) = match_blockquote(body) {
                if is_container_structural_break(rest) {
                    state.arm_blockquote_state(body, index);
                    state.output.push_str(line);
                    continue;
                }
            }
            state.emit_pass_through(line, body, index);
            continue;
        }

        // 8. The marker that opens one.
        if is_ignore_block_start(body) {
            state.flush();
            state.output.push_str(line);
            // A second opening marker inside a region never reaches here, so the
            // line recorded is the one that opened the region rather than the
            // last one seen -- a flag rather than a depth counter, which is what
            // every tool measured does.
            state.ignore_block_line = index + 1;
            // The marker is a non-blank line, so it spends an armed line-level
            // directive the way any other structural line does.
            state.directive_armed = false;
            continue;
        }

        // 9. The line-level ignore directive. All three markers are looked for
        // below the fence, front-matter and HTML guards on purpose, which is
        // what makes any of them inert inside any of those without a test of its
        // own for each combination.
        if is_ignore_directive(body) {
            state.flush();
            state.output.push_str(line);
            state.directive_armed = true;
            continue;
        }

        // 10. A blank line ends whatever was open.
        if py_trim(body).is_empty() {
            state.flush();
            state.output.push_str(line);
            continue;
        }

        // Any other non-blank line spends the directive, whether or not it
        // opens a paragraph. Taken once here rather than cleared in each
        // structural branch below: there are six of those and a seventh would
        // otherwise have to remember to do it. Spending it on a heading is
        // deliberate -- a directive that stayed armed would reach a paragraph
        // further down that nobody meant to exempt, and acting at a distance is
        // worse than doing nothing visibly.
        let armed = state.directive_armed;
        state.directive_armed = false;

        // 11. A line inside a run of link-only lines is structure, so it neither
        // joins its neighbors nor absorbs the prose either side of it. The
        // guards above run first, which keeps a badge-shaped line inside a
        // fence, front matter or an HTML block on its existing path.
        if link_block[index] {
            state.flush();
            state.output.push_str(line);
            continue;
        }

        // 12. A fence opener.
        if let Some(opening) = match_opening_fence(body) {
            state.flush();
            state.fence = Some(opening);
            state.output.push_str(line);
            continue;
        }

        // 13. Hard-break-terminated lines and whole-line-bold labels both carry
        // visual intent that joining would destroy.
        if has_hard_break(body) || is_whole_line_bold(body) {
            state.flush();
            state.emit_pass_through(line, body, index);
            continue;
        }

        // 14. A blockquote.
        if let Some((prefix, rest)) = match_blockquote(body) {
            if is_container_structural_break(rest) {
                state.flush();
                state.output.push_str(line);
                // Arm container-scoped state when the break opens a fence or an
                // HTML block. Without this the `> ...` lines below it fold back
                // into a new blockquote paragraph and are joined.
                state.arm_blockquote_state(body, index);
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
                        exempt: armed,
                        extras: Vec::new(),
                    });
                }
            }
            continue;
        }

        // 15. A list marker. This flushes unconditionally where branch 14 does
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
                exempt: armed,
                extras: Vec::new(),
            });
            continue;
        }

        // 16. Ordinary top-level prose.
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
                        exempt: armed,
                        extras: Vec::new(),
                    });
                }
            }
            continue;
        }

        // 17. A line indented to a list item's content column continues it.
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
        state.emit_pass_through(line, body, index);
    }

    state.flush();
    UnwrapResult {
        content: state.output,
        paragraphs_unwrapped: state.paragraphs_unwrapped,
        line_breaks_removed: state.line_breaks_removed,
        unclosed_ignore_start: (state.ignore_block_line != 0).then_some(state.ignore_block_line),
    }
}

impl<'a> Unwrapper<'a> {
    /// Emit the buffered paragraph, joining a multi-line buffer into one line.
    fn flush(&mut self) {
        let Some(paragraph) = self.paragraph.take() else {
            return;
        };
        // An exempt paragraph goes back exactly as it arrived, and neither
        // counter moves: a file whose only paragraph is exempt has to report as
        // unchanged, or `--fail-on-change` would fail on a document the author
        // already told the tool to leave alone.
        if paragraph.exempt {
            self.output.push_str(paragraph.first_line);
            for (raw, _) in &paragraph.extras {
                self.output.push_str(raw);
            }
            return;
        }
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
    ///
    /// `index` is the loop's, passed where the Python reads it from the
    /// enclosing scope: a comment opening here records the line it opened on.
    fn emit_pass_through(&mut self, raw: &str, body: &'a str, index: usize) {
        self.output.push_str(raw);
        if let Some(terminator) = match_opening_html_literal_terminator(body) {
            self.html_literal_terminator = Some(terminator);
            self.open_comment_run(body, terminator, index);
            return;
        }
        if let Some(tag) = match_opening_html_block(body) {
            self.html_block_tag = Some(tag);
        }
    }

    /// Begin accumulating the content of a comment opened on this line.
    ///
    /// `body` and `index` are the loop's, passed where the Python reads them
    /// from the enclosing scope: what is wanted is the whole line the comment
    /// opened on rather than whatever a container branch had already peeled
    /// off it.
    fn open_comment_run(&mut self, body: &'a str, terminator: &str, index: usize) {
        if terminator != COMMENT_CLOSE {
            // A processing instruction, CDATA section or declaration carries no
            // directive. Dropping the buffer rather than leaving it is what
            // stops a stale one being read when that literal closes.
            self.comment_parts = None;
            return;
        }
        let (depth, inner) = split_blockquote_stack(body);
        self.comment_depth = depth;
        let opened = py_trim_start(inner);
        self.comment_parts = Some(vec![opened.strip_prefix(COMMENT_OPEN).unwrap_or(opened)]);
        self.comment_line = index + 1;
    }

    /// Add this line to the open comment, or give up on it being a marker.
    fn continue_comment_run(&mut self, body: &'a str) {
        let Some(parts) = &mut self.comment_parts else {
            return;
        };
        let (depth, inner) = split_blockquote_stack(body);
        if depth != self.comment_depth {
            // The whole marker stack comes off every line, so a line carrying a
            // different one is not a line of this comment's content even though
            // the literal run goes on to the closing delimiter. Giving the
            // buffer up here is what keeps a whole-stack strip from reading a
            // comment whose depth changes part-way as the marker its lines
            // happen to spell between them; the run itself is untouched,
            // because where the comment ends is not a question about quoting.
            self.comment_parts = None;
            return;
        }
        parts.push(inner);
    }

    /// Act on a comment closing here whose whole content is a marker.
    fn close_comment_run(&mut self, body: &'a str) {
        let Some(mut parts) = self.comment_parts.take() else {
            return;
        };
        let (depth, inner) = split_blockquote_stack(body);
        if depth != self.comment_depth {
            return;
        }
        let Some(inner) = py_trim(inner).strip_suffix(COMMENT_CLOSE) else {
            // The literal run ends here, but the comment is not the whole of
            // what this line says. The one-line form rejects a trailing tail
            // the same way, and nothing else would tell the marker from a
            // sentence that happens to close a comment partway along.
            return;
        };
        parts.push(inner);
        // Joined on the newlines that separated the lines and trimmed once, so
        // a marker alone on its own line reads as the marker however many blank
        // lines surround it, while two fragments that spell one only when run
        // together do not.
        let joined = parts.join("\n");
        let marker = py_trim(&joined);
        if self.ignore_block_line != 0 {
            // Inside a region only the closing marker means anything, exactly
            // as the one-line form does there.
            if marker == IGNORE_BLOCK_END {
                self.ignore_block_line = 0;
            }
            return;
        }
        if marker == IGNORE_BLOCK_START {
            self.ignore_block_line = self.comment_line;
        } else if marker == IGNORE_DIRECTIVE {
            self.directive_armed = true;
        }
    }

    /// Arm blockquote-scoped state for a structural break inside a quote.
    ///
    /// The whole marker stack comes off before any of these tests, where the
    /// branch that calls this has peeled exactly one level. Under that one
    /// peel a fence opener two levels down still began with `>` and matched
    /// nothing here, so no fence was tracked and a marker inside quoted code
    /// was read as an instruction — the container whose guard makes markers
    /// inert was never armed, and a document printing an example one level
    /// further in was governed by the example. `body` and `index` are the
    /// loop's, passed where the Python reads them from the enclosing scope:
    /// what is wanted is the whole line the container opened on rather than
    /// whatever the calling branch had already peeled off it.
    fn arm_blockquote_state(&mut self, body: &'a str, index: usize) {
        let (depth, inner) = split_blockquote_stack(body);
        if let Some(terminator) = match_opening_html_literal_terminator(inner) {
            self.bq_html_literal_terminator = Some(terminator);
            self.open_comment_run(body, terminator, index);
        } else if let Some(opening) = match_opening_fence(inner) {
            self.bq_fence = Some(opening);
            self.bq_depth = depth;
        } else if let Some(tag) = match_opening_html_block(inner) {
            self.bq_html_block_tag = Some(tag);
            self.bq_depth = depth;
        }
    }

    /// Clear whichever blockquote-scoped state `body` closes, at most one.
    ///
    /// Read with the whole stack off, the way it was armed, and at the depth it
    /// was armed at: a line quoted to some other depth is not a line of that
    /// container. Inside a fence every line is literal, so a closing fence one
    /// level deeper is the text it spells rather than a closer, and an HTML
    /// block reads its own terminator the same way. The comment run is the
    /// exception on purpose — where a comment ends is fixed by its delimiter
    /// rather than by quoting, which is what
    /// `a-shallower-line-inside-a-twice-quoted-comment-is-not-joined` pins —
    /// and the depth a marker needs is checked against the comment's own, in
    /// `close_comment_run`.
    fn close_blockquote_state(&mut self, body: &'a str) {
        let (depth, inner) = split_blockquote_stack(body);
        if let Some(terminator) = self.bq_html_literal_terminator {
            if inner.contains(terminator) {
                self.bq_html_literal_terminator = None;
                self.close_comment_run(body);
            } else {
                self.continue_comment_run(body);
            }
            return;
        }
        if let Some((fence_char, fence_len)) = self.bq_fence {
            if depth == self.bq_depth && is_closing_fence(inner, fence_char, fence_len) {
                self.bq_fence = None;
            }
            return;
        }
        if let Some(tag) = self.bq_html_block_tag.take() {
            let closed = depth == self.bq_depth
                && (inner.to_lowercase().contains(&format!("</{tag}>"))
                    || (!is_raw_html_tag(&tag) && py_trim(inner).is_empty()));
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
