//! Differential fuzzer: one generated document, one argv, two binaries.
//!
//! Enumerated cases prove the implementations agree about what was anticipated.
//! Only this speaks to what was not, and shipping a second implementation means
//! shipping the claim that they agree.
//!
//! An example rather than a test, because it runs two subprocesses and writes
//! files, which is a tool rather than an assertion. `cargo run --example fuzz`
//! gives it a natural invocation that `cargo test` does not.
//!
//! ```text
//! cargo run --release --example fuzz -- --start 1 --count 2000
//! ```
//!
//! Every divergence it finds should be minimized, decided, **written into
//! `corpus/` as a case first**, and only then fixed. The corpus is what both
//! implementations answer to; a seed number is not, because
//! [`markdown_prose_hooks::fuzz`] renames every seed the moment its bank moves.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use markdown_prose_hooks::fuzz;
use markdown_prose_hooks::scan::py_splitlines_keepends;

/// The file name every case is written to, inside each runner's own directory.
const SUBJECT: &str = "note.md";

/// The argument lists worth running, cycled by seed.
///
/// `--write --json` is the richest: it reaches the transform, both counts, the
/// rewrite, and the transcript skip in one run. The other two are here because
/// they reach exit codes the first one cannot.
const ARGV: [&[&str]; 3] = [
    &["--write", "--json", SUBJECT],
    &["--json", SUBJECT],
    &["--write", "--fail-on-change", SUBJECT],
];

/// One implementation, and the scratch directory it runs in.
struct Runner {
    label: &'static str,
    program: String,
    leading: Vec<String>,
    dir: PathBuf,
}

/// Everything the parity boundary covers, plus the file the run left behind.
#[derive(PartialEq, Eq)]
struct Observed {
    code: i32,
    stdout: Vec<u8>,
    subject: Vec<u8>,
}

fn main() -> std::process::ExitCode {
    let options = Options::parse();
    let root = PathBuf::from("target/fuzz");
    let python = Runner {
        label: "py",
        program: options.python[0].clone(),
        leading: options.python[1..].to_vec(),
        dir: root.join("py"),
    };
    let rust = Runner {
        label: "rs",
        program: options.rust.clone(),
        leading: Vec::new(),
        dir: root.join("rs"),
    };

    let mut divergences = 0;
    for seed in options.start..options.start + options.count {
        let document = fuzz::document(seed);
        let argv = ARGV[(seed % ARGV.len() as u64) as usize];
        if compare(&python, &rust, argv, &document).is_none() {
            continue;
        }
        divergences += 1;
        // A hundred-line divergence is not a bug report; a three-line one is.
        let minimal = minimize(&document, |candidate| {
            compare(&python, &rust, argv, candidate).is_some()
        });
        println!("--- divergence, seed {seed}, argv {argv:?} ---");
        println!("minimized input: {minimal:?}");
        if let Some((left, right)) = compare(&python, &rust, argv, &minimal) {
            report(&python, &left);
            report(&rust, &right);
        }
        if divergences >= options.stop_after {
            break;
        }
    }
    println!(
        "{divergences} divergences over {} seeds from {}",
        options.count, options.start
    );
    if divergences == 0 {
        std::process::ExitCode::SUCCESS
    } else {
        std::process::ExitCode::FAILURE
    }
}

/// Run both implementations over one document, or `None` when they agree.
fn compare(
    python: &Runner,
    rust: &Runner,
    argv: &[&str],
    document: &str,
) -> Option<(Observed, Observed)> {
    let left = observe(python, argv, document);
    let right = observe(rust, argv, document);
    (left != right).then_some((left, right))
}

/// Run one implementation in its own directory over a fresh copy of `document`.
fn observe(runner: &Runner, argv: &[&str], document: &str) -> Observed {
    let subject = runner.dir.join(SUBJECT);
    fs::create_dir_all(&runner.dir).expect("scratch directory");
    fs::write(&subject, document.as_bytes()).expect("write the subject");
    let output = Command::new(&runner.program)
        .args(&runner.leading)
        .args(argv)
        .current_dir(&runner.dir)
        .output()
        .unwrap_or_else(|error| panic!("running {}: {error}", runner.label));
    Observed {
        // A signal leaves no code. `-1` is not a status either implementation
        // can return, so it cannot be mistaken for agreement.
        code: output.status.code().unwrap_or(-1),
        stdout: output.stdout,
        subject: fs::read(&subject).unwrap_or_default(),
    }
}

/// Delta-debug by line removal until a whole pass changes nothing.
fn minimize(document: &str, still_diverges: impl Fn(&str) -> bool) -> String {
    let mut lines: Vec<String> = py_splitlines_keepends(document)
        .into_iter()
        .map(str::to_owned)
        .collect();
    loop {
        let mut removed_any = false;
        let mut index = 0;
        while index < lines.len() {
            let mut candidate = lines.clone();
            candidate.remove(index);
            let text = candidate.concat();
            if still_diverges(&text) {
                lines = candidate;
                removed_any = true;
            } else {
                index += 1;
            }
        }
        if !removed_any {
            return lines.concat();
        }
    }
}

/// Print what one implementation did, with the bytes escaped.
fn report(runner: &Runner, observed: &Observed) {
    println!(
        "  {}: exit {} stdout {:?}",
        runner.label,
        observed.code,
        String::from_utf8_lossy(&observed.stdout)
    );
    println!(
        "  {}: file {:?}",
        runner.label,
        String::from_utf8_lossy(&observed.subject)
    );
}

/// The fuzzer's own arguments.
struct Options {
    start: u64,
    count: u64,
    stop_after: usize,
    python: Vec<String>,
    rust: String,
}

impl Options {
    fn parse() -> Self {
        let mut options = Self {
            start: 1,
            count: 1000,
            stop_after: 5,
            // Overridable because the interpreter that has this package
            // importable is a local decision: a uv venv, a `pre-commit`
            // environment and a plain install all spell it differently.
            python: vec![
                "python3".to_owned(),
                "-m".to_owned(),
                "markdown_prose_hooks".to_owned(),
            ],
            rust: Path::new("target/release/unwrap-markdown-prose-rs")
                .to_string_lossy()
                .into_owned(),
        };
        let argv: Vec<String> = std::env::args().skip(1).collect();
        let mut index = 0;
        while index < argv.len() {
            let value = argv.get(index + 1).cloned().unwrap_or_default();
            match argv[index].as_str() {
                "--start" => options.start = value.parse().expect("--start takes a number"),
                "--count" => options.count = value.parse().expect("--count takes a number"),
                "--stop-after" => {
                    options.stop_after = value.parse().expect("--stop-after takes a number");
                }
                "--python" => {
                    options.python = value.split_whitespace().map(str::to_owned).collect();
                }
                "--rust" => options.rust = value,
                other => panic!("unknown argument {other}"),
            }
            index += 2;
        }
        // Each runner runs with its scratch directory as the working directory,
        // and a relative program path is resolved against *that*, not against
        // where the fuzzer was started. Absolute paths cannot be misread.
        options.rust = absolute(&options.rust);
        options.python[0] = absolute(&options.python[0]);
        options
    }
}

/// Make a program path absolute, leaving a bare name for `PATH` to resolve.
///
/// Lexically, and deliberately not with `canonicalize`: a virtual environment's
/// `python3` is a symlink to the interpreter it was built from, and resolving it
/// leaves an interpreter that cannot import this package. That failure looks
/// exactly like a divergence — every seed, Python exiting 1 with empty stdout —
/// which is the worst way for a fuzzer to be wrong.
fn absolute(program: &str) -> String {
    let path = Path::new(program);
    if path.components().count() < 2 {
        return program.to_owned();
    }
    std::path::absolute(path)
        .unwrap_or_else(|error| panic!("resolving {program}: {error}"))
        .to_string_lossy()
        .into_owned()
}
