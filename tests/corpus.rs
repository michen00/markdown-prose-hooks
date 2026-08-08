//! Run the language-neutral conformance corpus against the Rust implementation.
//!
//! The same directory `tests/test_corpus.py` runs. These tests hold no
//! expectations of their own: each case carries its input, its expected output,
//! and the reasoning for both. The format is documented in `corpus/README.md`.
//!
//! Rust's built-in harness has no parameterization, so one test per case is not
//! available without a build script. The other option is taken here: a handful
//! of tests, each iterating every case and collecting *all* failures before
//! reporting them together. A bare `assert!` inside the loop would stop at the
//! first failing case and hide the rest, which is exactly backwards for a
//! conformance suite where the useful signal is how many cases a change broke.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

struct Case {
    slug: String,
    name: String,
    why: String,
    paragraphs_unwrapped: usize,
    line_breaks_removed: usize,
    input: String,
    expected: String,
}

fn corpus_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("corpus")
        .join("cases")
}

/// Read a file with no newline translation.
///
/// `fs::read_to_string` performs none, unlike Python's default text mode, which
/// rewrites CRLF to LF on the way in and would turn a real regression into a
/// pass. `tests/test_corpus.py` reaches the same behavior with `newline=''`.
fn read_verbatim(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_else(|err| panic!("{}: {err}", path.display()))
}

/// Return the `key: value` pairs in a case's metadata file.
///
/// `str::lines` splits on `\n` and drops a trailing `\r`, where Python's
/// `str.splitlines` breaks on ten boundaries. The divergence is real and is
/// confined here on purpose: metadata is ASCII keys and prose values, and the
/// bytes that matter — `input.md` and `expected.md` — are never split at all.
fn parse_meta(text: &str) -> BTreeMap<String, String> {
    let mut meta = BTreeMap::new();
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Some((key, value)) = trimmed.split_once(':') {
            meta.insert(key.trim().to_owned(), value.trim().to_owned());
        }
    }
    meta
}

fn load_corpus() -> Vec<Case> {
    let root = corpus_root();
    let mut directories: Vec<PathBuf> = fs::read_dir(&root)
        .unwrap_or_else(|err| panic!("{}: {err}", root.display()))
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| path.is_dir())
        .collect();
    // `read_dir` yields in whatever order the filesystem gives, so the cases
    // are sorted to make a failure list comparable between runs and machines.
    directories.sort();
    directories.into_iter().map(load_case).collect()
}

fn load_case(directory: PathBuf) -> Case {
    let meta = parse_meta(&read_verbatim(&directory.join("case.txt")));
    let get = |key: &str| {
        meta.get(key)
            .unwrap_or_else(|| panic!("{}: missing key {key}", directory.display()))
            .clone()
    };
    let count = |key: &str| {
        get(key)
            .parse()
            .unwrap_or_else(|err| panic!("{}: {key}: {err}", directory.display()))
    };
    Case {
        slug: directory
            .file_name()
            .expect("a case directory has a final component")
            .to_string_lossy()
            .into_owned(),
        name: get("name"),
        why: get("why"),
        paragraphs_unwrapped: count("paragraphs_unwrapped"),
        line_breaks_removed: count("line_breaks_removed"),
        input: read_verbatim(&directory.join("input.md")),
        expected: read_verbatim(&directory.join("expected.md")),
    }
}

fn report(kind: &str, total: usize, failures: &[String]) {
    assert!(
        failures.is_empty(),
        "{} of {total} cases failed {kind}:\n\n{}",
        failures.len(),
        failures.join("\n\n"),
    );
}

#[test]
fn the_corpus_is_not_empty() {
    // Iterating an empty list passes vacuously and reports success, so the
    // suite has to assert the corpus was found at all.
    let cases = load_corpus();
    assert!(
        !cases.is_empty(),
        "no cases under {}",
        corpus_root().display()
    );
}

#[test]
fn corpus_case_output() {
    let cases = load_corpus();
    let mut failures = Vec::new();
    for case in &cases {
        let result = markdown_prose_hooks::unwrap_markdown_prose(&case.input);
        if result.content != case.expected {
            // `{:?}` and not `{}`: the difference between a case that passes and
            // one that does not is often a trailing space or a `\r`, and printing
            // those raw shows two identical-looking blocks.
            failures.push(format!(
                "[{}] {} — {}\n  expected: {:?}\n  actual:   {:?}",
                case.slug, case.name, case.why, case.expected, result.content,
            ));
        }
    }
    report("output", cases.len(), &failures);
}

#[test]
fn corpus_case_counts() {
    // Split from the output assertion on purpose: identical content with a
    // wrong count means the reporting drifted from the rewriting, and that is
    // what `--check` and `--json` consumers actually read.
    let cases = load_corpus();
    let mut failures = Vec::new();
    for case in &cases {
        let result = markdown_prose_hooks::unwrap_markdown_prose(&case.input);
        if result.paragraphs_unwrapped != case.paragraphs_unwrapped
            || result.line_breaks_removed != case.line_breaks_removed
        {
            failures.push(format!(
                "[{}] {}\n  expected: {} paragraphs, {} breaks\n  actual:   {} paragraphs, {} breaks",
                case.slug,
                case.name,
                case.paragraphs_unwrapped,
                case.line_breaks_removed,
                result.paragraphs_unwrapped,
                result.line_breaks_removed,
            ));
        }
    }
    report("counts", cases.len(), &failures);
}

#[test]
fn corpus_case_is_idempotent() {
    // Free for every case the corpus gains, and it is the property a formatter
    // most needs: a second pre-commit run must not keep rewriting the file.
    let cases = load_corpus();
    let mut failures = Vec::new();
    for case in &cases {
        let once = markdown_prose_hooks::unwrap_markdown_prose(&case.input).content;
        let twice = markdown_prose_hooks::unwrap_markdown_prose(&once).content;
        if once != twice {
            failures.push(format!("[{}] {}", case.slug, case.name));
        }
    }
    report("idempotency", cases.len(), &failures);
}
