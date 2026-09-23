//! Document generator for the differential fuzzer.
//!
//! Every cast from the random source narrows a `u64` to a `usize` in order
//! to index one of the fixed arrays below. The value is already bounded by
//! that array's length, which is a handful of entries, so the truncation the
//! lint warns about on a 32-bit target cannot occur. Allowed for the module
//! rather than at five call sites that all say the same thing.
#![allow(clippy::cast_possible_truncation)]
//!
//! Enumerated cases prove the two implementations agree about what was
//! anticipated. Only a fuzzer speaks to what was not, and shipping a second
//! implementation means shipping the claim that they agree.
//!
//! **A seed does not name a stable document.** Any change to the bank, to the
//! draw order, or to a denominator renames every seed, because the fragment
//! index is drawn modulo the bank's length. The fixed seed range CI runs is a
//! regression net only while the generator is frozen; it is not a corpus, and a
//! divergence worth keeping is promoted into `corpus/` rather than left as a
//! seed number.

/// xorshift64\*, so the generator is deterministic without a dependency.
pub struct Rng {
    state: u64,
}

impl Rng {
    /// Seed the generator. Zero is a fixed point of xorshift, so it is mapped.
    #[must_use]
    pub fn new(seed: u64) -> Self {
        Self {
            state: if seed == 0 {
                0x9E37_79B9_7F4A_7C15
            } else {
                seed
            },
        }
    }

    /// The next raw value.
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    /// A value below `bound`, which must not be zero.
    pub fn below(&mut self, bound: u64) -> u64 {
        self.next_u64() % bound
    }
}

/// The lines a generated document is built from.
///
/// Chosen so the generator can reach every hazard the port has a comment about.
/// A bank that cannot reach a hazard is worse than no bank, because it reports
/// coverage it does not have — which is what `the_bank_reaches_its_hazards`
/// below exists to check.
pub const FRAGMENTS: &[&str] = &[
    // Ordinary prose, and prose carrying the four C0 separators that Python
    // calls whitespace and Rust does not. The trailing one is the fragment that
    // discriminates: a separator in the middle of a line survives either
    // reading, and only one at an edge tells `str.strip` from `str::trim`.
    // Mutation testing found that gap; the mid-line fragment alone did not.
    "ordinary prose that wraps",
    "a second prose line",
    "prose\u{1c}with\u{1d}four\u{1e}C0\u{1f}separators",
    "prose ending in a separator\u{1c}",
    "prose ending in a unit separator\u{1f}",
    "",
    "   ",
    // Fence openers of both characters and several lengths, indented and not.
    "```",
    "````",
    "~~~",
    "~~~~~",
    "```rust",
    "   ```",
    "    ```",
    "``` ```",
    // Blockquote prefixes at several depths, with and without the space.
    "> quoted prose",
    ">no space after the marker",
    "> > deeper prose",
    ">>> deepest",
    ">",
    "   > indented marker",
    ">     indented code inside a quote",
    "> ```",
    "> <!-- quoted comment",
    "> <div>",
    "> | a | b |",
    // The fence and the HTML block two levels down. A one-level opener reads the
    // same under a one-level peel and a whole-stack strip, so only a deeper one
    // tells the two apart.
    ">> ```",
    ">> <div>",
    // Each of those with a line quoted less deeply under it and a live marker
    // below. Drawn whole, because assembling it takes three consecutive draws,
    // which no seed range this size reaches. A container that outlives its quote
    // reads that marker as content and joins the marked break.
    ">> ```\n> one level up\n>> <!-- unwrap-ignore -->",
    ">> <div>\n> one level up\n>> <!-- unwrap-ignore -->",
    // The same shape opened by a literal, which a test of its own arms.
    ">> <?php\n> one level up\n>> <!-- unwrap-ignore -->",
    // A quoted speaker turn, which opens a row of its own rather than
    // continuing the quoted paragraph above it. Also a mutation-testing find:
    // an unquoted speaker line cannot reach that branch.
    "> Alex: a quoted utterance",
    "> Jordan: another quoted utterance",
    // List markers: bullets, both ordered spellings, and non-ASCII digits,
    // which are markers to no renderer and must not open a list.
    "- bullet item",
    "* star item",
    "+ plus item",
    "1. ordered item",
    "12) ordered item",
    "\u{663}. item",
    "\u{967}\u{968}) item",
    "  continuation at the content column",
    "    deeper continuation",
    // Alphabetic sub-enumerators, which CommonMark does not call list markers
    // and which are still load-bearing layout.
    "a. lettered subitem",
    "b) lettered subitem",
    // Label rows in all four shapes.
    "**Label:** value",
    "**Label**: value",
    "**Whole line bold**",
    "Alex: an utterance",
    "Alex Jordan Morgan Casey: four words",
    "Alex Jordan Morgan Casey Drew: five words",
    "[a stage direction]",
    "[a stage direction].",
    // Tables, and pipes hidden inside code spans of one, two and three ticks.
    "| a | b |",
    "| - | - |",
    "a `x | y` span",
    "a ``x | y`` span",
    "a ```x | y``` span",
    "an `unterminated run",
    "a `a``` closing run",
    // Hard breaks, both spellings.
    "a hard break  ",
    "a hard break\\",
    // HTML in every shape the loop distinguishes.
    "<div>",
    "</div>",
    "<div>closed on its own line</div>",
    "<br/>",
    "<pre>",
    "</pre>",
    "<!-- an open comment",
    "-->",
    "<!-- a closed comment -->",
    // The ignore directive in the spellings that matter: canonical, tight, and
    // quoted, plus two near misses the exact match has to reject. In the bank
    // rather than only in the corpus because what the corpus cannot reach is a
    // disagreement about *where* the directive is spent, which needs a document
    // nobody wrote.
    "<!-- unwrap-ignore -->",
    "<!--unwrap-ignore-->",
    "> <!-- unwrap-ignore -->",
    "<!-- unwrap-ignore for now -->",
    "unwrap-ignore",
    // The same directive written across a comment, a marker for the same reason
    // as the one-line form: the whole content is the word. Each carries its own
    // newlines, so one draw puts the form in a document whole. The blank-line
    // form is here because a blank line ends most runs but not a comment, the
    // quoted one because the container path accumulates separately, and the
    // last is a near miss the exact match must reject.
    "<!--\nunwrap-ignore\n-->",
    "<!--\n\nunwrap-ignore\n\n-->",
    "<!--\r\nunwrap-ignore\r\n-->",
    "> <!--\n> unwrap-ignore\n> -->",
    "<!--\nunwrap-ignore\nfor now\n-->",
    // The pieces those five are made of, drawn independently so the generator
    // assembles multi-line comments of its own. Without them, every multi-line
    // directive a seed emits would be one of the five verbatim. A bare closer
    // and a bare marker are already in the bank. Independent draws build shapes
    // nobody wrote down, such as a marker sharing a delimiter line, a run opened
    // inside a quote and closed outside it, a depth that changes mid-comment and
    // a tail after the delimiter. `the_generator_assembles_a_multiline_directive`
    // measures that they do.
    "<!--",
    "<!--unwrap-ignore",
    "unwrap-ignore-->",
    "--> and then some prose",
    "> <!--",
    "> -->",
    "> unwrap-ignore",
    ">> <!--",
    ">> -->",
    ">> unwrap-ignore",
    "unwrap-ignore-start",
    "unwrap-ignore-end",
    // The region markers, seeded unpaired on purpose: the generator picks
    // fragments independently, so most documents carrying one of these carry it
    // without its partner. An unclosed region exempting the tail of a file is
    // exactly the state the two implementations have to agree about, and a
    // paired-only bank would never build it.
    "<!-- unwrap-ignore-start -->",
    "<!-- unwrap-ignore-end -->",
    "<!--unwrap-ignore-start-->",
    "> <!-- unwrap-ignore-end -->",
    "  <!-- unwrap-ignore-end -->",
    // Both of those written across a comment, unpaired for the reason above.
    // Mixed with the one-line form, a region opens one way and closes the other,
    // which an implementation handling only one form would leave open.
    "<!--\nunwrap-ignore-start\n-->",
    "<!--\nunwrap-ignore-end\n-->",
    "<?php",
    "?>",
    "<![CDATA[",
    "]]>",
    "<!DOCTYPE html",
    "<!DOCTYPE html>",
    // Front matter openers and closers, with and without a byte order mark.
    "---",
    "\u{feff}---",
    "...",
    "title: a value",
    // Structural lines the prose branch has to decline.
    "# a heading",
    "===",
    "- - -",
    "***",
    "[label]: https://example.com",
    "[!NOTE]",
    "[![badge](s.svg)][ref]",
    "[another](https://example.com)",
    ":: an admonition",
    "!!! note",
    "{% raw %}",
    "{{ template }}",
    // Speaker headings at the `{0,39}` boundary, and a timestamped one whose
    // digits are the counted quantifier the specification narrowed to ASCII.
    concat!(
        "A",
        "eeeeeeeeee",
        "eeeeeeeeee",
        "eeeeeeeeee",
        "eeeeeeeee",
        ":"
    ),
    concat!(
        "A",
        "eeeeeeeeee",
        "eeeeeeeeee",
        "eeeeeeeeee",
        "eeeeeeeeee",
        ":"
    ),
    "MC 0:15",
    "MC \u{660}:\u{661}\u{665}",
    "JR 12:34",
];

/// Build the document for `seed`.
///
/// Every draw is unconditional, so the number of values consumed depends only
/// on the line count — which is itself the first draw. That keeps a seed's
/// document stable under edits to *this function's* branches, though not under
/// edits to the bank.
#[must_use]
pub fn document(seed: u64) -> String {
    let mut rng = Rng::new(seed);
    let line_count = 1 + rng.below(24);
    let mut out = String::new();
    for _ in 0..line_count {
        let index = rng.below(FRAGMENTS.len() as u64) as usize;
        out.push_str(FRAGMENTS[index]);
        // Mixed line endings within one document, which is where the CRLF
        // handling actually gets tested.
        match rng.below(16) {
            0 => out.push_str("\r\n"),
            1 => out.push('\r'),
            _ => out.push('\n'),
        }
    }
    // A document that does not end in a newline is its own case.
    if rng.below(8) == 0 {
        while out.ends_with(['\n', '\r']) {
            out.pop();
        }
    }
    out
}

/// A whole run: the tree to lay down, and the arguments to run in it.
///
/// [`document`] alone reaches the transform. It cannot reach what surrounds the
/// transform — several files at once, an ignore file, `--files-from`, and the
/// interaction between them, which is where the CLI corpus has cases and the
/// generator had nothing.
pub struct Scenario {
    /// Relative path to contents. Parent directories are the caller's to create.
    pub files: Vec<(String, String)>,
    /// The arguments after the program name.
    pub argv: Vec<String>,
}

/// Paths worth generating: nested, not nested, and one the patterns spare.
const NAMES: [&str; 4] = ["note.md", "keep.md", "sub/nested.md", "docs/deep.md"];

/// Ignore-file lines, including the shapes whose interaction decides an answer.
const PATTERNS: [&str; 10] = [
    "*.md",
    "!keep.md",
    "keep.md",
    "sub/",
    "docs/deep.md",
    "/note.md",
    "**/nested.md",
    "# a comment",
    "no-such-file.md",
    "*.m?",
];

/// Build the whole scenario for `seed`.
///
/// Drawn from a stream of its own, so a scenario and a document with the same
/// seed number share nothing. Every draw is unconditional for the reason
/// [`document`] gives.
#[must_use]
pub fn scenario(seed: u64) -> Scenario {
    let mut rng = Rng::new(seed ^ 0x5DEE_CE66_D000_0001);
    let file_count = 1 + rng.below(NAMES.len() as u64 - 1) as usize;
    // Taken in order so the names are distinct without a shuffle, which would
    // make the draw count depend on values.
    let mut files: Vec<(String, String)> = NAMES[..file_count]
        .iter()
        .map(|name| ((*name).to_owned(), document(rng.next_u64())))
        .collect();

    let pattern_count = rng.below(3) as usize;
    let patterns: Vec<&str> = (0..pattern_count)
        .map(|_| PATTERNS[rng.below(PATTERNS.len() as u64) as usize])
        .collect();
    if !patterns.is_empty() {
        files.push((
            ".unwrapignore".to_owned(),
            format!("{}\n", patterns.join("\n")),
        ));
    }

    let mut argv: Vec<String> = Vec::new();
    if rng.below(2) == 0 {
        argv.push("--write".to_owned());
    }
    if rng.below(2) == 0 {
        argv.push("--json".to_owned());
    }
    if rng.below(3) == 0 {
        argv.push("--fail-on-change".to_owned());
    }
    let exclude = rng.below(4);
    if exclude < PATTERNS.len() as u64 {
        argv.push("--exclude".to_owned());
        argv.push(PATTERNS[exclude as usize].to_owned());
    }
    // Named arguments, a `--files-from` list, or both. All three reach the same
    // filter, and that they do is the thing worth checking.
    let names: Vec<String> = files
        .iter()
        .map(|(name, _)| name.clone())
        .filter(|name| name != ".unwrapignore")
        .collect();
    match rng.below(3) {
        0 => argv.extend(names),
        1 => {
            files.push(("list.txt".to_owned(), format!("{}\n", names.join("\n"))));
            argv.push("--files-from".to_owned());
            argv.push("list.txt".to_owned());
        }
        _ => {
            files.push(("list.txt".to_owned(), format!("{}\n", names.join("\n"))));
            argv.push("--files-from".to_owned());
            argv.push("list.txt".to_owned());
            argv.extend(names);
        }
    }
    Scenario { files, argv }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::label::is_speaker_prefix;
    use crate::scan::{
        COMMENT_CLOSE, COMMENT_OPEN, IGNORE_BLOCK_END, IGNORE_BLOCK_START, IGNORE_DIRECTIVE,
        is_ignore_block_end, is_ignore_block_start, is_ignore_directive, is_list_line,
        match_list_marker, match_opening_fence, match_opening_html_block,
        match_opening_html_literal_terminator, py_trim, split_blockquote_stack,
    };

    /// What a fragment holds between its comment delimiters, when it spans lines.
    ///
    /// Deliberately not the implementation's reader, which would report coverage
    /// whenever the code under test agreed with itself.
    fn multiline_comment_content(fragment: &str) -> Option<&str> {
        if !fragment.contains('\n') {
            return None;
        }
        let inner = fragment
            .strip_prefix(COMMENT_OPEN)?
            .strip_suffix(COMMENT_CLOSE)?;
        Some(py_trim(inner))
    }

    #[test]
    fn the_bank_reaches_its_hazards() {
        let has = |predicate: fn(&str) -> bool| FRAGMENTS.iter().any(|f| predicate(f));
        assert!(has(|f| f.contains('\u{1c}')), "no C0 separator");
        assert!(has(|f| f.contains('\u{feff}')), "no byte order mark");
        assert!(has(|f| f.ends_with("  ")), "no two-space hard break");
        assert!(has(|f| f.ends_with('\\')), "no backslash hard break");
        assert!(has(|f| f.contains("```")), "no backtick fence");
        assert!(has(|f| f.contains("~~~")), "no tilde fence");
        assert!(has(|f| f.contains("<![CDATA[")), "no CDATA");
        assert!(has(|f| f.contains("<?")), "no processing instruction");
        assert!(has(|f| f.starts_with("<!DOCTYPE")), "no declaration");
        assert!(has(|f| f.contains('|')), "no table pipe");
        assert!(has(|f| f.starts_with("> ")), "no blockquote");
        assert!(has(is_speaker_prefix), "no speaker prefix");
        assert!(has(is_ignore_directive), "no ignore directive");
        assert!(has(is_ignore_block_start), "no region opener");
        assert!(has(is_ignore_block_end), "no region closer");
        // The same three written across a comment, the only shape that reaches
        // the accumulating path. The predicates above see one line at a time.
        let spans = |marker: &str| {
            FRAGMENTS
                .iter()
                .any(|f| multiline_comment_content(f) == Some(marker))
        };
        assert!(spans(IGNORE_DIRECTIVE), "no multi-line ignore directive");
        assert!(spans(IGNORE_BLOCK_START), "no multi-line region opener");
        assert!(spans(IGNORE_BLOCK_END), "no multi-line region closer");
        assert!(
            has(|f| f.starts_with("> <!--") && f.contains('\n')),
            "no quoted multi-line comment"
        );
        // A container opened two quote levels down, where the whole-stack strip
        // and a one-level peel differ. Asked as a depth, so `> > ` counts as
        // well as `>>`.
        let twice_quoted = |test: fn(&str) -> bool| {
            FRAGMENTS.iter().any(|f| {
                let (depth, inner) = split_blockquote_stack(f);
                depth >= 2 && test(inner)
            })
        };
        assert!(
            twice_quoted(|inner| match_opening_fence(inner).is_some()),
            "no twice-quoted fence opener"
        );
        assert!(
            twice_quoted(|inner| match_opening_html_block(inner).is_some()),
            "no twice-quoted HTML block opener"
        );
        // One of those with a shallower quoted line under it, the line that ends
        // the container. Asked of the fragment's own lines, since the shape is
        // in the bank whole.
        let shallower_under = |opens: fn(&str) -> bool| {
            FRAGMENTS.iter().any(|fragment| {
                let mut lines = fragment.split('\n');
                let Some(first) = lines.next() else {
                    return false;
                };
                let (depth, inner) = split_blockquote_stack(first);
                depth >= 2
                    && opens(inner)
                    && lines.any(|line| {
                        let (under, _) = split_blockquote_stack(line);
                        under > 0 && under < depth
                    })
            })
        };
        assert!(
            shallower_under(|inner| match_opening_fence(inner).is_some()
                || match_opening_html_block(inner).is_some()),
            "no twice-quoted container with a shallower line under it"
        );
        assert!(
            shallower_under(|inner| match_opening_html_literal_terminator(inner).is_some()),
            "no twice-quoted HTML literal with a shallower line under it"
        );
        assert!(has(|f| match_list_marker(f).is_some()), "no list marker");
    }

    /// Every comment run in `doc`, at the top level, holding just the directive.
    ///
    /// Searches for the delimiters rather than for fragments, so an assembled
    /// run is found the same way as one drawn whole, and the caller tells them
    /// apart. A quoted run is not counted, since one positive is enough.
    fn assembled_runs(doc: &str) -> Vec<&str> {
        let mut found = Vec::new();
        let mut from = 0;
        while let Some(offset) = doc[from..].find(COMMENT_OPEN) {
            let open = from + offset;
            let inner = open + COMMENT_OPEN.len();
            let Some(offset) = doc[inner..].find(COMMENT_CLOSE) else {
                break;
            };
            let end = inner + offset + COMMENT_CLOSE.len();
            let line_start = doc[..open].rfind(['\n', '\r']).map_or(0, |at| at + 1);
            let opens_its_line = doc[line_start..open].chars().all(|c| c == ' ');
            let closes_its_line = doc[end..].is_empty() || doc[end..].starts_with(['\n', '\r']);
            let run = &doc[open..end];
            if opens_its_line
                && closes_its_line
                && run.contains(['\n', '\r'])
                && py_trim(&doc[inner..inner + offset]) == IGNORE_DIRECTIVE
            {
                found.push(run);
            }
            from = end;
        }
        found
    }

    #[test]
    fn the_generator_assembles_a_multiline_directive() {
        // A run whose text is no fragment was assembled from separate draws,
        // which is the case the accumulating path has to survive. Counted over
        // the range `the_generator_reaches_every_fragment` uses, with a margin,
        // so a bank edit that makes assembly rare fails here.
        let mut assembled = 0;
        for seed in 1..4000 {
            let doc = document(seed);
            assembled += assembled_runs(&doc)
                .iter()
                .filter(|run| !FRAGMENTS.contains(run))
                .count();
        }
        assert!(
            assembled >= 4,
            "assembled {assembled} multi-line directives"
        );
    }

    #[test]
    fn the_bank_carries_a_non_ascii_digit_that_is_not_a_marker() {
        // The narrowing to `[0-9]` is only tested if something reaches it.
        let digits: Vec<&&str> = FRAGMENTS
            .iter()
            .filter(|f| f.chars().any(|c| c.is_numeric() && !c.is_ascii_digit()))
            .collect();
        assert!(digits.len() >= 3, "found {digits:?}");
        assert!(!is_list_line("\u{663}. item"));
        assert!(match_list_marker("\u{967}\u{968}) item").is_none());
    }

    #[test]
    fn the_speaker_boundary_pair_really_straddles_the_boundary() {
        // `[A-Z][a-zA-Z0-9_. -]{0,39}:` — 39 characters after the first is a
        // heading and 40 is not. Asserted rather than counted by eye.
        let short = FRAGMENTS
            .iter()
            .find(|f| f.starts_with("Ae") && f.len() == 41)
            .expect("no 39-character heading");
        let long = FRAGMENTS
            .iter()
            .find(|f| f.starts_with("Ae") && f.len() == 42)
            .expect("no 40-character heading");
        assert_eq!(short.matches('e').count(), 39);
        assert_eq!(long.matches('e').count(), 40);
    }

    #[test]
    fn the_generator_is_deterministic_and_never_empty() {
        for seed in 1..200 {
            assert_eq!(document(seed), document(seed));
        }
        // Zero is a fixed point of xorshift, so it has to be mapped away.
        assert_eq!(
            Rng::new(0).next_u64(),
            Rng::new(0x9E37_79B9_7F4A_7C15).next_u64()
        );
        let mut zero = Rng::new(0);
        assert_ne!(zero.next_u64(), 0);
    }

    #[test]
    fn the_generator_reaches_every_fragment() {
        // A bank entry no seed can draw is dead weight that reports coverage.
        let mut seen = vec![false; FRAGMENTS.len()];
        for seed in 1..4000 {
            let doc = document(seed);
            for (index, fragment) in FRAGMENTS.iter().enumerate() {
                if !fragment.is_empty() && doc.contains(fragment) {
                    seen[index] = true;
                }
            }
        }
        let missed: Vec<&&str> = FRAGMENTS
            .iter()
            .zip(&seen)
            .filter(|(fragment, hit)| !**hit && !fragment.is_empty())
            .map(|(fragment, _)| fragment)
            .collect();
        assert!(missed.is_empty(), "never generated: {missed:?}");
    }
}
