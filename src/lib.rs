//! Conservatively remove manual line breaks from Markdown prose.
//!
//! A second implementation of the unwrap, answering to the same conformance
//! corpus as the Python one in `src/markdown_prose_hooks/`. The corpus is the
//! specification; neither implementation is.

pub mod cli;
pub mod code_span;
pub mod fuzz;
pub mod ignore;
pub mod label;
pub mod links;
pub mod paragraph;
pub mod scan;
pub mod transcript;

pub use paragraph::unwrap_markdown_prose;

/// Result of applying the Markdown prose unwrap pass.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnwrapResult {
    /// The rewritten document.
    pub content: String,
    /// How many paragraphs were joined.
    pub paragraphs_unwrapped: usize,
    /// How many manual line breaks were removed.
    pub line_breaks_removed: usize,
}
