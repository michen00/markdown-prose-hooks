//! Inline code spans: the one pattern in the tool that cannot be a regex here.
//!
//! `_SUB_CODE_SPAN` is ``(`+)(?:(?!\1).)*\1``, which needs a backreference and a
//! negative lookahead. The `regex` crate excludes both by design, so this is
//! hand-written whatever else the port decides — and it is an **approximation of
//! CommonMark that is reproduced rather than corrected**. A real CommonMark span
//! closes on a run of exactly the opener's length; this closes on the first
//! position carrying that many or more, so `` `a``` `` is two spans where a
//! renderer sees one. The corpus pins the approximation. Correcting it here
//! would make the two implementations disagree with each other, which is the
//! only thing this port is not allowed to do.
//!
//! Every expected value in the tests below came from running the Python.

/// The one byte the whole module is about.
const TICK: u8 = b'`';

/// Iterator over the byte ranges `_SUB_CODE_SPAN` would replace.
///
/// Yields the same sequence `re.finditer` does, which is non-overlapping and
/// left to right. The pattern needs at least two backticks, so it can never
/// match empty and the zero-width-advance rule never applies.
pub struct CodeSpans<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl Iterator for CodeSpans<'_> {
    type Item = (usize, usize);

    fn next(&mut self) -> Option<(usize, usize)> {
        let (start, end) = next_span(self.bytes, self.at)?;
        self.at = end;
        Some((start, end))
    }
}

/// Every inline code span in `body`, as byte ranges.
#[must_use]
pub fn code_spans(body: &str) -> CodeSpans<'_> {
    CodeSpans {
        bytes: body.as_bytes(),
        at: 0,
    }
}

/// `_masked_code_spans`: every span blanked to spaces, same length out as in.
///
/// "Same length" is Python's, and Python counts characters: the replacement is
/// `' ' * len(match.group())`. A span holding non-ASCII therefore masks to
/// *fewer bytes* than it occupied, and a caller reasoning about columns is
/// reasoning about the same columns Python would.
#[must_use]
pub fn mask_code_spans(body: &str) -> String {
    let mut masked = String::with_capacity(body.len());
    let mut cursor = 0;
    for (start, end) in code_spans(body) {
        masked.push_str(&body[cursor..start]);
        for _ in 0..body[start..end].chars().count() {
            masked.push(' ');
        }
        cursor = end;
    }
    masked.push_str(&body[cursor..]);
    masked
}

/// `'|' in _masked_code_spans(body)`, without building the mask.
///
/// Observably identical to asking [`mask_code_spans`] and searching its result:
/// masking only ever replaces span bytes with spaces, so a pipe survives exactly
/// when it sits outside every span.
#[must_use]
pub fn contains_unmasked_pipe(body: &str) -> bool {
    let mut cursor = 0;
    for (start, end) in code_spans(body) {
        if body[cursor..start].contains('|') {
            return true;
        }
        cursor = end;
    }
    body[cursor..].contains('|')
}

/// The next span at or after `from`, or `None` when the rest holds none.
fn next_span(bytes: &[u8], from: usize) -> Option<(usize, usize)> {
    let mut i = from;
    while i < bytes.len() {
        if bytes[i] != TICK {
            i += 1;
            continue;
        }
        let mut run = 0;
        while bytes.get(i + run) == Some(&TICK) {
            run += 1;
        }
        // ``(`+)`` is greedy, so the engine tries the whole run first and gives
        // back one backtick at a time. The first opener length that finds a
        // closer wins, and the order is observable: ``` ```a` ``` closes on a
        // one-backtick opener only because three and two both failed first.
        for k in (1..=run).rev() {
            if let Some(end) = find_closer(bytes, i + k, k) {
                return Some((i, end));
            }
        }
        // `i + 1` restarts inside the run, which is what the engine does. It is
        // also indistinguishable from `i + run`, and provably so rather than by
        // luck: reaching this line means every opener length failed, including
        // one, and a one-backtick opener can only fail when the run is one
        // backtick long — with two or more, `bytes[i + 1]` is itself a backtick
        // and closes the span immediately. So the fallthrough is unreachable
        // unless `run == 1`, where the two are the same number.
        i += 1;
    }
    None
}

/// The whole of ``(?:(?!\1).)*\1``: where a span opened with `k` backticks ends.
///
/// The body loop consumes one character at a time and refuses to start one where
/// the closer would match, so it halts at the first position carrying `k`
/// backticks — where the closer then matches — or at a `\n` or the end of input,
/// where it cannot. Every position it did consume failed the same test the
/// closer applies, so backtracking the body can never rescue the attempt and
/// this linear scan is exact rather than approximate.
fn find_closer(bytes: &[u8], start: usize, k: usize) -> Option<usize> {
    let mut j = start;
    loop {
        if j + k <= bytes.len() && bytes[j..j + k].iter().all(|b| *b == TICK) {
            return Some(j + k);
        }
        // `.` does not match `\n` without `re.DOTALL`, and matches every other
        // character — including `\r`, `\x0b`, `\x0c`, U+0085, U+2028 and U+2029,
        // none of which this tool calls a line boundary either.
        if j >= bytes.len() || bytes[j] == b'\n' {
            return None;
        }
        j += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn matched(body: &str) -> Vec<&str> {
        code_spans(body).map(|(s, e)| &body[s..e]).collect()
    }

    #[test]
    fn the_approximation_closes_on_the_first_backtick_of_a_longer_run() {
        // CommonMark would make this one span. The Python does not, the corpus
        // pins the Python, and correcting it is an explicit non-goal.
        assert_eq!(matched("`a```"), ["`a`", "``"]);
    }

    #[test]
    fn openers_are_tried_longest_first() {
        // Three backticks open, and the closer is the *first* run of three, so
        // the trailing run is left over rather than swallowed.
        assert_eq!(matched("``` ``` ```"), ["``` ```", "``"]);
        // Here three and two both fail to find a closer, so the opener backs
        // down to one backtick and closes on the very next one.
        assert_eq!(matched("```a`"), ["``", "`a`"]);
    }

    #[test]
    fn a_bare_double_run_is_an_empty_span() {
        assert_eq!(matched("``"), ["``"]);
        // An odd run leaves its last backtick behind.
        assert_eq!(matched("```"), ["``"]);
        assert_eq!(matched("````"), ["````"]);
        assert_eq!(matched("`````"), ["````"]);
        assert_eq!(matched("``````"), ["``````"]);
    }

    #[test]
    fn a_run_of_two_always_opens_a_span_where_it_starts() {
        // The fact the restart step rests on. A two-backtick run closes on its
        // own second backtick whatever follows it, so an opener search that
        // begins on one can never come away empty — which is why restarting at
        // `i + 1` and at `i + run` are the same walk.
        for tail in ["", "a", "`", "\n", "\\", "a`", "\n`"] {
            for run in 2..=4 {
                let body = format!("x{}{tail}", "`".repeat(run));
                assert_eq!(
                    code_spans(&body).next().map(|(start, _)| start),
                    Some(1),
                    "run of {run} before {tail:?}"
                );
            }
        }
    }

    #[test]
    fn an_unterminated_run_matches_nothing() {
        assert_eq!(matched("`a"), Vec::<&str>::new());
        assert!(matched("").is_empty());
        assert!(matched("no ticks here").is_empty());
    }

    #[test]
    fn a_longer_opener_swallows_a_shorter_inner_run() {
        assert_eq!(matched("``a | b` c``"), ["``a | b` c``"]);
        assert!(!contains_unmasked_pipe("``a | b` c``"));
        assert!(!contains_unmasked_pipe("``|`|``"));
    }

    #[test]
    fn a_bare_pipe_survives_masking() {
        assert!(contains_unmasked_pipe("a | b"));
        assert!(contains_unmasked_pipe("a `b` | c"));
        // A pipe outside a span and another inside one: the outside one wins.
        assert!(contains_unmasked_pipe("|`|`|"));
        assert!(!contains_unmasked_pipe("`|`"));
    }

    #[test]
    fn mask_is_char_length_not_byte_length() {
        // Python's `' ' * len(group)` counts characters, so a non-ASCII span
        // masks to fewer bytes than it occupied: four here, against eight.
        assert_eq!(mask_code_spans("`\u{65e5}\u{672c}`"), "    ");
        assert_eq!(mask_code_spans("a`b`c"), "a   c");
        assert_eq!(mask_code_spans("``` ``` ```"), "          `");
        assert_eq!(mask_code_spans("````a``"), "    a  ");
        assert_eq!(mask_code_spans("`a"), "`a");
    }

    #[test]
    fn a_backslash_does_not_escape_a_backtick() {
        // The Python pattern has no escape handling. Adding CommonMark-correct
        // escaping would be a silent behavior change, so the span opens on the
        // backtick after the backslash and the backslash stays outside it.
        assert_eq!(matched("\\`a\\`"), ["`a\\`"]);
    }

    #[test]
    fn a_newline_stops_a_span_and_nothing_else_does() {
        // Python's `.` does not match `\n` without `re.DOTALL`.
        assert_eq!(matched("`a\nb`"), Vec::<&str>::new());
        // Every other separator this tool knows about is ordinary content.
        assert_eq!(matched("`a\rb`"), ["`a\rb`"]);
        assert_eq!(matched("`a\u{2028}b`"), ["`a\u{2028}b`"]);
        assert_eq!(matched("`a\u{b}b`"), ["`a\u{b}b`"]);
    }

    #[test]
    fn the_pipe_shortcut_agrees_with_the_mask_it_stands_for() {
        for body in [
            "", "|", "`|`", "``|`|``", "a | b", "|`a`", "`a`|", "`a|", "```|```", "x``y``z|",
        ] {
            assert_eq!(
                contains_unmasked_pipe(body),
                mask_code_spans(body).contains('|'),
                "disagreed on {body:?}"
            );
        }
    }
}
