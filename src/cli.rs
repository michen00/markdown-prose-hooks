//! The command line: argument parsing, file walking, reporting, exit codes.
//!
//! The parity boundary is exit codes and stdout, byte for byte; stderr need only
//! match in meaning, which is why the error prose here is not a translation of
//! Python's. `corpus/cli/` judges all three.
//!
//! The parser reproduces argparse's contract rather than inventing one, and
//! every behavior below was measured against CPython rather than recalled:
//! unambiguous long-option abbreviation, `--opt=value`, `--` ending the option
//! list without breaking the positional run, a lone `-` as a positional, and a
//! token starting with `-` being a positional when it looks like a negative
//! number or contains a space.
//!
//! One argparse behavior is deliberately *not* reproduced exactly. See
//! [`is_negative_number`].

use std::fmt::Write as _;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use crate::ignore::{IGNORE_FILE_NAME, IgnoreRules};
use crate::scan::{py_splitlines_keepends, py_trim, split_eol};
use crate::transcript::is_transcript_like_markdown;
use crate::unwrap_markdown_prose;

/// What one run of the program produced.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Outcome {
    /// Bytes for stdout. Compared byte for byte against the other implementation.
    pub stdout: String,
    /// Bytes for stderr. Compared only in meaning.
    pub stderr: String,
    /// The process exit status.
    pub code: u8,
}

/// The parsed command line.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Args {
    /// Markdown files to inspect.
    pub paths: Vec<String>,
    /// Read additional newline-delimited paths from this file.
    pub files_from: Option<String>,
    /// Rewrite files in place instead of only reporting.
    pub write: bool,
    /// Emit a machine-readable summary.
    pub json: bool,
    /// Exit non-zero when any file changed or would change.
    pub fail_on_change: bool,
    /// Read ignore patterns from here instead of `./.unwrapignore`.
    pub ignore_file: Option<String>,
    /// Skip paths matching these globs.
    pub exclude: Vec<String>,
}

/// What a flag does with the token after it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Takes {
    Nothing,
    OneValue,
}

/// Every long option, in the order `--help` would list them.
const OPTIONS: [(&str, Takes); 7] = [
    ("--help", Takes::Nothing),
    ("--files-from", Takes::OneValue),
    ("--write", Takes::Nothing),
    ("--json", Takes::Nothing),
    ("--fail-on-change", Takes::Nothing),
    ("--ignore-file", Takes::OneValue),
    ("--exclude", Takes::OneValue),
];

/// One report line per file the tool actually opened.
#[derive(Debug, Clone, PartialEq, Eq)]
struct FileReport {
    path: String,
    changed: bool,
    paragraphs_unwrapped: usize,
    line_breaks_removed: usize,
}

/// Why a file could not be read, in the tool's own vocabulary.
///
/// Error strings travel in the `--json` payload on stdout, and stdout is the
/// half of the parity boundary that must match byte for byte. Quoting the
/// runtime makes that impossible: Python renders one thing and Rust another, and
/// neither survives a change of platform or locale. So the tool says what
/// happened in words it owns, and anything unrecognized answers `unreadable`
/// rather than leaking a message.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReadError {
    Io(ErrorKind),
    NotUtf8,
}

/// Run the program and return everything it would have written.
///
/// `root` is the directory relative paths resolve against, which is the process
/// working directory in `main` and a scratch tree in the tests. It changes which
/// bytes are opened and nothing that is reported: a path is reported as it was
/// written on the command line, never as it was resolved.
#[must_use]
pub fn run(argv: &[String], root: &Path) -> Outcome {
    let args = match parse_args(argv) {
        Ok(args) => args,
        Err(message) => {
            return Outcome {
                stdout: String::new(),
                stderr: format!("error: {message}\n"),
                // argparse exits 2 on a parse error, and this is the only path
                // that produces a code the corpus does not otherwise reach.
                code: 2,
            };
        }
    };
    if args.paths.is_empty() && args.files_from.is_none() && wants_help(argv) {
        return Outcome {
            stdout: usage(),
            stderr: String::new(),
            code: 0,
        };
    }

    let mut errors: Vec<String> = Vec::new();
    let raw_paths = collect_input_paths(&args, root, &mut errors);
    let rules = build_ignore_rules(&args, root, &mut errors);
    let mut reports: Vec<FileReport> = Vec::new();

    for raw in &raw_paths {
        // Filtered here rather than inside any one discovery path, so exclusion
        // means the same thing however the name arrived. An excluded file leaves
        // no report and no error and so cannot trip `--fail-on-change`:
        // exclusion is a statement about scope, and a file that was never in
        // scope has nothing to fail about.
        if rules.excludes(raw) {
            continue;
        }
        let full = root.join(raw);
        let reported = posix_display(raw);
        // A symlink is skipped before anything follows it, and a missing or
        // non-regular path is skipped silently too. Only a file the tool tried
        // and failed to read is an error.
        let Ok(metadata) = fs::symlink_metadata(&full) else {
            continue;
        };
        if metadata.file_type().is_symlink() || !full.is_file() {
            continue;
        }
        match process_file(&full, &reported, args.write) {
            Ok(report) => reports.push(report),
            // Reported rather than raised. A formatter given twenty files must
            // not decline to format nineteen because the first was unreadable.
            Err(error) => errors.push(format!(
                "{reported}: cannot read ({})",
                describe(&full, error)
            )),
        }
    }

    let changed = reports.iter().any(|report| report.changed);
    let mut stdout = String::new();
    let mut stderr = String::new();
    if args.json {
        stdout.push_str(&json_payload(changed, &reports, &errors));
        stdout.push('\n');
    } else {
        for report in &reports {
            if report.changed {
                let _ = writeln!(
                    stdout,
                    "{}: removed {} manual line break(s)",
                    report.path, report.line_breaks_removed
                );
            }
        }
        for error in &errors {
            let _ = writeln!(stderr, "{error}");
        }
    }
    // `pre-commit` notices a hook rewriting a file and fails the run itself, so
    // the framework path needs no help. A GitHub Action has no such wrapper:
    // without this, a workflow step that reformatted every file still reports
    // success, which is the one outcome a check must never produce.
    let code = u8::from(args.fail_on_change && changed || !errors.is_empty());
    Outcome {
        stdout,
        stderr,
        code,
    }
}

/// Parse `argv`, or return the message a parse failure would print.
///
/// # Errors
///
/// Returns the failure text when a token is not a valid option, an abbreviation
/// is ambiguous, or an option that takes a value was not given one.
pub fn parse_args(argv: &[String]) -> Result<Args, String> {
    let tokens = classify(argv);
    let mut args = Args::default();
    let mut paths_taken = false;
    let mut extras: Vec<String> = Vec::new();
    let mut index = 0;
    while index < tokens.len() {
        let Token::Option { name, inline } = &tokens[index] else {
            // Positionals arrive in contiguous runs, and argparse gives the
            // whole first run to the one `nargs='*'` action and then retires it.
            // Every later run is therefore unrecognized -- measured, not
            // assumed: `a.md --exclude x b.md` exits 2 under CPython.
            let start = index;
            while matches!(tokens.get(index), Some(Token::Positional(_))) {
                index += 1;
            }
            let run = tokens[start..index]
                .iter()
                .map(Token::value)
                .collect::<Vec<String>>();
            if paths_taken {
                extras.extend(run);
            } else {
                args.paths = run;
                paths_taken = true;
            }
            continue;
        };
        let (option, takes) = resolve(name)?;
        index += 1;
        if takes == Takes::Nothing {
            if inline.is_some() {
                return Err(format!("argument {option}: ignored explicit argument"));
            }
            match option {
                "--write" => args.write = true,
                "--json" => args.json = true,
                "--fail-on-change" => args.fail_on_change = true,
                _ => {}
            }
            continue;
        }
        let value = match inline {
            Some(value) => value.clone(),
            None => match tokens.get(index) {
                // An option's value may be a token that starts with `-` only
                // when that token is not itself option-like, which is why
                // `--exclude -12` is accepted and `--exclude --json` is not.
                Some(Token::Positional(value)) => {
                    index += 1;
                    value.clone()
                }
                _ => return Err(format!("argument {option}: expected one argument")),
            },
        };
        match option {
            "--files-from" => args.files_from = Some(value),
            "--ignore-file" => args.ignore_file = Some(value),
            // Repeatable, and applied after the ignore file.
            "--exclude" => args.exclude.push(value),
            _ => {}
        }
    }
    if extras.is_empty() {
        Ok(args)
    } else {
        Err(format!("unrecognized arguments: {}", extras.join(" ")))
    }
}

/// One command-line token, already decided to be an option or not.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Token {
    Option {
        name: String,
        inline: Option<String>,
    },
    Positional(String),
}

impl Token {
    fn value(&self) -> String {
        match self {
            Token::Positional(value) => value.clone(),
            Token::Option { name, .. } => name.clone(),
        }
    }
}

/// Decide what each token is, once, before anything is consumed.
///
/// argparse classifies the whole of `argv` up front and only then matches
/// actions against the pattern, which is why an option's value is decided by
/// what the *token* looks like rather than by what the option wanted.
fn classify(argv: &[String]) -> Vec<Token> {
    let mut tokens = Vec::with_capacity(argv.len());
    let mut rest_are_positional = false;
    for arg in argv {
        if rest_are_positional {
            tokens.push(Token::Positional(arg.clone()));
            continue;
        }
        if arg == "--" {
            // The first `--` is removed rather than kept, and it does not break
            // the positional run around it: `a.md -- b.md` yields both paths.
            // A second one is an ordinary positional.
            rest_are_positional = true;
            continue;
        }
        if !is_option_like(arg) {
            tokens.push(Token::Positional(arg.clone()));
            continue;
        }
        match arg.split_once('=') {
            Some((name, value)) => tokens.push(Token::Option {
                name: name.to_owned(),
                inline: Some(value.to_owned()),
            }),
            None => tokens.push(Token::Option {
                name: arg.clone(),
                inline: None,
            }),
        }
    }
    tokens
}

/// Would argparse read this token as an option rather than as a positional?
fn is_option_like(arg: &str) -> bool {
    if !arg.starts_with('-') || arg.chars().count() == 1 {
        return false;
    }
    // Both of these make a `-`-leading token a positional under argparse.
    !is_negative_number(arg) && !arg.contains(' ')
}

/// argparse's `_negative_number_matcher`, narrowed to ASCII.
///
/// The standard library's is `^-\d+$|^-\d*\.\d+$`, and its `\d` is Unicode `Nd`
/// — 650 code points on 3.10 and 680 on 3.13. That is the same defect the
/// specification removed from this tool's own patterns in Task 3, except that
/// this pattern belongs to CPython and cannot be narrowed from here without
/// reaching into a private attribute of the standard library.
///
/// **So one divergence is accepted and stated rather than hidden.** A token like
/// `-١٢` is a positional path under Python and an unknown option under this
/// implementation. Every ASCII spelling agrees, which is what
/// `corpus/cli/a-negative-number-argument-is-a-path` pins. The alternative —
/// monkeypatching `_negative_number_matcher` — trades a rare, documented
/// divergence for a silent breakage on any interpreter that renames it, which is
/// the worse of the two.
fn is_negative_number(arg: &str) -> bool {
    let Some(rest) = arg.strip_prefix('-') else {
        return false;
    };
    if !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_digit()) {
        return true;
    }
    // `^-\d*\.\d+$`: the digits before the point are optional, the ones after
    // are not, so `-.5` is a number and `-5.` is not.
    match rest.split_once('.') {
        Some((whole, fraction)) => {
            whole.bytes().all(|b| b.is_ascii_digit())
                && !fraction.is_empty()
                && fraction.bytes().all(|b| b.is_ascii_digit())
        }
        None => false,
    }
}

/// Resolve an option name, allowing an unambiguous abbreviation.
fn resolve(name: &str) -> Result<(&'static str, Takes), String> {
    if let Some((option, takes)) = OPTIONS.iter().find(|(option, _)| *option == name) {
        return Ok((option, *takes));
    }
    if name == "-h" {
        return Ok(("--help", Takes::Nothing));
    }
    let candidates: Vec<&(&'static str, Takes)> = OPTIONS
        .iter()
        .filter(|(option, _)| option.starts_with(name))
        .collect();
    match candidates.as_slice() {
        [(option, takes)] => Ok((option, *takes)),
        [] => Err(format!("unrecognized arguments: {name}")),
        many => Err(format!(
            "ambiguous option: {name} could match {}",
            many.iter()
                .map(|(option, _)| *option)
                .collect::<Vec<&str>>()
                .join(", ")
        )),
    }
}

/// Did the caller ask for help?
fn wants_help(argv: &[String]) -> bool {
    argv.iter().any(|arg| {
        arg == "-h" || (is_option_like(arg) && matches!(resolve(arg), Ok(("--help", _))))
    })
}

/// The usage text.
///
/// Deliberately outside the parity boundary: it carries the program name, and
/// the program name is exactly what differs between the two implementations, so
/// `corpus/cli/README.md` states that no case asserts it.
fn usage() -> String {
    let mut text = String::from("Detect or remove manual line breaks in Markdown prose.\n\n");
    text.push_str("usage: unwrap-markdown-prose-rs [options] [paths ...]\n\n");
    for (option, takes) in OPTIONS {
        let value = if takes == Takes::OneValue {
            " VALUE"
        } else {
            ""
        };
        let _ = writeln!(text, "  {option}{value}");
    }
    text
}

/// `_collect_input_paths`: positional arguments, then any `--files-from` list.
fn collect_input_paths(args: &Args, root: &Path, errors: &mut Vec<String>) -> Vec<String> {
    let mut paths = args.paths.clone();
    let Some(files_from) = &args.files_from else {
        return paths;
    };
    let full = root.join(files_from);
    match read_text(&full) {
        // `Path.read_text` opens in text mode, which translates `\r\n` and a
        // lone `\r` to `\n` on the way in. The ignore file below is opened with
        // `newline=''` and is not translated, so the two differ on purpose.
        Ok(contents) => {
            let translated = contents.replace("\r\n", "\n").replace('\r', "\n");
            paths.extend(
                py_splitlines_keepends(&translated)
                    .into_iter()
                    .map(|line| split_eol(line).0)
                    .filter(|line| !py_trim(line).is_empty())
                    .map(str::to_owned),
            );
        }
        Err(error) => errors.push(format!(
            "{}: cannot read --files-from ({})",
            posix_display(files_from),
            describe(&full, error)
        )),
    }
    paths
}

/// `_build_ignore_rules`: the patterns in force, and any error reading them.
fn build_ignore_rules(args: &Args, root: &Path, errors: &mut Vec<String>) -> IgnoreRules {
    let explicit = args.ignore_file.as_deref();
    let name = explicit.unwrap_or(IGNORE_FILE_NAME);
    let full = root.join(name);
    // A missing default is silent because nobody asked for it. A missing
    // `--ignore-file` was named on the command line, and honoring the default
    // instead would format every file the caller meant to protect.
    let text = if explicit.is_some() || full.is_file() {
        match read_text(&full) {
            Ok(text) => Some(text),
            Err(error) => {
                errors.push(format!(
                    "{}: cannot read --ignore-file ({})",
                    posix_display(name),
                    describe(&full, error)
                ));
                None
            }
        }
    } else {
        None
    };
    IgnoreRules::new(text.as_deref(), args.exclude.iter().map(String::as_str))
}

/// `_process_file`: read, transform, optionally rewrite, and report.
fn process_file(full: &Path, reported: &str, write: bool) -> Result<FileReport, ReadError> {
    let original = read_text(full)?;
    if is_transcript_like_markdown(&original) {
        return Ok(FileReport {
            path: reported.to_owned(),
            changed: false,
            paragraphs_unwrapped: 0,
            line_breaks_removed: 0,
        });
    }
    let result = unwrap_markdown_prose(&original);
    let changed = result.content != original;
    if write && changed {
        // Written as bytes, so the file's original `\r\n` or `\r` style passes
        // straight back through. A text-mode write would rewrite every line
        // ending in the file on the first unwrap that lands.
        fs::write(full, result.content.as_bytes()).map_err(|e| ReadError::Io(e.kind()))?;
    }
    Ok(FileReport {
        path: reported.to_owned(),
        changed,
        paragraphs_unwrapped: result.paragraphs_unwrapped,
        line_breaks_removed: result.line_breaks_removed,
    })
}

/// Read a file with no newline translation and a strict UTF-8 decode.
fn read_text(path: &Path) -> Result<String, ReadError> {
    let bytes = fs::read(path).map_err(|error| ReadError::Io(error.kind()))?;
    String::from_utf8(bytes).map_err(|_| ReadError::NotUtf8)
}

/// `_describe_error`: the tool's own name for a read failure.
///
/// The condition is resolved before the class, because for one case the class is
/// itself platform-dependent: opening a directory is `EISDIR` on POSIX and
/// `EACCES` on Windows. Keying on the class alone let the platform back into a
/// payload that has to match byte for byte, and the CLI tier caught it.
fn describe(path: &Path, error: ReadError) -> &'static str {
    let kind = match error {
        // A decode failure carries no filename in Python either, so it never
        // reaches the directory test.
        ReadError::NotUtf8 => return "not valid UTF-8",
        ReadError::Io(kind) => kind,
    };
    if path.is_dir() {
        return "is a directory";
    }
    match kind {
        ErrorKind::NotFound => "not found",
        ErrorKind::IsADirectory => "is a directory",
        ErrorKind::NotADirectory => "not a directory",
        ErrorKind::PermissionDenied => "permission denied",
        _ => "unreadable",
    }
}

/// `Path(raw).as_posix()`: how a path is reported, on every platform.
///
/// A Windows run prints `sub/nested.md`, never `sub\nested.md`. The
/// normalization is the path type's own: duplicate separators collapse, `.`
/// components go, and `..` stays -- which is why the ignore rules resolve `..`
/// for themselves rather than relying on this.
///
/// UNC and drive-relative paths are out of scope; the corpus is what judges this
/// and it holds neither.
#[must_use]
pub fn posix_display(raw: &str) -> String {
    let separators: &[char] = if cfg!(windows) { &['/', '\\'] } else { &['/'] };
    let leading = raw.chars().take_while(|c| separators.contains(c)).count();
    // POSIX gives exactly two leading slashes their own meaning and collapses
    // any longer run to one.
    let root = match leading {
        0 => "",
        2 if !cfg!(windows) => "//",
        _ => "/",
    };
    let parts: Vec<&str> = raw
        .split(separators)
        .filter(|part| !part.is_empty() && *part != ".")
        .collect();
    if parts.is_empty() {
        return if root.is_empty() { "." } else { root }.to_owned();
    }
    format!("{root}{}", parts.join("/"))
}

/// The `--json` payload, matching `json.dumps(payload, indent=2, sort_keys=True)`.
fn json_payload(changed: bool, reports: &[FileReport], errors: &[String]) -> String {
    let mut out = String::from("{\n  \"changed\": ");
    out.push_str(if changed { "true" } else { "false" });
    out.push_str(",\n  \"errors\": ");
    if errors.is_empty() {
        out.push_str("[]");
    } else {
        out.push_str("[\n");
        for (index, error) in errors.iter().enumerate() {
            out.push_str("    ");
            json_string(error, &mut out);
            out.push_str(if index + 1 == errors.len() {
                "\n"
            } else {
                ",\n"
            });
        }
        out.push_str("  ]");
    }
    out.push_str(",\n  \"files\": ");
    if reports.is_empty() {
        out.push_str("[]");
    } else {
        out.push_str("[\n");
        for (index, report) in reports.iter().enumerate() {
            // Keys sorted, which puts `path` last rather than first.
            let _ = write!(
                out,
                "    {{\n      \"changed\": {},\n      \"line_breaks_removed\": {},\n      \"paragraphs_unwrapped\": {},\n      \"path\": ",
                report.changed, report.line_breaks_removed, report.paragraphs_unwrapped
            );
            json_string(&report.path, &mut out);
            out.push_str("\n    }");
            out.push_str(if index + 1 == reports.len() {
                "\n"
            } else {
                ",\n"
            });
        }
        out.push_str("  ]");
    }
    out.push_str("\n}");
    out
}

/// One JSON string literal, escaped the way `ensure_ascii=True` escapes.
///
/// Everything outside `0x20..=0x7e` is escaped, which includes `U+007F`: it is
/// ASCII, and it is still escaped. Emitting a raw DEL byte there diverges on
/// stdout, which is the half of the boundary that has to match.
fn json_string(text: &str, out: &mut String) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{20}'..='\u{7e}' => out.push(c),
            _ => {
                // Above the basic plane Python emits a surrogate pair, which is
                // what encoding to UTF-16 produces.
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
        }
    }
    out.push('"');
}

/// The working directory, or `.` when it cannot be read.
#[must_use]
pub fn working_directory() -> PathBuf {
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(argv: &[&str]) -> Result<Args, String> {
        parse_args(
            &argv
                .iter()
                .map(|s| (*s).to_owned())
                .collect::<Vec<String>>(),
        )
    }

    #[test]
    fn the_first_positional_run_is_the_path_list() {
        assert_eq!(parse(&["a.md", "b.md"]).unwrap().paths, ["a.md", "b.md"]);
        assert_eq!(parse(&["--exclude", "x", "a.md"]).unwrap().paths, ["a.md"]);
        assert_eq!(
            parse(&["--write", "--json", "a.md", "b.md", "--exclude", "x"])
                .unwrap()
                .paths,
            ["a.md", "b.md"]
        );
    }

    #[test]
    fn a_second_positional_run_is_unrecognized() {
        // Measured against CPython. argparse retires the one `nargs='*'` action
        // after the first run, so a later positional has nothing left to match.
        assert!(parse(&["a.md", "--exclude", "x", "b.md"]).is_err());
        assert!(parse(&["--json", "a.md", "--json", "b.md"]).is_err());
    }

    #[test]
    fn an_abbreviation_is_taken_when_it_is_unambiguous() {
        assert!(parse(&["--wr"]).unwrap().write);
        assert!(parse(&["--w"]).unwrap().write);
        assert!(parse(&["--j"]).unwrap().json);
        assert!(parse(&["--fa"]).unwrap().fail_on_change);
        assert_eq!(parse(&["--e", "x"]).unwrap().exclude, ["x"]);
        assert_eq!(
            parse(&["--i", "x"]).unwrap().ignore_file.as_deref(),
            Some("x")
        );
        // `--files-from` and `--fail-on-change` share a prefix.
        assert!(parse(&["--f", "x"]).is_err());
    }

    #[test]
    fn a_value_may_be_given_inline_or_after() {
        assert_eq!(parse(&["--exclude=x"]).unwrap().exclude, ["x"]);
        assert_eq!(parse(&["--exc=x"]).unwrap().exclude, ["x"]);
        assert_eq!(
            parse(&["--files-from=list.txt"])
                .unwrap()
                .files_from
                .as_deref(),
            Some("list.txt")
        );
        assert!(parse(&["--exclude"]).is_err());
        // A value has to be a positional token, so another option is not one.
        assert!(parse(&["--exclude", "--json"]).is_err());
    }

    #[test]
    fn the_last_value_wins_and_exclude_accumulates() {
        assert_eq!(
            parse(&["--ignore-file", "x", "--ignore-file", "y"])
                .unwrap()
                .ignore_file
                .as_deref(),
            Some("y")
        );
        assert_eq!(
            parse(&["--exclude", "a", "--exclude", "b"])
                .unwrap()
                .exclude,
            ["a", "b"]
        );
    }

    #[test]
    fn a_dash_leading_token_is_a_positional_when_argparse_says_so() {
        assert_eq!(parse(&["--json", "-12"]).unwrap().paths, ["-12"]);
        assert_eq!(parse(&["--json", "-1.5"]).unwrap().paths, ["-1.5"]);
        assert_eq!(parse(&["--json", "-.5"]).unwrap().paths, ["-.5"]);
        assert_eq!(parse(&["--json", "-0"]).unwrap().paths, ["-0"]);
        assert_eq!(parse(&["-"]).unwrap().paths, ["-"]);
        assert_eq!(parse(&["--json", "-a b"]).unwrap().paths, ["-a b"]);
        assert!(parse(&["--json", "-x"]).is_err());
        assert!(parse(&["--json", "-1a"]).is_err());
        // `-5.` is not a number: the digits after the point are required.
        assert!(parse(&["--json", "-5."]).is_err());
        // An option's value may be a negative number.
        assert_eq!(parse(&["--exclude", "-12"]).unwrap().exclude, ["-12"]);
    }

    #[test]
    fn a_double_dash_ends_the_options_without_breaking_the_run() {
        assert_eq!(
            parse(&["a.md", "--", "b.md"]).unwrap().paths,
            ["a.md", "b.md"]
        );
        assert_eq!(parse(&["--", "a.md"]).unwrap().paths, ["a.md"]);
        assert_eq!(
            parse(&["--json", "--"]).unwrap().paths,
            Vec::<String>::new()
        );
        assert_eq!(parse(&["--json", "--", "-x"]).unwrap().paths, ["-x"]);
        // Only the first one is removed; a second is an ordinary positional.
        assert_eq!(parse(&["--", "--", "a.md"]).unwrap().paths, ["--", "a.md"]);
        let args = parse(&["--write", "--", "--write"]).unwrap();
        assert!(args.write);
        assert_eq!(args.paths, ["--write"]);
    }

    #[test]
    fn the_negative_number_rule_is_ascii_and_says_so() {
        assert!(is_negative_number("-12"));
        assert!(is_negative_number("-.5"));
        assert!(is_negative_number("-1.5"));
        assert!(!is_negative_number("-5."));
        assert!(!is_negative_number("-"));
        assert!(!is_negative_number("-1a"));
        // The accepted divergence: CPython's `\d` takes this and this does not.
        assert!(!is_negative_number("-\u{661}\u{662}"));
    }

    #[test]
    fn a_path_is_reported_with_posix_separators() {
        assert_eq!(posix_display("a.md"), "a.md");
        assert_eq!(posix_display("./a.md"), "a.md");
        assert_eq!(posix_display("a//b.md"), "a/b.md");
        assert_eq!(posix_display("a/b.md/"), "a/b.md");
        assert_eq!(posix_display("a/../b.md"), "a/../b.md");
        assert_eq!(posix_display(""), ".");
        assert_eq!(posix_display("/"), "/");
        assert_eq!(posix_display("///"), "/");
        assert_eq!(posix_display(".."), "..");
    }

    #[test]
    fn the_json_payload_matches_pythons_dump() {
        let payload = json_payload(
            true,
            &[FileReport {
                path: "fine.md".to_owned(),
                changed: true,
                paragraphs_unwrapped: 1,
                line_breaks_removed: 1,
            }],
            &["bad.md: cannot read (not valid UTF-8)".to_owned()],
        );
        assert_eq!(
            payload,
            "{\n  \"changed\": true,\n  \"errors\": [\n    \"bad.md: cannot read (not valid UTF-8)\"\n  ],\n  \"files\": [\n    {\n      \"changed\": true,\n      \"line_breaks_removed\": 1,\n      \"paragraphs_unwrapped\": 1,\n      \"path\": \"fine.md\"\n    }\n  ]\n}"
        );
        assert_eq!(
            json_payload(false, &[], &[]),
            "{\n  \"changed\": false,\n  \"errors\": [],\n  \"files\": []\n}"
        );
    }

    #[test]
    fn json_escapes_everything_outside_printable_ascii() {
        let mut out = String::new();
        json_string("a\u{7f}b", &mut out);
        // U+007F is ASCII and is still escaped.
        assert_eq!(out, "\"a\\u007fb\"");
        out.clear();
        json_string("\u{e9}\u{1f600}\"\\\n\t", &mut out);
        assert_eq!(out, "\"\\u00e9\\ud83d\\ude00\\\"\\\\\\n\\t\"");
    }
}
