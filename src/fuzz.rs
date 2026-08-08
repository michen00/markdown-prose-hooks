//! Document generator for the differential fuzzer.
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
    use crate::scan::{is_list_line, match_list_marker};

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
        assert!(has(|f| match_list_marker(f).is_some()), "no list marker");
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
