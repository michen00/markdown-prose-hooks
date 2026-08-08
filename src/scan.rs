//! Structural line matchers: what a line *is*, before anything decides what to
//! do with it.
//!
//! Each function ports one compiled pattern or one small helper from
//! `src/markdown_prose_hooks/unwrap.py`, and the pattern it answers to is named
//! in its documentation. Nothing here holds state or reads more than the line it
//! is given.
//!
//! Every expected value in the tests below was produced by running the Python
//! rather than by reading the pattern. Reading a regex and writing down what it
//! ought to do reproduces the reader's misunderstanding in a second language,
//! which is the one failure a second implementation is supposed to catch.

/// Python's `str.isspace()`, `str.strip()`, and `\s` on a `str` pattern.
///
/// One set of 29 code points, verified identical across all three on 3.10 and
/// 3.13: the Unicode `White_Space` property plus the four C0 separators
/// `U+001C`-`U+001F`. Rust's `char::is_whitespace` is `White_Space` alone, 25
/// points, so `str::trim` is not `str.strip()` and is never used to port it.
///
/// Written out rather than delegated to `char::is_whitespace` plus the four,
/// because this predicate decides parity and should not depend on which Unicode
/// version the compiler shipped with. `python_whitespace_matches_rusts_view`
/// below is the drift detector for that choice.
#[must_use]
pub fn is_python_space(c: char) -> bool {
    matches!(c,
        '\u{9}'..='\u{d}'        // tab, newline, vertical tab, form feed, return
        | '\u{1c}'..='\u{1f}'    // file, group, record, unit separator
        | '\u{20}'               // space
        | '\u{85}'               // next line
        | '\u{a0}'               // no-break space
        | '\u{1680}'             // ogham space mark
        | '\u{2000}'..='\u{200a}'
        | '\u{2028}'             // line separator
        | '\u{2029}'             // paragraph separator
        | '\u{202f}'             // narrow no-break space
        | '\u{205f}'             // medium mathematical space
        | '\u{3000}'             // ideographic space
    )
}

/// Python's `str.strip()`.
#[must_use]
pub fn py_trim(s: &str) -> &str {
    s.trim_matches(is_python_space)
}

/// Python's `str.lstrip()`.
#[must_use]
pub fn py_trim_start(s: &str) -> &str {
    s.trim_start_matches(is_python_space)
}

/// Python's `str.rstrip()`.
#[must_use]
pub fn py_trim_end(s: &str) -> &str {
    s.trim_end_matches(is_python_space)
}

/// `_split_eol`: return `(body, eol)` where `eol` is `\r\n`, `\n`, `\r` or empty.
#[must_use]
pub fn split_eol(line: &str) -> (&str, &str) {
    // `\r\n` first, or a CRLF line reports a `\n` terminator and keeps the `\r`
    // as the last byte of its body.
    for eol in ["\r\n", "\n", "\r"] {
        if let Some(body) = line.strip_suffix(eol) {
            return (body, eol);
        }
    }
    (line, "")
}

/// `_split_lines(keepends=True)`: split on `\r\n`, `\n` and `\r`, and nothing else.
///
/// Deliberately not `str::lines` and deliberately not `str.splitlines`. Task 3
/// narrowed the specification to these three boundaries in both languages; a
/// vertical tab is content, and joining across one deleted it.
#[must_use]
pub fn py_splitlines_keepends(text: &str) -> Vec<&str> {
    // Scanning bytes is safe for exactly these two: `\r` and `\n` are ASCII, so
    // they never occur inside a multi-byte UTF-8 sequence and every index this
    // slices at is a character boundary.
    let bytes = text.as_bytes();
    let mut lines = Vec::new();
    let mut start = 0;
    let mut index = 0;
    while index < bytes.len() {
        let end = match bytes[index] {
            b'\r' if bytes.get(index + 1) == Some(&b'\n') => index + 2,
            b'\r' | b'\n' => index + 1,
            _ => {
                index += 1;
                continue;
            }
        };
        lines.push(&text[start..end]);
        index = end;
        start = end;
    }
    if start < bytes.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// `_has_hard_break`: a trailing backslash or two trailing spaces.
#[must_use]
pub fn has_hard_break(body: &str) -> bool {
    body.ends_with('\\') || body.ends_with("  ")
}

/// `_starts_front_matter`: `---` on line one with a reachable closer below it.
///
/// A bare `---` is ambiguous between front matter and a thematic break, so it
/// only counts when a closing `---` or `...` exists somewhere later. The scan is
/// unbounded on purpose: a bounded one corrupts a long YAML header.
#[must_use]
pub fn starts_front_matter(lines: &[&str]) -> bool {
    let Some(first) = lines.first() else {
        return false;
    };
    let opener = split_eol(first).0;
    // `removeprefix` leaves the string alone when the prefix is absent.
    if opener.strip_prefix('\u{feff}').unwrap_or(opener) != "---" {
        return false;
    }
    lines[1..]
        .iter()
        .any(|line| matches!(split_eol(line).0, "---" | "..."))
}

/// `_MATCH_FENCE`: return `(fence_char, fence_len)` for a fenced code opener.
#[must_use]
pub fn match_opening_fence(body: &str) -> Option<(char, usize)> {
    let bytes = body.as_bytes();
    let indent = leading_spaces(bytes);
    if indent > 3 {
        return None;
    }
    let fence_char = match bytes.get(indent) {
        Some(b'`') => '`',
        Some(b'~') => '~',
        _ => return None,
    };
    let run = bytes[indent..]
        .iter()
        .take_while(|b| **b == fence_char as u8)
        .count();
    (run >= 3).then_some((fence_char, run))
}

/// `_is_closing_fence`: does `body` close a fence of this character and length?
#[must_use]
pub fn is_closing_fence(body: &str, fence_char: char, fence_len: usize) -> bool {
    let stripped = body.trim_start_matches(' ');
    if body.len() - stripped.len() > 3 {
        return false;
    }
    let mut rest = stripped;
    for _ in 0..fence_len {
        match rest.strip_prefix(fence_char) {
            Some(shorter) => rest = shorter,
            None => return false,
        }
    }
    // Python asks whether the set of remaining characters is a subset of
    // `{fence_char}`, and the empty set satisfies that -- as does an all-empty
    // iterator here.
    py_trim(rest).chars().all(|c| c == fence_char)
}

/// `_MATCH_BLOCKQUOTE`: return `(prefix, rest)` for one blockquote level.
#[must_use]
pub fn match_blockquote(body: &str) -> Option<(&str, &str)> {
    let end = match_blockquote_once(body)?;
    Some((&body[..end], &body[end..]))
}

/// `_MATCH_BLOCKQUOTE_PREFIX`: the byte length of the whole marker stack.
#[must_use]
pub fn match_blockquote_prefix(body: &str) -> Option<usize> {
    let mut end = 0;
    // Each level consumes at least the `>`, so this always makes progress.
    while let Some(step) = match_blockquote_once(&body[end..]) {
        end += step;
    }
    (end > 0).then_some(end)
}

/// `_SUB_BLOCKQUOTE_PREFIX('', body)`: peel every blockquote level, or none.
///
/// The Python calls `re.sub`, whose default is replace-all, but the pattern is
/// anchored with `^` and compiled without `re.MULTILINE`, so it can only fire at
/// offset 0. A line further down a multi-line string keeps its marker.
#[must_use]
pub fn strip_blockquote_prefix(body: &str) -> &str {
    match match_blockquote_prefix(body) {
        Some(end) => &body[end..],
        None => body,
    }
}

/// `_MATCH_LIST_MARKER`: return `(prefix, content_col, rest)`.
///
/// `content_col` is a byte offset, and since the narrowing to ASCII digits the
/// whole prefix is ASCII -- a bounded run of spaces, the marker, then one or
/// more spaces -- so it is also the character offset the Python reports. That
/// was not true while the marker could be a Devanagari digit.
///
/// The trailing run here is **ASCII spaces only**, where `is_list_line` takes
/// any Python whitespace. They look like one predicate and are not: a tab after
/// the marker gives `None` here and `true` there.
#[must_use]
pub fn match_list_marker(body: &str) -> Option<(&str, usize, &str)> {
    let bytes = body.as_bytes();
    let indent = leading_spaces(bytes);
    if indent > 3 {
        return None;
    }
    let after_marker = match_marker(bytes, indent)?;
    let mut cursor = after_marker;
    while bytes.get(cursor) == Some(&b' ') {
        cursor += 1;
    }
    if cursor == after_marker {
        return None;
    }
    Some((&body[..cursor], cursor, &body[cursor..]))
}

/// `_MATCH_LIST`: a marker at column zero followed by any Python whitespace.
#[must_use]
pub fn is_list_line(body: &str) -> bool {
    let bytes = body.as_bytes();
    // No indent is accepted at all, unlike `match_list_marker`: callers hand
    // this one an already-stripped line.
    let Some(after_marker) = match_marker(bytes, 0) else {
        return false;
    };
    body[after_marker..]
        .chars()
        .next()
        .is_some_and(is_python_space)
}

/// `_MATCH_ALPHA_LIST`: `a.` / `b)` sub-enumerators, which CommonMark does not
/// treat as list markers but which are still load-bearing layout.
#[must_use]
pub fn is_alpha_list_line(body: &str) -> bool {
    let bytes = body.as_bytes();
    if !bytes.first().is_some_and(u8::is_ascii_alphabetic) {
        return false;
    }
    if !matches!(bytes.get(1), Some(b'.' | b')')) {
        return false;
    }
    // Exactly one whitespace character is required, not one or more -- the
    // pattern ends `\s` rather than `\s+`. With nothing after it in the pattern
    // that is the same acceptance, but it is worth not "fixing".
    body[2..].chars().next().is_some_and(is_python_space)
}

/// `_MATCH_SETEXT`: a run of `=` or a run of `-`, then whitespace to the end.
#[must_use]
pub fn is_setext_line(body: &str) -> bool {
    let Some(first) = body.chars().next() else {
        return false;
    };
    if first != '=' && first != '-' {
        return false;
    }
    // The alternation is `=+|-+`, so the run may not mix: `=-=` matches neither
    // branch. Trimming the first character's own run reproduces that.
    body.trim_start_matches(first).chars().all(is_python_space)
}

/// `_MATCH_THEMATIC`: three or more `-`, `*` or `_`, whitespace permitted between.
///
/// Mixing the three is accepted, which CommonMark does not do; that is the
/// Python's shape and this is a port, not a correction.
#[must_use]
pub fn is_thematic_break(body: &str) -> bool {
    // Each repetition is marker-then-whitespace, so the line cannot start with
    // whitespace however much of it follows a marker.
    if !body.starts_with(['-', '*', '_']) {
        return false;
    }
    let mut markers = 0usize;
    for c in body.chars() {
        if matches!(c, '-' | '*' | '_') {
            markers += 1;
        } else if !is_python_space(c) {
            return false;
        }
    }
    markers >= 3
}

/// `_MATCH_LINK_REFERENCE`: `[label]:` with a non-empty label.
#[must_use]
pub fn is_link_reference(body: &str) -> bool {
    let Some(rest) = body.strip_prefix('[') else {
        return false;
    };
    // `[^\]]+` is greedy but cannot cross a `]`, so it always ends at the first
    // one; backtracking never reaches a later `]`.
    match rest.find(']') {
        None | Some(0) => false,
        Some(index) => rest[index + 1..].starts_with(':'),
    }
}

/// `_MATCH_HTML_TAG_NAME`: the tag name of an opening tag, case preserved.
#[must_use]
pub fn match_html_tag_name(body: &str) -> Option<&str> {
    let rest = body.strip_prefix('<')?;
    if !rest.as_bytes().first()?.is_ascii_alphabetic() {
        return None;
    }
    let end = rest
        .as_bytes()
        .iter()
        .position(|b| !(b.is_ascii_alphanumeric() || *b == b'-'))
        .unwrap_or(rest.len());
    Some(&rest[..end])
}

/// `match_opening_html_block`: the tag name of a block that stays open.
///
/// Two different lowercasings, and they are not interchangeable. The tag *name*
/// comes from `[a-zA-Z][a-zA-Z0-9-]*` and is ASCII by construction, so
/// `to_ascii_lowercase` is exact and cheap. The *line* is lowercased with
/// Python's full-Unicode `str.lower()`, which can change length and can fold
/// non-ASCII onto ASCII, so it needs `to_lowercase`.
#[must_use]
pub fn match_opening_html_block(body: &str) -> Option<String> {
    let stripped = py_trim(body);
    if !stripped.starts_with('<') {
        return None;
    }
    // `-->` cannot reach here past the check above; it is carried because the
    // Python carries it, and a port that drops a redundant guard invites the
    // next reader to wonder which one of them was wrong.
    for prefix in ["<!--", "-->", "<?", "<![", "<!", "</"] {
        if stripped.starts_with(prefix) {
            return None;
        }
    }
    if stripped.ends_with("/>") {
        return None;
    }
    let name = match_html_tag_name(stripped)?.to_ascii_lowercase();
    if stripped.to_lowercase().contains(&format!("</{name}>")) {
        return None;
    }
    Some(name)
}

/// `_match_opening_html_literal_terminator`: what would close a raw HTML literal.
#[must_use]
pub fn match_opening_html_literal_terminator(body: &str) -> Option<&'static str> {
    let stripped = py_trim_start(body);
    for (opener, terminator) in [("<!--", "-->"), ("<?", "?>"), ("<![CDATA[", "]]>")] {
        if let Some(tail) = stripped.strip_prefix(opener) {
            if !tail.contains(terminator) {
                return Some(terminator);
            }
        }
    }
    // A declaration such as `<!DOCTYPE html`. Python asks for `isascii() and
    // isupper()` on the third character, which together are exactly A-Z.
    let mut chars = stripped.chars();
    if chars.next() != Some('<') || chars.next() != Some('!') {
        return None;
    }
    let third = chars.next()?;
    (third.is_ascii_uppercase() && !chars.as_str().contains('>')).then_some(">")
}

/// `_MATCH_GFM_ALERT`: `[!NOTE]`, `[!TIP]-`, and the rest of the alert syntax.
#[must_use]
pub fn is_gfm_alert(body: &str) -> bool {
    let Some(rest) = body.strip_prefix("[!") else {
        return false;
    };
    let bytes = rest.as_bytes();
    if !bytes.first().is_some_and(u8::is_ascii_uppercase) {
        return false;
    }
    let end = bytes
        .iter()
        .position(|b| !(b.is_ascii_uppercase() || b.is_ascii_digit() || matches!(b, b'_' | b'-')))
        .unwrap_or(bytes.len());
    let Some(tail) = rest[end..].strip_prefix(']') else {
        return false;
    };
    let tail = tail.strip_prefix(['+', '-']).unwrap_or(tail);
    // Python's `$` outside MULTILINE matches at the end of the string or just
    // before a newline that *is* the last character -- and only `\n`. A
    // trailing `\r` therefore fails where a trailing `\n` passes.
    tail.is_empty() || tail == "\n"
}

/// `_RAW_HTML_TAGS`: tags whose content is literal and must not be reflowed.
#[must_use]
pub fn is_raw_html_tag(name: &str) -> bool {
    matches!(name, "pre" | "script" | "style" | "textarea")
}

/// Count leading ASCII spaces, stopping at four so the caller can reject `> 3`.
fn leading_spaces(bytes: &[u8]) -> usize {
    bytes.iter().take(4).take_while(|b| **b == b' ').count()
}

/// One blockquote level at `body`'s start: the byte length it occupies.
fn match_blockquote_once(body: &str) -> Option<usize> {
    let bytes = body.as_bytes();
    let indent = leading_spaces(bytes);
    if indent > 3 || bytes.get(indent) != Some(&b'>') {
        return None;
    }
    let mut end = indent + 1;
    // ` ?`, at most one, which is why `>  a` yields a rest of ` a`.
    if bytes.get(end) == Some(&b' ') {
        end += 1;
    }
    Some(end)
}

/// The marker itself -- `[-+*]` or a run of ASCII digits then `.` or `)`.
///
/// Shared by `match_list_marker` and `is_list_line` because the marker half of
/// the two patterns is identical. What follows it is not, and each caller spells
/// its own trailing rule rather than taking one from here.
fn match_marker(bytes: &[u8], start: usize) -> Option<usize> {
    let mut cursor = start;
    match bytes.get(cursor)? {
        b'-' | b'+' | b'*' => return Some(cursor + 1),
        b'0'..=b'9' => {
            while matches!(bytes.get(cursor), Some(b'0'..=b'9')) {
                cursor += 1;
            }
        }
        _ => return None,
    }
    // `[0-9]+` is greedy and backtracking cannot help: giving a digit back only
    // exposes another digit, never the `.` or `)` the pattern needs next.
    match bytes.get(cursor) {
        Some(b'.' | b')') => Some(cursor + 1),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_whitespace_matches_rusts_view_plus_four() {
        // The drift detector for writing the set out by hand. If a future Rust
        // ships a changed `White_Space`, this fails here rather than silently
        // changing what the tool considers a blank line.
        for cp in 0..=0x10_FFFFu32 {
            let Some(c) = char::from_u32(cp) else {
                continue;
            };
            let expected = c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}');
            assert_eq!(is_python_space(c), expected, "disagreed on U+{cp:04X}");
        }
        assert_eq!(
            (0..=0x10_FFFFu32)
                .filter_map(char::from_u32)
                .filter(|c| is_python_space(*c))
                .count(),
            29
        );
    }

    #[test]
    fn python_whitespace_includes_the_c0_separators() {
        assert!(is_python_space('\u{1c}'));
        assert!(is_python_space('\u{1f}'));
        assert!(!'\u{1c}'.is_whitespace());
        assert_eq!(py_trim("\u{1c}a\u{1e}"), "a");
        assert_eq!("\u{1c}a\u{1e}".trim(), "\u{1c}a\u{1e}");
        // A no-break space is whitespace to Python and to Rust alike.
        assert_eq!(py_trim("\u{a0}a\u{a0}"), "a");
        assert_eq!(py_trim_start("\u{1c}a\u{1e}"), "a\u{1e}");
        assert_eq!(py_trim_end("\u{1c}a\u{1e}"), "\u{1c}a");
    }

    #[test]
    fn an_ordered_list_marker_is_ascii_digits_only() {
        // The specification narrowed to `[0-9]`; `\d` was 650 code points on
        // 3.10 and 680 on 3.13, so there was no one Python behavior to port.
        assert!(is_list_line("1. x"));
        assert!(!is_list_line("\u{661}. x")); // ARABIC-INDIC ONE
        assert!(!is_list_line("\u{967}. x")); // DEVANAGARI ONE
        assert!(match_list_marker("\u{661}. x").is_none());
    }

    #[test]
    fn a_list_marker_reports_its_content_column() {
        // ASCII throughout since the narrowing, so this index is the same
        // number in characters and in bytes. It was not before.
        assert_eq!(match_list_marker("12. x"), Some(("12. ", 4, "x")));
        assert_eq!(match_list_marker("- x"), Some(("- ", 2, "x")));
        assert_eq!(match_list_marker("-  x"), Some(("-  ", 3, "x")));
        assert_eq!(match_list_marker("   - x"), Some(("   - ", 5, "x")));
        assert_eq!(match_list_marker("    - x"), None);
        assert_eq!(match_list_marker("-x"), None);
        assert_eq!(match_list_marker("1.x"), None);
        assert_eq!(match_list_marker("1a. x"), None);
    }

    #[test]
    fn list_marker_needs_a_space_where_list_line_takes_any_whitespace() {
        assert!(match_list_marker("-\tx").is_none());
        assert!(is_list_line("-\tx"));
        // And any Unicode whitespace, not merely a tab.
        assert!(is_list_line("*\u{a0}x"));
        // `is_list_line` accepts no indent at all.
        assert!(!is_list_line(" - x"));
    }

    #[test]
    fn an_alpha_enumerator_needs_one_whitespace() {
        assert!(is_alpha_list_line("a. x"));
        assert!(is_alpha_list_line("a) x"));
        assert!(is_alpha_list_line("a.\tx"));
        assert!(is_alpha_list_line("A. x"));
        assert!(!is_alpha_list_line("a.x"));
        assert!(!is_alpha_list_line("ab. x"));
        assert!(!is_alpha_list_line("a."));
    }

    #[test]
    fn a_closing_fence_tolerates_python_whitespace_after_it() {
        assert!(is_closing_fence("```\u{1c}", '`', 3));
        assert!(is_closing_fence("```", '`', 3));
        assert!(is_closing_fence("   ```", '`', 3));
        assert!(is_closing_fence("``` ```", '`', 3));
        assert!(is_closing_fence("````", '`', 3));
        assert!(!is_closing_fence("    ```", '`', 3));
        assert!(!is_closing_fence("```x", '`', 3));
        assert!(!is_closing_fence("``", '`', 3));
    }

    #[test]
    fn an_opening_fence_reports_its_character_and_length() {
        assert_eq!(match_opening_fence("```"), Some(('`', 3)));
        assert_eq!(match_opening_fence("   ```"), Some(('`', 3)));
        assert_eq!(match_opening_fence("~~~~"), Some(('~', 4)));
        assert_eq!(match_opening_fence("```rust"), Some(('`', 3)));
        assert_eq!(match_opening_fence(" ~~~ "), Some(('~', 3)));
        assert_eq!(match_opening_fence("    ```"), None);
        assert_eq!(match_opening_fence("``"), None);
        assert_eq!(match_opening_fence("`~`"), None);
    }

    #[test]
    fn split_eol_recognizes_the_three_boundaries() {
        assert_eq!(split_eol("a\r\n"), ("a", "\r\n"));
        assert_eq!(split_eol("a\n"), ("a", "\n"));
        assert_eq!(split_eol("a\r"), ("a", "\r"));
        assert_eq!(split_eol("a"), ("a", ""));
        assert_eq!(split_eol("\r\n"), ("", "\r\n"));
        assert_eq!(split_eol(""), ("", ""));
    }

    #[test]
    fn splitlines_is_narrow_per_the_specification() {
        // Task 3 narrowed both implementations to three boundaries, so a
        // vertical tab and a line separator are both content.
        assert_eq!(py_splitlines_keepends("a\u{b}b\n"), vec!["a\u{b}b\n"]);
        assert_eq!(py_splitlines_keepends("a\u{2028}b\n"), vec!["a\u{2028}b\n"]);
        assert_eq!(py_splitlines_keepends("a\r\nb\n"), vec!["a\r\n", "b\n"]);
        assert_eq!(py_splitlines_keepends("a\rb"), vec!["a\r", "b"]);
        assert_eq!(py_splitlines_keepends("a\n\n"), vec!["a\n", "\n"]);
        assert!(py_splitlines_keepends("").is_empty());
        assert_eq!(py_splitlines_keepends("a"), vec!["a"]);
    }

    #[test]
    fn a_hard_break_is_a_backslash_or_two_spaces() {
        assert!(has_hard_break("a  "));
        assert!(has_hard_break("a\\"));
        assert!(has_hard_break("  "));
        assert!(!has_hard_break("a "));
        assert!(!has_hard_break("a"));
        assert!(!has_hard_break(""));
    }

    #[test]
    fn front_matter_needs_a_reachable_closer_and_tolerates_a_bom() {
        assert!(starts_front_matter(&["---\n", "a: 1\n", "---\n"]));
        assert!(starts_front_matter(&["\u{feff}---\n", "---\n"]));
        assert!(starts_front_matter(&["---\n", "...\n"]));
        assert!(starts_front_matter(&["---\r\n", "---\r\n"]));
        assert!(!starts_front_matter(&["---\n", "a: 1\n"]));
        assert!(!starts_front_matter(&[]));
        // A trailing space on the opener is not `---`.
        assert!(!starts_front_matter(&["--- \n", "---\n"]));
    }

    #[test]
    fn a_blockquote_takes_one_level_and_at_most_one_space() {
        assert_eq!(match_blockquote("> a"), Some(("> ", "a")));
        assert_eq!(match_blockquote(">a"), Some((">", "a")));
        assert_eq!(match_blockquote("   > a"), Some(("   > ", "a")));
        assert_eq!(match_blockquote(">"), Some((">", "")));
        assert_eq!(match_blockquote(">  a"), Some(("> ", " a")));
        assert_eq!(match_blockquote("    > a"), None);
        assert_eq!(match_blockquote("a"), None);
    }

    #[test]
    fn a_blockquote_prefix_strip_fires_at_most_once() {
        // Anchored and not MULTILINE, so despite re.sub's replace-all default
        // it cannot fire past offset 0.
        assert_eq!(strip_blockquote_prefix("> > a"), "a");
        assert_eq!(strip_blockquote_prefix("a\n> b"), "a\n> b");
        assert_eq!(strip_blockquote_prefix(">>a"), "a");
        assert_eq!(strip_blockquote_prefix("   >   > a"), "a");
        assert_eq!(strip_blockquote_prefix("> "), "");
        assert_eq!(strip_blockquote_prefix("    > a"), "    > a");
        assert_eq!(match_blockquote_prefix("> > a"), Some(4));
        assert_eq!(match_blockquote_prefix("   >   > a"), Some(9));
        assert_eq!(match_blockquote_prefix("no marker"), None);
    }

    #[test]
    fn a_setext_run_may_not_mix_its_character() {
        assert!(is_setext_line("==="));
        assert!(is_setext_line("---"));
        assert!(is_setext_line("=== "));
        assert!(is_setext_line("===\n"));
        assert!(is_setext_line("===\r\n"));
        assert!(is_setext_line("===\n\n"));
        // `\s*` absorbs a lone carriage return and `$` then matches at the end.
        assert!(is_setext_line("===\r"));
        assert!(!is_setext_line("=-="));
        assert!(!is_setext_line("= ="));
        assert!(!is_setext_line(""));
    }

    #[test]
    fn a_thematic_break_counts_three_markers_and_may_mix_them() {
        assert!(is_thematic_break("---"));
        assert!(is_thematic_break("***"));
        assert!(is_thematic_break("___"));
        assert!(is_thematic_break("- - -"));
        assert!(is_thematic_break("---\n"));
        // Mixing is accepted here where CommonMark rejects it; this is a port.
        assert!(is_thematic_break("-*_"));
        // The separator is Python whitespace, so a no-break space counts.
        assert!(is_thematic_break("-\u{a0}-\u{a0}-"));
        assert!(!is_thematic_break("--"));
        assert!(!is_thematic_break(" ---"));
        assert!(!is_thematic_break("---x"));
    }

    #[test]
    fn a_link_reference_needs_a_non_empty_label() {
        assert!(is_link_reference("[a]: b"));
        assert!(is_link_reference("[a]:"));
        // A backslash is not an escape to this pattern; the `]` still ends it.
        assert!(is_link_reference("[a\\]: b"));
        assert!(!is_link_reference("[]: b"));
        assert!(!is_link_reference("[a] b"));
        assert!(!is_link_reference("a]: b"));
    }

    #[test]
    fn a_tag_name_keeps_its_case_and_starts_with_a_letter() {
        assert_eq!(match_html_tag_name("<div>"), Some("div"));
        assert_eq!(match_html_tag_name("<my-tag x>"), Some("my-tag"));
        assert_eq!(match_html_tag_name("<DIV>"), Some("DIV"));
        assert_eq!(match_html_tag_name("<a"), Some("a"));
        assert_eq!(match_html_tag_name("<1div>"), None);
        assert_eq!(match_html_tag_name("< div>"), None);
        assert_eq!(match_html_tag_name("div"), None);
    }

    #[test]
    fn an_html_block_opener_rejects_what_closes_on_its_own_line() {
        assert_eq!(match_opening_html_block("<div>").as_deref(), Some("div"));
        assert_eq!(
            match_opening_html_block("  <div>  ").as_deref(),
            Some("div")
        );
        // No closing bracket is required: the pattern reads a name, not a tag.
        assert_eq!(match_opening_html_block("<div").as_deref(), Some("div"));
        assert_eq!(match_opening_html_block("<div>x</div>"), None);
        assert_eq!(match_opening_html_block("<br/>"), None);
        assert_eq!(match_opening_html_block("<!-- c -->"), None);
        assert_eq!(match_opening_html_block("</div>"), None);
        assert_eq!(match_opening_html_block("<?php"), None);
        assert_eq!(match_opening_html_block("<![CDATA["), None);
        assert_eq!(match_opening_html_block("<!DOCTYPE html>"), None);
        // Both lowercasings have to happen, in either direction of mismatch.
        assert_eq!(match_opening_html_block("<DIV>x</div>"), None);
        assert_eq!(match_opening_html_block("<div>x</DIV>"), None);
    }

    #[test]
    fn a_literal_terminator_is_reported_only_while_it_is_still_open() {
        assert_eq!(
            match_opening_html_literal_terminator("<!-- open"),
            Some("-->")
        );
        assert_eq!(
            match_opening_html_literal_terminator("  <!-- open"),
            Some("-->")
        );
        assert_eq!(match_opening_html_literal_terminator("<?php"), Some("?>"));
        assert_eq!(
            match_opening_html_literal_terminator("<![CDATA[x"),
            Some("]]>")
        );
        assert_eq!(
            match_opening_html_literal_terminator("<!DOCTYPE html"),
            Some(">")
        );
        assert_eq!(
            match_opening_html_literal_terminator("<!-- closed -->"),
            None
        );
        assert_eq!(match_opening_html_literal_terminator("<?php ?>"), None);
        assert_eq!(match_opening_html_literal_terminator("<![CDATA[x]]>"), None);
        assert_eq!(
            match_opening_html_literal_terminator("<!DOCTYPE html>"),
            None
        );
        // The third character must be ASCII uppercase, so a lowercase one fails.
        assert_eq!(match_opening_html_literal_terminator("<!x"), None);
        assert_eq!(match_opening_html_literal_terminator("<!"), None);
    }

    #[test]
    fn a_gfm_alert_ends_at_the_end_or_before_one_trailing_newline() {
        assert!(is_gfm_alert("[!NOTE]"));
        assert!(is_gfm_alert("[!NOTE]+"));
        assert!(is_gfm_alert("[!NOTE]-"));
        assert!(is_gfm_alert("[!NOTE]\n"));
        assert!(is_gfm_alert("[!N0-T_E]"));
        // Python's `$` accepts one trailing `\n` and only `\n`.
        assert!(!is_gfm_alert("[!NOTE]\r"));
        assert!(!is_gfm_alert("[!NOTE]\n\n"));
        assert!(!is_gfm_alert("[!note]"));
        assert!(!is_gfm_alert("[!]"));
        assert!(!is_gfm_alert("[NOTE]"));
        assert!(!is_gfm_alert("[!NOTE]x"));
    }

    #[test]
    fn the_raw_html_tags_are_the_four_that_hold_literal_text() {
        for name in ["pre", "script", "style", "textarea"] {
            assert!(is_raw_html_tag(name));
        }
        assert!(!is_raw_html_tag("div"));
        assert!(!is_raw_html_tag("PRE"));
    }
}
