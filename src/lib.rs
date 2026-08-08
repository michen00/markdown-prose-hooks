//! Conservatively remove manual line breaks from Markdown prose.
//!
//! A second implementation of the unwrap, answering to the same conformance
//! corpus as the Python one in `src/markdown_prose_hooks/`. The corpus is the
//! specification; neither implementation is.

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

/// Return Markdown with soft wraps in paragraph contexts joined.
///
/// Task 9 replaces this body. Until then it is deliberately the identity, so
/// the corpus harness reports real divergence rather than a build error.
#[must_use]
pub fn unwrap_markdown_prose(text: &str) -> UnwrapResult {
    UnwrapResult {
        content: text.to_owned(),
        paragraphs_unwrapped: 0,
        line_breaks_removed: 0,
    }
}
