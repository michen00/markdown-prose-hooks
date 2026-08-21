# markdown-prose-hooks-rs

The two `pre-commit` hook ids for the Rust implementation of [markdown-prose-hooks](https://github.com/michen00/markdown-prose-hooks), and nothing else.

Nothing here is authored. This tree is a reduced view of that repository, carrying only what building and running these two ids requires, so that a consumer downloads one implementation rather than two implementations plus the corpus that specifies them and the notebook that measures them. It is replaced wholesale rather than merged, so an edit made here is an edit that gets overwritten — send it upstream.

What sits here is a wrapper: a crate whose only dependency is the published `markdown-prose-hooks`, and whose only source file is the binary that calls into it. `pre-commit` builds a `language: rust` hook with `cargo install --bins --root <envdir> --path .`, so it compiles this crate and fetches the implementation from crates.io. `Cargo.lock` is committed on purpose, so the build resolves the version this tree names even if a later one supersedes it.

## Use

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks-rs
    rev: '' # a commit or tag of this repository
    hooks:
      - id: unwrap-markdown-prose-rs
```

`unwrap-markdown-prose-rs` joins manual soft-wrap line breaks in Markdown prose, leaving code fences, tables, lists, front matter, hard breaks, and label rows untouched. `unwrap-markdown-prose-rs-check` reports the same files and rewrites nothing, for repositories that want the signal rather than the edit.

These ids need a Rust toolchain on the machine that installs them. `pre-commit` provisions one if cargo is absent, and that costs far more than the hook saves, so the choice between this repository and [markdown-prose-hooks-py](https://github.com/michen00/markdown-prose-hooks-py) turns on whether cargo is already installed rather than on any timing figure. Upstream's readme makes that argument in full.

Exclusions belong to the tool rather than to the framework: `.unwrapignore` and `--exclude` reach every way of invoking it, while `pre-commit`'s own `exclude:` key reaches only this one.

## What lives upstream

The conformance corpus that specifies the behavior, the Python implementation that answers to the same corpus, the differential fuzzer that compares them, the benchmarks, and the design documents. So does installing the tool outside `pre-commit`: it is published as `markdown-prose-hooks` on crates.io and on PyPI, under that name rather than this repository's, which is deliberately unpublished.

## License

MIT, in [LICENSE](LICENSE).
