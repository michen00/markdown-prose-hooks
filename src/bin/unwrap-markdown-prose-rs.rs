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
    let mut out = std::io::stdout();
    let delivered = out
        .write_all(outcome.stdout.as_bytes())
        .and_then(|()| out.flush());
    let _ = std::io::stderr().write_all(outcome.stderr.as_bytes());
    match delivered {
        Ok(()) => ExitCode::from(outcome.code),
        // How `| head` ends. The consumer stopped reading on purpose, so the
        // rest of the document not arriving is its decision rather than a
        // failure of this run.
        Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => {
            ExitCode::from(outcome.code)
        }
        Err(error) => {
            let _ = writeln!(std::io::stderr(), "cannot write to stdout ({error})");
            ExitCode::from(1)
        }
    }
}
