//! Label rows: the shapes whose line breaks are layout rather than wrapping.
//!
//! GFM renders a softbreak inside a paragraph as `<br>`, so an author who put
//! `**Remove:** ...` and `**Add:** ...` on separate lines meant two rows, and
//! joining them destroys the thing the lines were for. Each function here ports
//! one compiled pattern from `src/markdown_prose_hooks/unwrap.py`.
//!
//! Two properties of the Python decide most of this module, and both are easy to
//! port wrongly. `[A-Z]` in a `str` pattern is the literal range `U+0041..=
//! U+005A` and not a Unicode property, so `Émile:` is not a speaker. And the
//! bold-colon and speaker patterns carry no `$`: they are **prefixes**, matched
//! against a row that has a value after the label, and porting them as
//! whole-line predicates breaks every real label row.
//!
//! Every expected value in the tests below came from running the Python.

use crate::scan::{is_python_space, py_trim_start};

/// `_MATCH_WHOLE_LINE_BOLD`: `^\s*\*\*[^*]+\*\*\s*$`.
///
/// The only one of the four that tolerates leading whitespace.
#[must_use]
pub fn is_whole_line_bold(body: &str) -> bool {
    let Some(rest) = py_trim_start(body).strip_prefix("**") else {
        return false;
    };
    let label = up_to_first_star(rest);
    // `[^*]+` needs at least one character, so `****` is not a bold label.
    if label.is_empty() {
        return false;
    }
    let Some(tail) = rest[label.len()..].strip_prefix("**") else {
        return false;
    };
    // Giving characters back from `[^*]+` only ever exposes another non-`*`
    // character, which the `\*\*` after it cannot match, so the greedy reading
    // is the only one and a third `*` here is a failure rather than a retry.
    tail.chars().all(is_python_space)
}

/// `_MATCH_BOLD_COLON_PREFIX`: `^\*\*[^*]+(?::\*\*|\*\*:)`.
///
/// Both spellings of a bold key/value row — `**Label:** value` with the colon
/// inside the bold, and `**Label**: value` with it just outside.
#[must_use]
pub fn is_bold_colon_prefix(body: &str) -> bool {
    let Some(rest) = body.strip_prefix("**") else {
        return false;
    };
    // `[^*]+` is greedy, but here it genuinely backtracks: `**Remove:** x` only
    // matches once the run gives back its trailing colon so `:**` can have it.
    // Walking the run's split points forward asks the same question the engine
    // asks walking them backward, because only existence is wanted.
    let mut at = 0;
    for c in rest.chars() {
        if c == '*' {
            break;
        }
        at += c.len_utf8();
        let tail = &rest[at..];
        if tail.starts_with(":**") || tail.starts_with("**:") {
            return true;
        }
    }
    false
}

/// `_MATCH_SPEAKER_PREFIX`: `^[A-Z][a-zA-Z0-9_.-]*(?: [A-Z][a-zA-Z0-9_.-]*){0,3}:\s`.
///
/// One to four space-separated capitalized words, then a colon and one
/// whitespace character. The `{0,3}` counts whole words, not characters, so
/// nothing in this module counts characters at all.
#[must_use]
pub fn is_speaker_prefix(body: &str) -> bool {
    let bytes = body.as_bytes();
    let Some(first) = match_first_word(bytes) else {
        return false;
    };
    let mut at = first;
    let mut extra_words = 0;
    loop {
        if colon_then_whitespace(body, at) {
            return true;
        }
        if extra_words == 3 {
            return false;
        }
        // A word's own character run can never help by giving anything back:
        // neither the space that opens the next word nor the colon that ends the
        // pattern is in `[a-zA-Z0-9_.-]`, so each word ends in exactly one place.
        let Some(next) = match_extra_word(bytes, at) else {
            return false;
        };
        at = next;
        extra_words += 1;
    }
}

/// `_MATCH_BRACKETED_LINE`: `^\[[^\[\]]*\]\.?\s*$`.
#[must_use]
pub fn is_bracketed_line(body: &str) -> bool {
    let Some(rest) = body.strip_prefix('[') else {
        return false;
    };
    // `[^\[\]]*` crosses neither bracket, so it always ends at the first one and
    // that one has to be the closer.
    let Some(end) = rest.find(['[', ']']) else {
        return false;
    };
    if rest.as_bytes()[end] != b']' {
        return false;
    }
    let tail = &rest[end + 1..];
    // `\.?` is optional, so a tail that is all whitespace already matches;
    // stripping a leading dot that is not there leaves the tail alone, which
    // asks both readings in one test.
    tail.strip_prefix('.')
        .unwrap_or(tail)
        .chars()
        .all(is_python_space)
}

/// `_is_label_line`: any of the four shapes, after leading whitespace comes off.
///
/// Three of the four reject leading whitespace on their own. Stripping it here
/// papers over that at this one call site and nowhere else, which is why
/// `is_whole_line_bold` still strips for itself.
#[must_use]
pub fn is_label_line(content: &str) -> bool {
    let stripped = py_trim_start(content);
    is_bold_colon_prefix(stripped)
        || is_speaker_prefix(stripped)
        || is_bracketed_line(stripped)
        || is_whole_line_bold(stripped)
}

/// The leading run of characters that are not `*`.
///
/// Scanning bytes would give the same answer — `*` is ASCII, so it never occurs
/// inside a multi-byte sequence — but the offsets are used to slice, and a
/// character walk cannot land inside one.
fn up_to_first_star(s: &str) -> &str {
    match s.find('*') {
        Some(end) => &s[..end],
        None => s,
    }
}

/// `[a-zA-Z0-9_.-]`, the class both speaker words are spelled with.
fn is_speaker_word_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-')
}

/// `[A-Z][a-zA-Z0-9_.-]*` at offset zero.
fn match_first_word(bytes: &[u8]) -> Option<usize> {
    if !bytes.first()?.is_ascii_uppercase() {
        return None;
    }
    Some(word_end(bytes, 1))
}

/// ` [A-Z][a-zA-Z0-9_.-]*` at `at`, one repetition of the group.
fn match_extra_word(bytes: &[u8], at: usize) -> Option<usize> {
    if bytes.get(at) != Some(&b' ') || !bytes.get(at + 1)?.is_ascii_uppercase() {
        return None;
    }
    Some(word_end(bytes, at + 2))
}

/// The end of a `[a-zA-Z0-9_.-]*` run starting at `at`.
fn word_end(bytes: &[u8], at: usize) -> usize {
    let mut end = at;
    while bytes.get(end).is_some_and(|b| is_speaker_word_byte(*b)) {
        end += 1;
    }
    end
}

/// `:\s` at `at` — the colon, then exactly one whitespace character.
fn colon_then_whitespace(body: &str, at: usize) -> bool {
    if body.as_bytes().get(at) != Some(&b':') {
        return false;
    }
    body[at + 1..].chars().next().is_some_and(is_python_space)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speaker_prefixes_are_ascii_uppercase_only() {
        assert!(is_speaker_prefix("Alex: hello"));
        // É. `[A-Z]` is a literal range, not a Unicode property.
        assert!(!is_speaker_prefix("\u{c9}mile: bonjour"));
        assert!(!is_speaker_prefix("alex: hello"));
        assert!(!is_speaker_prefix("1A: x"));
    }

    #[test]
    fn a_speaker_prefix_allows_at_most_four_words() {
        assert!(is_speaker_prefix("A: x"));
        assert!(is_speaker_prefix("A B C: x"));
        assert!(is_speaker_prefix("A B C D: x"));
        assert!(!is_speaker_prefix("A B C D E: x"));
        // One space between words, because the group opens with exactly one.
        assert!(!is_speaker_prefix("A  B: x"));
        assert!(!is_speaker_prefix("A B  C: x"));
    }

    #[test]
    fn a_speaker_prefix_needs_a_colon_and_one_whitespace() {
        assert!(is_speaker_prefix("A:\tx"));
        assert!(!is_speaker_prefix("A:x"));
        assert!(!is_speaker_prefix("A:"));
        // The word class carries a dot and a hyphen, so these are one word each.
        assert!(is_speaker_prefix("Dr.X: hi"));
        assert!(is_speaker_prefix("A-B: x"));
        assert!(is_speaker_prefix("A_1: x"));
    }

    #[test]
    fn label_patterns_are_prefixes_not_whole_lines() {
        assert!(is_bold_colon_prefix("**Remove:** the thing"));
        assert!(is_bold_colon_prefix("**On X**: \"quote\""));
        assert!(is_bold_colon_prefix("**a**:"));
        assert!(is_bold_colon_prefix("**a:**"));
        assert!(!is_bold_colon_prefix("**:** empty label"));
        assert!(!is_bold_colon_prefix("**a**"));
        // A space is a label as far as `[^*]+` is concerned; nothing is not.
        assert!(is_bold_colon_prefix("** **: x"));
        // The run stops at the first `*`, so an inner one is fatal.
        assert!(!is_bold_colon_prefix("**a*b:** x"));
        // Leading whitespace is rejected here and tolerated by `is_label_line`.
        assert!(!is_bold_colon_prefix(" **a:** x"));
        assert!(is_label_line(" **a:** x"));
    }

    #[test]
    fn a_negated_class_matches_a_newline_too() {
        // `[^*]` and `[^\[\]]` are negated classes, which match `\n` in Python
        // as they do here. Only `.` declines to.
        assert!(is_bold_colon_prefix("**a\nb:** x"));
        assert!(is_whole_line_bold("**a\nb**"));
    }

    #[test]
    fn whole_line_bold_wants_the_whole_line() {
        assert!(is_whole_line_bold("**Title**"));
        assert!(is_whole_line_bold("  **Title**  "));
        assert!(is_whole_line_bold("**a**\n"));
        assert!(is_whole_line_bold("**a**\n\n"));
        assert!(!is_whole_line_bold("**a** **b**"));
        assert!(!is_whole_line_bold("**a***"));
        assert!(!is_whole_line_bold("****"));
        assert!(!is_whole_line_bold("**a**x"));
        assert!(!is_whole_line_bold("*a*"));
    }

    #[test]
    fn a_bracketed_line_takes_one_optional_trailing_dot() {
        assert!(is_bracketed_line("[All agreed.]"));
        assert!(is_bracketed_line("[All agreed.]."));
        assert!(is_bracketed_line("[]"));
        assert!(is_bracketed_line("[a] "));
        assert!(is_bracketed_line("[a]\n"));
        assert!(!is_bracketed_line("[a]x"));
        assert!(!is_bracketed_line("[a].."));
        // A nested bracket ends the run before the closer is reached.
        assert!(!is_bracketed_line("[a[b]]"));
        assert!(!is_bracketed_line("  [a]"));
        assert!(is_label_line("  [a]"));
    }

    #[test]
    fn a_label_line_is_any_of_the_four() {
        assert!(is_label_line("Alex: \"utterance\""));
        assert!(is_label_line("**Remove:** it"));
        assert!(is_label_line("[stage direction]"));
        assert!(is_label_line("**Title**"));
        assert!(!is_label_line("ordinary prose"));
        assert!(!is_label_line(""));
    }
}
