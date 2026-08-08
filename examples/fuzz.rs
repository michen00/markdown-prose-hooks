//! Differential fuzzer: one generated tree, one argv, two binaries.
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

/// One file of a generated tree: its relative path and its contents.
type File = (String, String);

/// One implementation, and the scratch directory it runs in.
struct Runner {
    label: &'static str,
    program: String,
    leading: Vec<String>,
    dir: PathBuf,
}

/// Everything the parity boundary covers, plus the tree the run left behind.
///
/// The tree matters as much as the output: it is what catches a run writing a
/// file it should have skipped, which no amount of stdout checking would
/// notice. The same reasoning as the CLI corpus comparing `expected/` whole.
#[derive(PartialEq, Eq)]
struct Observed {
    code: i32,
    stdout: Vec<u8>,
    tree: Vec<(String, Vec<u8>)>,
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
        let scenario = fuzz::scenario(seed);
        let argv: Vec<&str> = scenario.argv.iter().map(String::as_str).collect();
        if compare(&python, &rust, &argv, &scenario.files).is_none() {
            continue;
        }
        divergences += 1;
        // A hundred-line divergence is not a bug report; a three-line one is.
        let minimal = minimize(&scenario.files, |files| {
            compare(&python, &rust, &argv, files).is_some()
        });
        println!("--- divergence, seed {seed}, argv {:?} ---", scenario.argv);
        for (name, contents) in &minimal {
            println!("  {name}: {contents:?}");
        }
        if let Some((left, right)) = compare(&python, &rust, &argv, &minimal) {
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

/// Run both implementations over one tree, or `None` when they agree.
fn compare(
    python: &Runner,
    rust: &Runner,
    argv: &[&str],
    files: &[File],
) -> Option<(Observed, Observed)> {
    let left = observe(python, argv, files);
    let right = observe(rust, argv, files);
    (left != right).then_some((left, right))
}

/// Run one implementation over a fresh copy of `files` in its own directory.
fn observe(runner: &Runner, argv: &[&str], files: &[File]) -> Observed {
    // Removed rather than overwritten, so a file one seed created cannot be
    // read by the next one and turn a clean run into a phantom divergence.
    let _ = fs::remove_dir_all(&runner.dir);
    fs::create_dir_all(&runner.dir).expect("scratch directory");
    for (name, contents) in files {
        let path = runner.dir.join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("parent directory");
        }
        fs::write(&path, contents.as_bytes()).expect("write a subject file");
    }
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
        tree: snapshot(&runner.dir),
    }
}

/// Every file under `root`, by relative POSIX path, sorted.
fn snapshot(root: &Path) -> Vec<(String, Vec<u8>)> {
    let mut found = Vec::new();
    collect(root, root, &mut found);
    found.sort();
    found
}

/// Walk `dir`, appending every file it holds.
fn collect(root: &Path, dir: &Path, found: &mut Vec<(String, Vec<u8>)>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect(root, &path, found);
            continue;
        }
        // Compared across platforms, so the separator cannot be the platform's.
        let relative = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        found.push((relative, fs::read(&path).unwrap_or_default()));
    }
}

/// Delta-debug by line removal, across every file, until a pass changes nothing.
fn minimize(files: &[File], still_diverges: impl Fn(&[File]) -> bool) -> Vec<File> {
    let mut current: Vec<(String, Vec<String>)> = files
        .iter()
        .map(|(name, contents)| {
            let lines = py_splitlines_keepends(contents)
                .into_iter()
                .map(str::to_owned)
                .collect();
            (name.clone(), lines)
        })
        .collect();
    loop {
        let mut removed_any = false;
        for index in 0..current.len() {
            let mut line = 0;
            while line < current[index].1.len() {
                let mut candidate = current.clone();
                candidate[index].1.remove(line);
                if still_diverges(&joined(&candidate)) {
                    current = candidate;
                    removed_any = true;
                } else {
                    line += 1;
                }
            }
        }
        if !removed_any {
            // A file emptied by this is kept: that it exists at all is part of
            // the case, and deleting it would change what the run is given.
            return joined(&current);
        }
    }
}

/// Put each file's surviving lines back together.
fn joined(files: &[(String, Vec<String>)]) -> Vec<File> {
    files
        .iter()
        .map(|(name, lines)| (name.clone(), lines.concat()))
        .collect()
}

/// Print what one implementation did, with the bytes escaped.
fn report(runner: &Runner, observed: &Observed) {
    println!(
        "  {}: exit {} stdout {:?}",
        runner.label,
        observed.code,
        String::from_utf8_lossy(&observed.stdout)
    );
    for (name, contents) in &observed.tree {
        println!(
            "  {}: {name} {:?}",
            runner.label,
            String::from_utf8_lossy(contents)
        );
    }
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
