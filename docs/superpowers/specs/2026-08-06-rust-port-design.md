# Rust port design

A second implementation of the unwrap, in Rust, answering to the same conformance corpus as the Python one. Both are maintained; neither is a throwaway.

## Why

Two reasons, and they are different in kind. The first is that the corpus was written to be a language-neutral specification and has never been tested as one — a spec with a single implementation is a description of that implementation wearing a spec's clothes. A second implementation is the only thing that proves the corpus says what it means. The second reason is learning Rust, which argues for writing more of it by hand rather than less.

Those two reasons point the same direction more often than not, and where they conflict this document says which one wins.

## Constraints established by measurement

These were verified against the installed `pre-commit` 4.6.0 and the local toolchain rather than assumed, because each one decides part of the design.

**Both manifests must sit at the repository root.** `pre-commit` installs a `language: python` hook with `python -mpip install .` and a `language: rust` hook with `cargo install --bins --root <env> --path .`, both run with `cwd` set to the repository root. Moving `pyproject.toml` into a `python/` directory would break the existing hook, and `Cargo.toml` cannot live in `rust/`. Cargo can redirect its sources with explicit `path` keys, so this costs tidiness rather than structure.

**One of the nineteen patterns cannot be a regex in Rust.** A scan of every pattern constant found exactly one using constructs the `regex` crate excludes by design: `_CODE_SPAN_RE`, which needs both a backreference and a negative lookahead. It must be hand-written whatever else is decided.

**Dependencies are expensive for consumers.** A crate with `regex = "1"` compiles ten crates in 6.6 s; an empty crate compiles one in 0.12 s. `pre-commit` does not pass `--locked`, so a consumer does not even get lockfile-pinned versions in exchange.

**A lib-only crate cannot back a mirror repository.** `cargo install --bins --path .` on a crate with no binary fails with `error: no packages found with binaries or examples`, and `pre-commit` always installs the hook repository's own crate.

## Decisions

### Zero dependencies

The Rust crate takes no dependencies, matching the Python package's own promise. Eighteen of the nineteen patterns are mostly anchored, mostly literal matches that hand-write in a few lines each and run faster than a regex engine can dispatch; the nineteenth cannot use the crate anyway. Argument parsing is hand-written for the same reason.

This is the decision where learning and shipping agree. Hand-written scanners are where the Rust actually is — slices, `char_indices`, `strip_prefix`, exhaustive `match` — and they are also what keeps the hook cheap to install.

The cost is honest: the port stops being mechanical. With `regex` it would be a transliteration. Without it, every matcher is a small design problem, and the corpus is what makes that trade safe.

### Parity means matching Python, not matching CommonMark

`_CODE_SPAN_RE` is an approximation. Against `` `a``` `` it matches `` `a` ``, closing on the first backtick of a three-run, where CommonMark requires a span opened with a one-backtick run to close on a run of exactly one. The corpus pins the Python's behavior, so the Rust scanner reproduces the approximation rather than correcting it.

Correcting it is a separate change to the specification, made in the corpus first and then in both implementations. Doing it silently inside the port turns a spec question into what looks like a Rust bug.

### The naming is symmetric, with no alias

Hook ids become `unwrap-markdown-prose-py` and `unwrap-markdown-prose-rs`, each with a `-check` variant. The Rust binary is `unwrap-markdown-prose-rs`, distinct from the Python console script — otherwise `cargo install` shadows the Python one on `PATH` and the parity harness has no unambiguous way to name each.

Renaming the existing ids is free today, because the repository has no remote and no consumers, and is a breaking change the moment it has either.

There is no bare `unwrap-markdown-prose` alias. A hook id maps to a fixed `language` and `entry`, so it cannot route based on what a consumer has installed; a bare id would be a duplicated definition that silently means the Python one, which undoes the symmetry and drifts from whichever definition it was copied from.

### Publishing, and what is deferred

Publishing to PyPI and to crates.io is worth doing on its own merits: `pip install`, `cargo install`, discoverability, and consumers not using `pre-commit` at all.

Mirror repositories are deferred. Their usual justification is download size, and the tracked tree is 181K of which the corpus is 18K — ten percent, not the seventy-four percent a `du` reading suggests, because 154 small files round up to a 4K block each. The shape is recorded here so it is not re-derived later: a Rust mirror is a thin wrapper crate depending on the published crate whose `main.rs` calls into its library, which works only because this design splits `lib.rs` from `main.rs`.

## Layout

```text
Cargo.toml                  package root; explicit paths into rust/
pyproject.toml              unchanged
.pre-commit-hooks.yaml      four ids: {py,rs} x {write,check}
corpus/cases/<slug>/        transform tier, 51 cases, unchanged
corpus/cli/<slug>/          CLI tier, new
rust/src/                   Rust sources
rust/tests/                 Rust integration tests
src/markdown_prose_hooks/   Python, unchanged
tests/                      Python, unchanged
```

Keeping the Rust tests in `rust/tests/` is a preference rather than a necessity, and the difference is worth recording because the necessity was asserted first and then disproved. Cargo's default integration-test directory is `<package root>/tests/`, which here is the pytest directory, but target discovery is extension-scoped: a shared `tests/` holding `test_corpus.py`, `corpus.rs`, and a `__pycache__/` gives Cargo exactly one target and pytest exactly one test, each ignoring the other's files. They coexist.

The separation is for readers, not for the tools. A `tests/` directory that answers to two languages is harder to scan than two directories that each answer to one, and the cost is three lines of `Cargo.toml`. Because `tests/` then holds no `.rs` files at all, autodiscovery finds nothing and `autotests = false` is unnecessary; it stays off the manifest rather than being carried as cargo-cult defense.

## Modules

The Python is one 816-line file. That suits Python and does not suit learning Rust, so the port decomposes into units that can each be understood and tested alone.

| module | responsibility |
| -- | -- |
| `scan.rs` | the structural matchers: fence, blockquote and its prefix, list markers, setext, thematic break, link reference, HTML tag name, GFM alert |
| `code_span.rs` | the backreference matcher, alone, because it is the subtle one |
| `label.rs` | label, speaker, and bracketed-line classification |
| `links.rs` | link-only lines and link-block indexes |
| `paragraph.rs` | the accumulator and the row-wise flush |
| `transcript.rs` | `is_transcript_like_markdown` |
| `cli.rs`, `main.rs` | argument parsing, file walking, exit codes |

`scan.rs` carries most of the learning: small `fn(&str) -> Option<_>` functions, each independently testable, none of them interesting enough to hide a bug in.

## Known hazards

**Character counts versus byte offsets.** `_BARE_SPEAKER_HEADING_RE` is `^[A-Z][a-zA-Z0-9_. -]{0,39}:$`, where `{0,39}` counts characters. Rust slices bytes. A heading containing any non-ASCII character classifies differently unless the Rust counts `chars()`. This is exactly the drift dual maintenance produces, so it gets a corpus case rather than a comment.

**Line endings.** The tool exists partly to not rewrite CRLF into LF. `split_inclusive('\n')` keeps the terminator attached and slices without allocating, but the `\r` needs handling explicitly. Windows is in the test matrix for this reason alone.

## Parity architecture

Four layers, each covering what the one below cannot.

1. **Rust unit tests** for `scan.rs` and friends. Below the specification's altitude — they pin the matchers, not the behavior — so they stay Rust-native and out of the corpus.
2. **`corpus/cases/`**, run unchanged by both implementations. This is the specification.
3. **`corpus/cli/`**, new, covering the layer the corpus has never reached: argument parsing, file walking, `--write`, and `--fail-on-change`. Same philosophy as the existing tier — `key: value` metadata, literal files, a `why` that surfaces in the failure.
4. **Differential fuzzing.** A seeded generator assembles documents from a bank of fragments — fence openers, blockquote prefixes, list markers, label lines, table rows, code spans, mixed line endings, hard breaks — and both binaries run each one. Divergence is minimized and **promoted into the corpus**, which is what makes the corpus grow where drift actually lives rather than where it was anticipated.

### The CLI tier's format

```text
corpus/cli/<slug>/
  case.txt      name, why, argv, exit_code
  tree/         the input file tree, copied to a scratch directory before the run
  expected/     the tree as it must look afterward
  stdout.txt    expected stdout, verbatim; absent means empty
```

The run happens with the working directory set to the copied tree, so `argv` holds relative paths and needs no substitution. It splits on whitespace with no quoting rules, which every language does in one line; a case needing a path with a space in it is a reason to extend the format deliberately rather than to smuggle in a shell.

### The parity boundary

Exit codes and stdout must match byte for byte. **stderr need only match in meaning.** Byte-identical error prose across two languages is maintenance cost with no user-visible payoff, so the CLI tier asserts the first two and leaves the third free. Stating the boundary is the point; an unstated one gets litigated at every divergence.

## Error handling

No `anyhow` or `thiserror`, per the dependency decision. A small error enum implementing `Display` and `From` by hand, `Result` through the IO layer, and `main` returning `ExitCode`. Writing those impls is worth more here than importing them.

## CI

The existing `lint`, `test`, `hook`, `action`, and `build` jobs stay. Added:

- `rust-lint`: `cargo fmt --check` and `cargo clippy -- -D warnings`
- `rust-test`: `cargo test` on Linux, macOS, and Windows, matching the Python matrix's reasoning about line endings
- `parity`: build both, run the differential fuzzer over a fixed seed set plus one fresh seed per run so CI keeps exploring
- `hook`: extended to resolve the two new Rust ids through `pre-commit try-repo`

MSRV is pinned at 1.86 in `rust-version`, matching the local toolchain. Notably that predates if-let chains, which stabilized in 1.88.

## Sequence

One commit per step. From step five onward the corpus is the gate.

1. Cargo scaffold, `.gitignore` for `target/`, CI skeleton, and one deliberately failing corpus test that proves the harness reads the corpus at all
2. `scan.rs` and its unit tests
3. `code_span.rs`, including the approximation
4. `label.rs` and `links.rs`
5. `paragraph.rs` and the line state machine — **the corpus turns green here**
6. `transcript.rs`
7. `cli.rs` and `main.rs`
8. The CLI corpus tier: format, cases, and both implementations wired to it
9. The differential fuzzer
10. Release plumbing: a cross-compilation matrix publishing prebuilt binaries, `action.yml` switched to download one instead of provisioning Python, and the four hook ids

Step ten is gated on the fuzzer rather than on the corpus. Enumerated cases prove the implementations agree about what was anticipated; only the fuzzer speaks to what was not, and shipping a second implementation means shipping the claim that they agree.

## Shipping, and the three channels

The Rust implementation ships. What it ships *through* differs by channel, and conflating them produced a wrong answer once already, so they are separated here.

Measured over twenty runs each, a Rust binary starts in 8.4 ms, a bare interpreter in 12.8 ms, and the interpreter plus this module in 28.2 ms. Shell process creation is common to all three, so the per-invocation saving is about 20 ms, on top of a throughput difference that only shows up on `--all-files` runs. Twenty milliseconds against a hundred commits a day is two seconds a day per developer. That is real, it compounds across a team, and agent-driven work commits far more often than human-driven work does — but it is not on its own the argument for a second implementation.

**Through `pre-commit`, Python stays the default.** `pre-commit` is itself a Python application, so every consumer of it already has an interpreter; a `language: python` hook is close to free for everyone, including Rust shops. A `language: rust` hook builds from source, and a consumer without cargo pays a full rustup toolchain download first. The Rust ids are offered, not recommended, and the audience for them is a repository that already has cargo — where `language: rust` resolves to the system toolchain and the hook costs one small crate build.

**Through the GitHub Action, Rust is strictly better, and the action should use it.** `action.yml` currently provisions Python. Because this project controls that channel it can instead publish prebuilt binaries to GitHub Releases and have the action download one: about a megabyte, no toolchain, no build. That is faster to *install* as well as faster to run, which removes the install-cost objection rather than trading against it. Prebuilt binaries are therefore a planned artifact, not a later optimization, and the release workflow gains a cross-compilation matrix.

**Through direct installation the choice is the consumer's, which is the point of the symmetric naming.** `pip install` and `cargo install` reach the same tool, and a deployment carrying only one of the two runtimes can still have it.

## Non-goals

Configurable ignore globs and comment directives such as `<!-- unwrap-ignore -->` are out of scope. They are wanted, but directive semantics belong in the corpus before a second implementation has to honor them, and adding them mid-port would mean specifying and porting at once.
