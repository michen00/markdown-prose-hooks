//! `.unwrapignore` patterns and `--exclude` globs.
//!
//! A deliberate subset of gitignore rather than a reimplementation of it. Only a
//! leading slash anchors; gitignore also anchors any pattern holding a
//! non-trailing slash, which is two rules for one question, and full fidelity
//! across two hand-written implementations is a parity liability rather than a
//! feature.
//!
//! Every expected value in the tests below came from running the Python, and
//! `corpus/cli/` judges the whole of it.

use crate::scan::py_splitlines_keepends;

/// `_IGNORE_FILE`: read from the working directory, never from an install root.
///
/// The working directory is the repository in every channel that matters:
/// `pre-commit` runs a hook there, the composite action runs there, and a person
/// runs the CLI there.
pub const IGNORE_FILE_NAME: &str = ".unwrapignore";

/// One path segment of a pattern.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Segment {
    /// `**`, the only segment that crosses separators.
    DoubleStar,
    /// Anything else, with its star runs already collapsed.
    Literal(Vec<char>),
}

/// One parsed line of a `.unwrapignore` file, or one `--exclude` glob.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pattern {
    negated: bool,
    dir_only: bool,
    anchored: bool,
    segments: Vec<Segment>,
}

/// `_collapse_segment`: read one segment as `**`, or collapse its star runs.
///
/// A segment made of nothing but stars is `**` however many were typed, which
/// keeps `***` from being a third thing nobody can predict. Stars adjacent to
/// other characters cannot cross a separator whatever their number, so a run
/// inside a segment collapses to one — `a**b` and `a*b` are the same pattern,
/// and writing them differently must not make them behave differently.
fn collapse_segment(segment: &str) -> Segment {
    if !segment.is_empty() && segment.chars().all(|c| c == '*') {
        return if segment.chars().count() > 1 {
            Segment::DoubleStar
        } else {
            Segment::Literal(vec!['*'])
        };
    }
    let mut collapsed: Vec<char> = Vec::new();
    for c in segment.chars() {
        if c != '*' || collapsed.last() != Some(&'*') {
            collapsed.push(c);
        }
    }
    Segment::Literal(collapsed)
}

/// `_parse_ignore_pattern`: the pattern a line describes, or none.
#[must_use]
pub fn parse(line: &str) -> Option<Pattern> {
    // Trailing whitespace goes, because it is almost always an editing accident
    // and a pattern that silently depends on an invisible character is a bad
    // trade. `\ ` keeps a genuinely intended one.
    let mut line = line;
    while (line.ends_with(' ') || line.ends_with('\t')) && !line.ends_with("\\ ") {
        line = &line[..line.len() - 1];
    }
    if line.is_empty() || line.starts_with('#') {
        return None;
    }
    let negated = line.starts_with('!');
    if negated {
        line = &line[1..];
    }
    // `\#` and `\!` keep a leading character that would otherwise be a comment
    // marker or a negation.
    let unescaped = line
        .replace("\\#", "#")
        .replace("\\!", "!")
        .replace("\\ ", " ");
    let mut rest = unescaped.as_str();
    let dir_only = rest.ends_with('/');
    if dir_only {
        rest = &rest[..rest.len() - 1];
    }
    let anchored = rest.starts_with('/');
    if anchored {
        rest = &rest[1..];
    }
    let segments: Vec<Segment> = rest
        .split('/')
        .filter(|segment| !segment.is_empty() && *segment != ".")
        .map(collapse_segment)
        .collect();
    if segments.is_empty() {
        return None;
    }
    Some(Pattern {
        negated,
        dir_only,
        anchored,
        segments,
    })
}

/// Every pattern in force, in the order that decides a tie.
#[derive(Debug, Clone, Default)]
pub struct IgnoreRules {
    patterns: Vec<Pattern>,
}

impl IgnoreRules {
    /// Build the rules from an ignore file's text and the `--exclude` globs.
    ///
    /// The file's lines come first and the globs after, which is what makes
    /// `--exclude` able to narrow what the file widened.
    #[must_use]
    pub fn new<'a, I: IntoIterator<Item = &'a str>>(
        ignore_text: Option<&'a str>,
        excludes: I,
    ) -> Self {
        let lines: Vec<&str> = ignore_text
            .map(|text| {
                py_splitlines_keepends(text)
                    .into_iter()
                    .map(|line| crate::scan::split_eol(line).0)
                    .collect()
            })
            .unwrap_or_default();
        Self {
            patterns: lines
                .into_iter()
                .chain(excludes)
                .filter_map(parse)
                .collect(),
        }
    }

    /// Is `raw_path` out of scope?
    ///
    /// Last match wins, so a broad pattern can be narrowed by a later negation.
    /// Without that a pattern could only ever be widened, and the file would
    /// have to be written in an order nobody expects.
    #[must_use]
    pub fn excludes(&self, raw_path: &str) -> bool {
        let components = split_components(raw_path);
        let mut excluded = false;
        for pattern in &self.patterns {
            if pattern_matches(pattern, &components) {
                excluded = !pattern.negated;
            }
        }
        excluded
    }

    /// How many patterns are in force.
    #[must_use]
    pub fn len(&self) -> usize {
        self.patterns.len()
    }

    /// Whether no pattern is in force, in which case nothing is excluded.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.patterns.is_empty()
    }
}

/// `_split_components`: a candidate path split up, with `.` and `..` resolved.
///
/// Never routed through a path type first: `Path('a/../b.md').as_posix()` keeps
/// the `..`, so a pattern spelled like the resolved path would not match it.
///
/// Candidate separators are normalized on Windows and nowhere else, so a pattern
/// stays one spelling across platforms while a path written the local way still
/// matches. A backslash in a *pattern* is an escape everywhere, never a
/// separator, which is why this governs only the candidate side.
#[must_use]
pub fn split_components(raw: &str) -> Vec<&str> {
    let normalized: Vec<&str> = if cfg!(windows) {
        raw.split(['\\', '/']).collect()
    } else {
        raw.split('/').collect()
    };
    let mut components: Vec<&str> = Vec::new();
    for component in normalized {
        match component {
            "" | "." => {}
            ".." => {
                components.pop();
            }
            _ => components.push(component),
        }
    }
    components
}

/// `_match_glob_segment`: one path component against one glob segment.
///
/// The classic single-saved-star backtracking walk. The wildcard branch is
/// tested **before** the literal branch, and that order is load-bearing rather
/// than stylistic: with the literal branch first, a text character that happens
/// to be `*` matches the pattern's `*` as a literal, no backtrack point is
/// recorded, and `*x.md` stops matching a file genuinely named `*ax.md`.
///
/// Characters and not bytes, because `?` is a counted quantifier of exactly one
/// and Python counts characters.
fn match_glob_segment(pattern: &[char], text: &[char]) -> bool {
    let mut star_pattern: Option<usize> = None;
    let mut star_text = 0;
    let mut p = 0;
    let mut t = 0;
    while t < text.len() {
        if p < pattern.len() && pattern[p] == '*' {
            star_pattern = Some(p);
            star_text = t;
            p += 1;
        } else if p < pattern.len() && (pattern[p] == '?' || pattern[p] == text[t]) {
            p += 1;
            t += 1;
        } else if let Some(saved) = star_pattern {
            star_text += 1;
            t = star_text;
            p = saved + 1;
        } else {
            return false;
        }
    }
    pattern[p..].iter().all(|c| *c == '*')
}

/// `_match_segments`: do these segments match these components exactly?
fn match_segments(segments: &[Segment], components: &[&str]) -> bool {
    let Some((head, tail)) = segments.split_first() else {
        return components.is_empty();
    };
    match head {
        // Zero or more components, stated once and applied everywhere rather
        // than one rule for a leading `**`, another for a trailing one, and a
        // third in the middle. The zero case is the one a naive implementation
        // misses: `a/**/b.md` has to match `a/b.md`.
        Segment::DoubleStar => {
            (0..=components.len()).any(|index| match_segments(tail, &components[index..]))
        }
        Segment::Literal(glob) => {
            let Some((first, rest)) = components.split_first() else {
                return false;
            };
            let text: Vec<char> = first.chars().collect();
            match_glob_segment(glob, &text) && match_segments(tail, rest)
        }
    }
}

/// `_pattern_matches`: does this pattern select this candidate?
fn pattern_matches(pattern: &Pattern, components: &[&str]) -> bool {
    let starts: Vec<usize> = if pattern.anchored {
        vec![0]
    } else {
        (0..components.len()).collect()
    };
    for start in starts {
        let rest = &components[start..];
        if !pattern.dir_only {
            if match_segments(&pattern.segments, rest) {
                return true;
            }
            continue;
        }
        // A trailing slash restricts to directories, and the tool is handed
        // files, so it matches when a *proper* prefix does — `fixtures/` covers
        // `fixtures/wrapped.md` and not a file named `fixtures`.
        if (1..rest.len()).any(|length| match_segments(&pattern.segments, &rest[..length])) {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rules(lines: &[&str]) -> IgnoreRules {
        IgnoreRules::new(None, lines.iter().copied())
    }

    #[test]
    fn a_leading_slash_anchors_and_nothing_else_does() {
        assert!(rules(&["/top.md"]).excludes("top.md"));
        assert!(!rules(&["/top.md"]).excludes("sub/top.md"));
        assert!(rules(&["top.md"]).excludes("sub/top.md"));
        // A multi-segment pattern is still unanchored, and the whole run of
        // segments has to match, ending at the candidate's last component.
        assert!(rules(&["docs/note.md"]).excludes("docs/note.md"));
        assert!(rules(&["docs/note.md"]).excludes("deep/docs/note.md"));
        assert!(!rules(&["docs"]).excludes("deep/docs/note.md"));
    }

    #[test]
    fn a_double_star_crosses_separators_including_zero_of_them() {
        assert!(rules(&["a/**/b.md"]).excludes("a/b.md"));
        assert!(rules(&["a/**/b.md"]).excludes("a/m/n/b.md"));
        assert!(!rules(&["a/**/b.md"]).excludes("other/b.md"));
        // Any run of stars alone is `**`, so `***` is not a third thing.
        assert!(rules(&["a/***/b.md"]).excludes("a/b.md"));
    }

    #[test]
    fn a_single_star_stays_inside_one_component() {
        assert!(rules(&["*.md"]).excludes("a.md"));
        assert!(rules(&["*.md"]).excludes("sub/a.md"));
        assert!(!rules(&["a*b"]).excludes("a/b"));
        // Collapsed: `a**b` inside a segment is `a*b`, not a separator crosser.
        assert!(!rules(&["a**b"]).excludes("a/b"));
        assert!(rules(&["a**b"]).excludes("axxb"));
    }

    #[test]
    fn a_literal_star_in_a_filename_still_matches() {
        // The wildcard branch has to be tried before the literal branch, or the
        // text's own `*` is consumed as a literal and no backtrack is recorded.
        assert!(rules(&["*x.md"]).excludes("*ax.md"));
        assert!(rules(&["*x.md"]).excludes("*x.md"));
    }

    #[test]
    fn a_question_mark_is_exactly_one_character() {
        assert!(rules(&["a?.md"]).excludes("ab.md"));
        assert!(!rules(&["a?.md"]).excludes("ab c.md"));
        // One character, not one byte.
        assert!(rules(&["a?.md"]).excludes("a\u{e9}.md"));
    }

    #[test]
    fn a_trailing_slash_restricts_to_a_proper_prefix() {
        assert!(rules(&["fixtures/"]).excludes("fixtures/wrapped.md"));
        assert!(!rules(&["fixtures/"]).excludes("fixtures"));
        assert!(rules(&["fixtures/"]).excludes("a/fixtures/b/c.md"));
    }

    #[test]
    fn the_last_matching_pattern_wins() {
        assert!(!rules(&["*.md", "!keep.md"]).excludes("keep.md"));
        assert!(rules(&["!keep.md", "*.md"]).excludes("keep.md"));
        assert!(rules(&["*.md", "!keep.md"]).excludes("a.md"));
    }

    #[test]
    fn comments_and_blank_lines_describe_no_pattern() {
        assert!(parse("").is_none());
        assert!(parse("   ").is_none());
        assert!(parse("# a comment").is_none());
        assert!(parse("/").is_none());
        assert!(parse(".").is_none());
        // An escaped marker is a pattern, not a comment or a negation.
        assert!(rules(&["\\#a.md"]).excludes("#a.md"));
        assert!(rules(&["\\!a.md"]).excludes("!a.md"));
    }

    #[test]
    fn trailing_whitespace_goes_unless_it_was_escaped() {
        assert!(rules(&["a.md   "]).excludes("a.md"));
        assert!(rules(&["a.md\\ "]).excludes("a.md "));
        assert!(!rules(&["a.md\\ "]).excludes("a.md"));
    }

    #[test]
    fn a_candidate_resolves_its_dot_segments_and_a_pattern_does_not() {
        assert_eq!(split_components("a/../b.md"), ["b.md"]);
        assert_eq!(split_components("./a.md"), ["a.md"]);
        assert_eq!(split_components("a//b.md"), ["a", "b.md"]);
        assert_eq!(split_components("../a.md"), ["a.md"]);
        assert!(split_components("").is_empty());
        assert!(rules(&["b.md"]).excludes("a/../b.md"));
    }

    #[test]
    fn no_patterns_excludes_nothing() {
        let empty = IgnoreRules::default();
        assert!(empty.is_empty());
        assert!(!empty.excludes("anything.md"));
    }

    #[test]
    fn an_ignore_file_is_split_on_the_three_boundaries() {
        let rules = IgnoreRules::new(Some("a.md\r\nb.md\rc.md\n"), std::iter::empty());
        assert_eq!(rules.len(), 3);
        assert!(rules.excludes("a.md"));
        assert!(rules.excludes("b.md"));
        assert!(rules.excludes("c.md"));
    }
}
