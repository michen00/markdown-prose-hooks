//! The Rust command-line entry point.
//!
//! The filename is the binary name. `src/bin/<name>.rs` takes its own
//! filename, where an autodiscovered `src/main.rs` would take the package name
//! and build `markdown-prose-hooks` instead — colliding with the Python
//! console script on any PATH holding both. That is also what lets
//! `Cargo.toml` stay a `[package]` block and nothing else.

fn main() {
    // Task 11 replaces this with the real CLI. Exit 2 rather than 1: the
    // corpus spends 1 on "a file needed rewriting", and a stub must not be
    // mistaken for a verdict about a document.
    eprintln!("not implemented");
    std::process::exit(2);
}
