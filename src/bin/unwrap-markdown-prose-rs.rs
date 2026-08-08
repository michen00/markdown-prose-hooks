//! The Rust implementation's command-line entry point.
//!
//! Named for its file rather than for the package, because Cargo takes a
//! `src/bin` target's name from the filename. The `-rs` suffix is what lets both
//! implementations sit on one `PATH` and lets `corpus/cli/` run each in turn.

use std::io::Write;
use std::process::ExitCode;

use markdown_prose_hooks::cli;

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let outcome = cli::run(&argv, &cli::working_directory());
    // Written as bytes rather than through `println!`, so nothing between here
    // and the pipe decides what a newline is. The Python pins its own streams to
    // `\n` for the same reason: stdout is compared byte for byte, and a CRLF
    // there would make this program's output the one thing in the repository
    // whose line endings the platform chooses.
    let _ = std::io::stdout().write_all(outcome.stdout.as_bytes());
    let _ = std::io::stderr().write_all(outcome.stderr.as_bytes());
    let _ = std::io::stdout().flush();
    ExitCode::from(outcome.code)
}
