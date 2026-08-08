//! Transcript detection: the one classifier the transform tier cannot pin.
//!
//! `is_transcript_like_markdown` is not reachable from `unwrap_markdown_prose` —
//! the CLI asks it before the transform runs, and answers yes by leaving the
//! file alone entirely. So `corpus/cases/` says nothing about it and
//! `corpus/cli/` says everything, which is why the process tier was built first.
//!
//! Both heading patterns count characters over an ASCII class, so the counted
//! quantifiers here are the only ones in the crate where the character count and
//! the byte count could part company — and they cannot, because a non-ASCII
//! character is not in either class and stops the run before the count is
//! reached.
//!
//! Every expected value in the tests below came from running the Python.

use crate::scan::{py_splitlines_keepends, py_trim, split_eol};

/// `_TRANSCRIPT_HEADING_FLOOR`: fewer headings than this is not a transcript.
pub const TRANSCRIPT_HEADING_FLOOR: usize = 2;

/// `_TRANSCRIPT_HEADING_RATIO`: the density a transcript has to clear.
///
/// Real transcripts run 0.12 to 0.49; a prose document with two stray
/// colon-terminated intro lines runs about 0.004. The gate exists so a long
/// design document is never skipped wholesale over a couple of them.
pub const TRANSCRIPT_HEADING_RATIO: f64 = 0.05;

/// `_MATCH_BARE_SPEAKER_HEADING`: `^[A-Z][a-zA-Z0-9_. -]{0,39}:$`.
///
/// A heading that stands alone above a blank line, such as `MC:`.
#[must_use]
pub fn match_bare_speaker_heading(body: &str) -> bool {
    let bytes = body.as_bytes();
    if !bytes.first().is_some_and(u8::is_ascii_uppercase) {
        return false;
    }
    let mut end = 1;
    while bytes.get(end).is_some_and(|b| is_bare_class_byte(*b)) {
        end += 1;
    }
    // The run is maximal and giving characters back cannot help: the colon the
    // pattern wants next is not in the class, so every shorter reading stops on
    // a class character instead. An over-long run therefore just fails.
    if end - 1 > 39 {
        return false;
    }
    ends_after_colon(body, bytes, end)
}

/// `_MATCH_TIMESTAMPED_SPEAKER_HEADING`: `^[A-Z][a-zA-Z0-9_.-]{0,19} [0-9]{1,2}:[0-9]{2}$`.
///
/// A heading carrying an inline timestamp, such as `MC 0:15`, which sits
/// directly above its utterance rather than above a blank line.
///
/// The digits are `[0-9]` and not `\d`: the specification narrowed them, because
/// `\d` selected 650 code points on 3.10 and 680 on 3.13 and so was not one
/// behavior to port. `corpus/cli/a-non-ascii-digit-timestamp-is-not-a-transcript`
/// pins the narrowed reading.
#[must_use]
pub fn match_timestamped_speaker_heading(body: &str) -> bool {
    let bytes = body.as_bytes();
    if !bytes.first().is_some_and(u8::is_ascii_uppercase) {
        return false;
    }
    let mut end = 1;
    // The same class as the speaker prefix in `label`, minus the space, which is
    // what separates the name from the timestamp here.
    while bytes.get(end).is_some_and(|b| is_name_class_byte(*b)) {
        end += 1;
    }
    if end - 1 > 19 || bytes.get(end) != Some(&b' ') {
        return false;
    }
    let start = end + 1;
    let mut run = 0;
    while run < 2 && bytes.get(start + run).is_some_and(u8::is_ascii_digit) {
        run += 1;
    }
    // `[0-9]{1,2}` is greedy, so two digits are tried before one. `MC 1:23` only
    // matches on the one-digit reading, and it is reached by backtracking.
    (1..=run).rev().any(|hours| {
        let colon = start + hours;
        bytes.get(colon) == Some(&b':')
            && bytes.get(colon + 1).is_some_and(u8::is_ascii_digit)
            && bytes.get(colon + 2).is_some_and(u8::is_ascii_digit)
            && ends_here(body, colon + 3)
    })
}

/// `_is_transcript_like_markdown`: does this document use repeated speaker turns?
#[must_use]
pub fn is_transcript_like_markdown(text: &str) -> bool {
    let bodies: Vec<&str> = py_splitlines_keepends(text)
        .iter()
        .map(|line| py_trim(split_eol(line).0))
        .collect();
    let mut headings = 0;
    let mut non_blank = 0;
    for (index, body) in bodies.iter().enumerate() {
        if !body.is_empty() {
            non_blank += 1;
        }
        let next_body = bodies.get(index + 1).copied().unwrap_or("");
        // The two shapes want opposite neighbors, which is the whole reason
        // they are two shapes: a bare heading stands above a blank line, and a
        // timestamped one sits directly above the utterance it labels.
        let counts = if match_bare_speaker_heading(body) {
            next_body.is_empty()
        } else if match_timestamped_speaker_heading(body) {
            !next_body.is_empty()
        } else {
            false
        };
        if counts {
            headings += 1;
        }
    }
    if headings < TRANSCRIPT_HEADING_FLOOR || non_blank == 0 {
        return false;
    }
    // True division on both sides, so a document of 40 lines needs two headings
    // and a document of 41 needs three.
    headings as f64 / non_blank as f64 >= TRANSCRIPT_HEADING_RATIO
}

/// `[a-zA-Z0-9_. -]`, the bare heading's class. Note the space.
fn is_bare_class_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b' ' | b'-')
}

/// `[a-zA-Z0-9_.-]`, the timestamped heading's name class. No space.
fn is_name_class_byte(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-')
}

/// A colon at `at`, and then the end of the pattern.
fn ends_after_colon(body: &str, bytes: &[u8], at: usize) -> bool {
    bytes.get(at) == Some(&b':') && ends_here(body, at + 1)
}

/// Python's `$` outside `re.MULTILINE`.
///
/// It matches at the end of the string or just before a newline that *is* the
/// last character, and only `\n`: a trailing `\r` fails where a trailing `\n`
/// passes. Callers here always pass a stripped line, so this can only matter to
/// somebody calling the pattern directly — which the tests do.
fn ends_here(body: &str, at: usize) -> bool {
    matches!(&body[at..], "" | "\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bare_heading_counts_characters_over_an_ascii_class() {
        assert!(match_bare_speaker_heading("MC:"));
        assert!(match_bare_speaker_heading("A:"));
        assert!(match_bare_speaker_heading("A B C D E F:"));
        assert!(match_bare_speaker_heading("A.B-C_1:"));
        // 'A' plus 39 is the boundary; 'A' plus 40 is not a heading.
        assert!(match_bare_speaker_heading(&format!("A{}:", "e".repeat(39))));
        assert!(!match_bare_speaker_heading(&format!(
            "A{}:",
            "e".repeat(40)
        )));
        // Non-ASCII is rejected by the class, and never reaches the count.
        assert!(!match_bare_speaker_heading(&format!(
            "A{}:",
            "\u{e9}".repeat(39)
        )));
        assert!(!match_bare_speaker_heading("a:"));
        assert!(!match_bare_speaker_heading("A"));
        assert!(!match_bare_speaker_heading("A::"));
        assert!(!match_bare_speaker_heading("A:b"));
        assert!(!match_bare_speaker_heading(":"));
    }

    #[test]
    fn a_timestamped_heading_is_ascii_digits_only() {
        // The plan drafted the opposite expectation, from a belief that the
        // Python's `\d` was one set to be ported faithfully. It was not.
        assert!(match_timestamped_speaker_heading("MC 0:15"));
        assert!(match_timestamped_speaker_heading("MC 12:34"));
        assert!(!match_timestamped_speaker_heading(
            "MC \u{660}:\u{661}\u{665}"
        ));
        assert!(!match_timestamped_speaker_heading(
            "MC \u{967}\u{968}:\u{969}\u{969}"
        ));
    }

    #[test]
    fn a_timestamp_takes_one_or_two_digits_then_exactly_two() {
        // `MC 1:23` matches only on the one-digit reading of a greedy `{1,2}`.
        assert!(match_timestamped_speaker_heading("MC 1:23"));
        assert!(!match_timestamped_speaker_heading("MC 123:45"));
        assert!(!match_timestamped_speaker_heading("MC 1:2"));
        assert!(!match_timestamped_speaker_heading("MC 1:234"));
        assert!(!match_timestamped_speaker_heading("MC1:23"));
        // The name class holds no space, so a two-word name is not a heading.
        assert!(!match_timestamped_speaker_heading("M C 1:23"));
        assert!(match_timestamped_speaker_heading(&format!(
            "A{} 1:23",
            "e".repeat(19)
        )));
        assert!(!match_timestamped_speaker_heading(&format!(
            "A{} 1:23",
            "e".repeat(20)
        )));
    }

    #[test]
    fn the_end_anchor_takes_one_newline_and_only_a_newline() {
        assert!(match_bare_speaker_heading("A:\n"));
        assert!(match_timestamped_speaker_heading("MC 0:15\n"));
        assert!(!match_timestamped_speaker_heading("MC 0:15\r"));
    }

    #[test]
    fn two_headings_over_a_short_document_do_classify() {
        assert!(is_transcript_like_markdown("MC:\n\na\nb\n\nJR:\n\nc\nd\n"));
        assert!(is_transcript_like_markdown(
            "MC 0:15\nhello\n\nJR 0:20\nthere\n"
        ));
    }

    #[test]
    fn the_density_gate_keeps_prose_out() {
        let mut doc = String::from("Concretely:\n\n");
        for _ in 0..200 {
            doc.push_str("A line of ordinary prose.\n");
        }
        doc.push_str("\nFinal note:\n");
        assert!(!is_transcript_like_markdown(&doc));
    }

    #[test]
    fn a_heading_needs_the_right_neighbor_to_count() {
        // Two bare headings, but the first has a non-blank line under it, so
        // only one of them counts and the floor is not cleared.
        assert!(!is_transcript_like_markdown("MC:\nJR:\n"));
        assert!(!is_transcript_like_markdown("MC:\n\na\n"));
        assert!(!is_transcript_like_markdown(""));
    }
}
