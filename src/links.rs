//! Badge blocks: runs of lines that are nothing but links.
//!
//! A badge block is a list that happens not to use list markers. Joining one
//! turns "add one badge" into a whole-line diff, which is the opposite of what
//! unwrapping is for, so a *run* of link-only lines is structure and a single
//! one is not.
//!
//! The patterns here are `_LINK_TOKEN` and `_MATCH_LINK_ONLY_LINE`, and they are
//! ported as a hand walk rather than a regex. That is exact rather than
//! approximate: at every point one of these patterns can branch, the branches
//! begin with different characters, so the engine never has a second reading to
//! backtrack into. The walk therefore answers what the regex answers, and the
//! comments below say where each branch is decided.
//!
//! Every expected value in the tests below came from running the Python.

use crate::scan::{is_python_space, match_blockquote_prefix};

/// `_LINK_BLOCK_FLOOR`: how many link-only lines in a row make a block.
///
/// Two, because one link-only line is more often a wrap point inside a
/// paragraph than a block of its own, and one standing between blank lines is
/// already emitted verbatim as a single-line paragraph.
pub const LINK_BLOCK_FLOOR: usize = 2;

/// `_MATCH_LINK_ONLY_LINE`: `^\s*TOKEN(?:\s+TOKEN)*\s*$`.
///
/// Takes the line with any blockquote markers already removed;
/// [`is_link_only_line`] is the one that removes them.
#[must_use]
pub fn matches_link_only_line(text: &str) -> bool {
    let bytes = text.as_bytes();
    // No `\s*` here can usefully give anything back: a token opens with `!` or
    // `[`, and neither is whitespace, so the maximal run is the only run worth
    // trying at every one of the three places this pattern spells one.
    let Some(mut at) = match_link_token(bytes, skip_whitespace(text, 0)) else {
        return false;
    };
    loop {
        let separated = skip_whitespace(text, at);
        // `\s+`, so a token butted straight against the last one does not
        // continue the line -- and cannot be reached by the trailing `\s*$`
        // either, which is why `[a](x)[b](y)` is not a link-only line.
        if separated == at {
            break;
        }
        match match_link_token(bytes, separated) {
            Some(end) => at = end,
            None => break,
        }
    }
    skip_whitespace(text, at) == text.len()
}

/// `_is_link_only_line`: the same question, asked of a line that may be quoted.
///
/// Every blockquote level comes off first, so a quoted badge block is recognized
/// the way a bare one is, and a line quoted deeper than its neighbors does not
/// split the run they share. A line carrying no marker answers on its own text,
/// since it may be a lazy continuation of a quoted paragraph.
///
/// What the markers leave behind is read the way the container logic reads it:
/// four spaces or a tab past a marker is indented code, and a lone link inside
/// that is not a badge. The test applies only once a marker has come off,
/// because the same indentation with no marker in front of it may be a list
/// item's content column -- and holding a badge run together underneath a list
/// item is the whole point.
#[must_use]
pub fn is_link_only_line(body: &str) -> bool {
    let rest = match match_blockquote_prefix(body) {
        Some(end) => {
            let rest = &body[end..];
            if rest.starts_with("    ") || rest.starts_with('\t') {
                return false;
            }
            rest
        }
        None => body,
    };
    matches_link_only_line(rest)
}

/// `_link_block_indexes`: which lines sit inside a run of link-only lines.
///
/// Returns a bitmap parallel to `bodies` rather than a set of indexes: the only
/// consumer asks about each line once, in order, so it cannot be queried with an
/// index it never had.
#[must_use]
pub fn link_block_indexes(bodies: &[&str]) -> Vec<bool> {
    let mut inside = vec![false; bodies.len()];
    let mut run_start = 0;
    let mut run_quoted = false;
    // One past the end is a sentinel that closes a run reaching the last line.
    // An empty body is never link-only, so it always closes.
    for index in 0..=bodies.len() {
        let body = bodies.get(index).copied().unwrap_or("");
        if !is_link_only_line(body) {
            close_run(&mut inside, run_start, index);
            run_start = index + 1;
            continue;
        }
        // A run may lose its markers partway through, because a marker-less line
        // reads as a lazy continuation of the quoted paragraph above it. It
        // cannot gain them: a quoted line arriving on top of an unquoted run is
        // a blockquote interrupting a paragraph, so the lines above it are
        // outside the quote and the run ends there.
        let quoted = match_blockquote_prefix(body).is_some();
        if index == run_start {
            run_quoted = quoted;
        } else if quoted && !run_quoted {
            close_run(&mut inside, run_start, index);
            run_start = index;
            run_quoted = true;
        }
    }
    inside
}

/// Mark the run ending just below `end`, when it is long enough to be a block.
fn close_run(inside: &mut [bool], start: usize, end: usize) {
    if end - start >= LINK_BLOCK_FLOOR {
        for flag in &mut inside[start..end] {
            *flag = true;
        }
    }
}

/// The offset past a `\s*` run beginning at `at`.
fn skip_whitespace(text: &str, at: usize) -> usize {
    let mut end = at;
    for c in text[at..].chars() {
        if !is_python_space(c) {
            break;
        }
        end += c.len_utf8();
    }
    end
}

/// `_LINK_TOKEN`: `!?TEXT(?:TARGET|\[[^\[\]]*\])`, one link or image.
///
/// `!?` is greedy, and dropping the `!` never rescues a failure: the text half
/// has to open on `[`, which the `!` is not.
fn match_link_token(bytes: &[u8], start: usize) -> Option<usize> {
    let mut at = start;
    if bytes.get(at) == Some(&b'!') {
        at += 1;
    }
    at = match_link_text(bytes, at)?;
    // A destination opens on `(` and a reference on `[`, so the alternation is
    // decided by one character and its order is not observable.
    match_link_target(bytes, at).or_else(|| match_flat_group(bytes, at, b'[', b']'))
}

/// `_LINK_TEXT`: `\[(?:[^\[\]]|\[[^\[\]]*\])*\]`, one level of nesting.
fn match_link_text(bytes: &[u8], start: usize) -> Option<usize> {
    match_nesting_group(bytes, start, b'[', b']')
}

/// `_LINK_TARGET`: `\((?:[^()]|\([^()]*\))*\)`, one level of nesting.
///
/// The nesting is what lets a destination carry a parenthesized tail such as
/// `/wiki/Ruby_(rock)`.
fn match_link_target(bytes: &[u8], start: usize) -> Option<usize> {
    match_nesting_group(bytes, start, b'(', b')')
}

/// A bracketed group admitting exactly one level of the same bracket inside it.
///
/// Byte scanning is exact here: the four delimiters are ASCII, so none of them
/// occurs inside a multi-byte sequence, and every offset returned lands on one
/// of them and is therefore a character boundary.
fn match_nesting_group(bytes: &[u8], start: usize, open: u8, close: u8) -> Option<usize> {
    if bytes.get(start) != Some(&open) {
        return None;
    }
    let mut at = start + 1;
    loop {
        match bytes.get(at) {
            None => return None,
            Some(b) if *b == close => return Some(at + 1),
            // An inner group that does not close is fatal rather than a retry:
            // ending the repetition early only puts the closer up against the
            // same `[` that just failed.
            Some(b) if *b == open => at = match_flat_group(bytes, at, open, close)?,
            Some(_) => at += 1,
        }
    }
}

/// A bracketed group holding no bracket of either kind, `\[[^\[\]]*\]`.
fn match_flat_group(bytes: &[u8], start: usize, open: u8, close: u8) -> Option<usize> {
    if bytes.get(start) != Some(&open) {
        return None;
    }
    let mut at = start + 1;
    loop {
        match bytes.get(at) {
            None => return None,
            Some(b) if *b == close => return Some(at + 1),
            Some(b) if *b == open => return None,
            Some(_) => at += 1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_link_token_admits_exactly_one_level_of_nesting() {
        assert!(matches_link_only_line("[![alt](src)][ref]"));
        assert!(matches_link_only_line("[a](/wiki/Ruby_(rock))"));
        assert!(matches_link_only_line("[a[b]](x)"));
        assert!(matches_link_only_line("[a](x(y)z)"));
        assert!(!matches_link_only_line("[a[b[c]]](x)"));
        assert!(!matches_link_only_line("[a](x))"));
    }

    #[test]
    fn a_link_only_line_is_links_and_whitespace_and_nothing_else() {
        assert!(matches_link_only_line("[a](x)"));
        assert!(matches_link_only_line("![a](x)"));
        assert!(matches_link_only_line("[a][b]"));
        assert!(matches_link_only_line("[a](x) [b](y)"));
        assert!(matches_link_only_line("  [a](x)"));
        assert!(matches_link_only_line("[a](x)  "));
        assert!(!matches_link_only_line("[a](x) text"));
        assert!(!matches_link_only_line("text [a](x)"));
        // A bare reference-less `[a]` is not a token: the tail is required.
        assert!(!matches_link_only_line("[a]"));
        assert!(!matches_link_only_line(""));
        assert!(!matches_link_only_line("   "));
    }

    #[test]
    fn tokens_have_to_be_separated_by_whitespace() {
        // `(?:\s+TOKEN)*` needs the whitespace, and the trailing `\s*$` cannot
        // pick up the second token either.
        assert!(!matches_link_only_line("[a](x)[b](y)"));
    }

    #[test]
    fn indented_code_under_a_quote_marker_is_not_a_badge() {
        assert!(!is_link_only_line(">     [a](x)"));
        assert!(!is_link_only_line(">\t[a](x)"));
        // No marker, so the same indentation may be a list content column.
        assert!(is_link_only_line("    [a](x)"));
        assert!(is_link_only_line("\t[a](x)"));
        assert!(is_link_only_line("> [a](x)"));
        assert!(is_link_only_line("> > [a](x)"));
        assert!(!is_link_only_line(">     text"));
    }

    #[test]
    fn a_run_needs_two_lines_to_be_structural() {
        assert_eq!(link_block_indexes(&["[a](x)", "text"]), [false, false]);
        assert_eq!(link_block_indexes(&["[a](x)"]), [false]);
        assert_eq!(link_block_indexes(&["[a](x)", "[b](y)"]), [true, true]);
        assert_eq!(
            link_block_indexes(&["text", "[a](x)", "[b](y)"]),
            [false, true, true]
        );
        // A blank line between them is two runs of one, not one run of two.
        assert_eq!(
            link_block_indexes(&["[a](x)", "", "[b](y)"]),
            [false, false, false]
        );
        assert!(link_block_indexes(&[]).is_empty());
    }

    #[test]
    fn a_quoted_line_on_top_of_an_unquoted_run_opens_a_new_run() {
        // Two runs of two here, not one run of four, and both clear the floor.
        assert_eq!(
            link_block_indexes(&["[a](x)", "[b](y)", "> [c](z)", "> [d](w)"]),
            [true, true, true, true]
        );
        // One run of one and another of one, so neither clears it.
        assert_eq!(link_block_indexes(&["[a](x)", "> [b](y)"]), [false, false]);
        // The other direction is a lazy continuation, so the run holds.
        assert_eq!(link_block_indexes(&["> [a](x)", "[b](y)"]), [true, true]);
    }
}
