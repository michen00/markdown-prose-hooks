# Rust port design

A second implementation of the unwrap, in Rust, answering to the same conformance corpus as the Python one. Both are maintained; neither is a throwaway.

## Why

Two reasons, and they are different in kind. The first is that the corpus was written to be a language-neutral specification and has never been tested as one — a spec with a single implementation is a description of that implementation wearing a spec's clothes. A second implementation is the only thing that proves the corpus says what it means. The second reason is learning Rust, which argues for writing more of it by hand rather than less.

Those two reasons point the same direction more often than not, and where they conflict this document says which one wins.

## Constraints established by measurement

These were verified against the installed `pre-commit` 4.6.0 and the local toolchain rather than assumed, because each one decides part of the design.

**Both manifests must sit at the repository root.** `pre-commit` installs a `language: python` hook with `python -mpip install .` and a `language: rust` hook with `cargo install --bins --root <env> --path .`, both run with `cwd` set to the repository root. Moving `pyproject.toml` into a `python/` directory would break the existing hook, and `Cargo.toml` cannot live in `rust/`. This turns out to cost nothing at all: with both manifests at the root, both languages simply share `src/` and `tests/`, and every Cargo target is autodiscovered.

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

### The naming is symmetric

Hook ids become `unwrap-markdown-prose-py` and `unwrap-markdown-prose-rs`, each with a `-check` variant. The Rust binary is `unwrap-markdown-prose-rs`, distinct from the Python console script — otherwise `cargo install` shadows the Python one on `PATH` and the parity harness has no unambiguous way to name each.

Renaming the existing ids is free today, because the repository has no remote and no consumers, and is a breaking change the moment it has either.

### Ignore configuration is first class

Skipping files must work the same way no matter how the tool was reached. `pre-commit` offers a per-hook `exclude:` regex, but that covers exactly one of the three channels, and a repository configuring exclusions there gets nothing when the same files are processed through the Action or the CLI. Exclusion therefore belongs to the tool.

Two mechanisms, both language-neutral:

- **`.unwrapignore`**, a gitignore-style file read from the working directory, overridable with `--ignore-file PATH`
- **`--exclude GLOB`**, repeatable, applied after the file

Exclusion filters the file list however that list was produced — explicit arguments, `--files-from`, or directory discovery. This is what makes it invocation-independent: `pre-commit` passes filenames explicitly, so a tool that only honored exclusions during its own discovery would ignore them precisely where they are most used. An excluded file is skipped silently and does not trip `--fail-on-change`; exclusion is a statement about scope, not an error.

The format is a deliberately small subset of gitignore, because full fidelity across two hand-written implementations is a parity liability rather than a feature. Blank lines and `#` comments are skipped. `*` matches a run of non-separator characters, `**` matches across separators, `?` matches one non-separator character. A leading `/` anchors to the ignore file's directory; without it a pattern matches at any depth. A trailing `/` restricts to directories. A leading `!` negates, and the last matching pattern wins. Character classes are excluded from the subset.

Nested per-directory ignore files are deferred. Git supports them, and supporting them means specifying precedence between levels in a way both implementations must agree on — worth doing deliberately later, not smuggled in now.

TOML was considered and rejected, on the same grounds `corpus/README.md` rejects YAML for the corpus, but for one reason rather than the two first offered. Rust's standard library has no TOML parser, so a TOML config file costs a dependency in Rust whatever Python does. That is sufficient on its own. The observation that `tomllib` arrived in 3.11 while this floor is 3.10 is true and irrelevant: raising the Python floor would not unlock TOML here, because the Rust side blocks it either way. A line-oriented glob file costs a few lines in any language.

### The Python floor is pegged to pre-commit's

The floor stays at 3.10, and stops being a judgment call: it tracks whatever `pre-commit` itself supports.

The mechanism makes this the right rule rather than a cautious one. `pre-commit` builds a `language: python` hook's environment from the interpreter `pre-commit` is running under — `get_default_version` reads `sys.version_info` of its own process — and `pre-commit` declares `Requires-Python: >=3.10`. A consumer running it under 3.10 therefore gets a 3.10 hook environment by default, and a hook requiring 3.11 fails to install for them. Anything below pre-commit's floor is unreachable; anything above it breaks consumers pre-commit still serves. The floor is checkable rather than arguable, and it moves on its own when pre-commit moves.

Raising it was considered and does not pay. 3.11 buys nothing this codebase uses, now that `tomllib` is known not to unlock TOML. 3.13 buys `Path.read_text(newline=...)`, which removes one `with` block at one call site, and costs 3.12 — the most widely deployed version at the time of writing. One nicer call site is not worth a supported version of reach for a tool that wants adoption.

There is also an answer now for a consumer stuck below the floor, which there was not before: the Rust hook needs no interpreter at all.

### Publishing, and what is deferred

Publishing to PyPI and to crates.io is worth doing on its own merits: `pip install`, `cargo install`, discoverability, and consumers not using `pre-commit` at all.

Mirror repositories are deferred. Their usual justification is download size, and the tracked tree is 181K of which the corpus is 18K — ten percent, not the seventy-four percent a `du` reading suggests, because 154 small files round up to a 4K block each. The shape is recorded here so it is not re-derived later: a Rust mirror is a thin wrapper crate depending on the published crate whose `main.rs` calls into its library, which works only because this design splits `lib.rs` from `main.rs`.

## Layout

```text
Cargo.toml                  a [package] block and nothing else
pyproject.toml              unchanged
.pre-commit-hooks.yaml      four ids: {py,rs} x {write,check}
corpus/cases/<slug>/        transform tier, 51 cases, unchanged
corpus/cli/<slug>/          CLI tier, new
src/                        lib.rs, main.rs, and the Rust modules
src/markdown_prose_hooks/   the Python package, unchanged
tests/                      both languages, cargo and pytest each seeing only their own
```

**The two languages share `src/` and `tests/`, and the payoff is a manifest with no paths in it.** Every target is autodiscovered: `src/lib.rs`, `src/main.rs`, the modules they declare, and the integration tests under `tests/`. `Cargo.toml` needs no `[lib]`, no `[[bin]]`, no `[[test]]`, and no `autotests` key. A manifest that says nothing cannot say anything wrong.

Both directions were verified rather than assumed, because the opposite was asserted first and turned out to be false. Cargo's target discovery is extension-scoped: it takes `lib.rs`, `main.rs`, and whatever they `mod`, and a sibling directory named `markdown_prose_hooks` is invisible to it. Hatchling's `packages = ["src/markdown_prose_hooks"]` names its directory explicitly, so a built wheel contains the two Python files and no `.rs` at all. In `tests/`, cargo sees one target and pytest sees one test.

The crowding argument does not survive contact with the actual file count. The Python package is `unwrap.py` and `__init__.py`; `src/` today holds exactly one entry. A dozen Rust files beside one package directory is a normal `src/`, and separating them would buy tidiness at the cost of five manifest lines that can drift.

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
| `ignore.rs` | the glob subset and the `.unwrapignore` reader |
| `cli.rs`, `main.rs` | argument parsing, file walking, exit codes |

`scan.rs` carries most of the learning: small `fn(&str) -> Option<_>` functions, each independently testable, none of them interesting enough to hide a bug in.

## Known hazards

**Character counts versus byte offsets.** `_BARE_SPEAKER_HEADING_RE` is `^[A-Z][a-zA-Z0-9_. -]{0,39}:$`, where `{0,39}` counts characters. Rust slices bytes. A heading containing any non-ASCII character classifies differently unless the Rust counts `chars()`. This is exactly the drift dual maintenance produces, so it gets a corpus case rather than a comment.

**Line endings.** The tool exists partly to not rewrite CRLF into LF. `split_inclusive('\n')` keeps the terminator attached and slices without allocating, but the `\r` needs handling explicitly. Windows is in the test matrix for this reason alone.

## Parity architecture

Four layers, each covering what the one below cannot.

1. **Rust unit tests** for `scan.rs` and friends. Below the specification's altitude — they pin the matchers, not the behavior — so they stay Rust-native and out of the corpus.
2. **`corpus/cases/`**, run unchanged by both implementations. This is the specification.
3. **`corpus/cli/`**, new, covering the layer the corpus has never reached: argument parsing, file walking, `--write`, `--fail-on-change`, and the ignore rules. Same philosophy as the existing tier — `key: value` metadata, literal files, a `why` that surfaces in the failure.
4. **Differential fuzzing.** A seeded generator assembles documents from a bank of fragments — fence openers, blockquote prefixes, list markers, label lines, table rows, code spans, mixed line endings, hard breaks — and both binaries run each one. Divergence is minimized and **promoted into the corpus**, which is what makes the corpus grow where drift actually lives rather than where it was anticipated.

### The CLI tier's format

```text
corpus/cli/<slug>/
  case.txt      name, why, argv, exit_code
  tree/         the input file tree, copied to a scratch directory before the run
  expected/     the tree as it must look afterward
  stdout.txt    expected stdout, verbatim; absent means empty
```

A case exercising the ignore rules simply puts a `.unwrapignore` in its `tree/`, which needs no new format: the tier already copies an arbitrary file tree and runs in it. That is the whole reason the ignore semantics are specifiable at all.

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
8. The CLI corpus tier: format, cases covering today's behavior, and both implementations wired to it
9. Ignore rules — **specified in the corpus first**, then implemented in Python, then in Rust, as three commits in that order
10. The differential fuzzer
11. Release plumbing: a cross-compilation matrix publishing prebuilt binaries, `action.yml` switched to download one instead of provisioning Python, and the four hook ids

Step nine is the first feature this project builds the way it intends to build all of them, and its ordering is the point rather than a formality. Everything before it ports behavior that already exists, where the corpus is a regression net. Ignore rules do not exist yet in either implementation, so the cases are written against nothing, fail in both languages, and are then made to pass twice. That is what the corpus was for; until now it has only ever been asked to confirm.

It also arrives in the right order relative to publishing. The glob subset becomes a compatibility promise the moment it is released, and specifying it while there are still no consumers costs nothing.

Step eleven is gated on the fuzzer rather than on the corpus. Enumerated cases prove the implementations agree about what was anticipated; only the fuzzer speaks to what was not, and shipping a second implementation means shipping the claim that they agree.

## Shipping, and the three channels

The Rust implementation ships. What it ships *through* differs by channel, and conflating them produced a wrong answer once already, so they are separated here.

Measured over twenty runs each, a Rust binary starts in 8.4 ms, a bare interpreter in 12.8 ms, and the interpreter plus this module in 28.2 ms. Shell process creation is common to all three, so the per-invocation saving is about 20 ms, on top of a throughput difference that only shows up on `--all-files` runs. Twenty milliseconds against a hundred commits a day is two seconds a day per developer. That is real, it compounds across a team, and agent-driven work commits far more often than human-driven work does — but it is not on its own the argument for a second implementation.

**Through `pre-commit`, Python stays the default.** `pre-commit` is itself a Python application, so every consumer of it already has an interpreter; a `language: python` hook is close to free for everyone, including Rust shops. A `language: rust` hook builds from source, and a consumer without cargo pays a full rustup toolchain download first. The Rust ids are offered, not recommended, and the audience for them is a repository that already has cargo — where `language: rust` resolves to the system toolchain and the hook costs one small crate build.

**Through the GitHub Action, Rust is strictly better, and the action should use it.** `action.yml` currently provisions Python. Because this project controls that channel it can instead publish prebuilt binaries to GitHub Releases and have the action download one: about a megabyte, no toolchain, no build. That is faster to *install* as well as faster to run, which removes the install-cost objection rather than trading against it. Prebuilt binaries are therefore a planned artifact, not a later optimization, and the release workflow gains a cross-compilation matrix.

**Through direct installation the choice is the consumer's, which is the point of the symmetric naming.** `pip install` and `cargo install` reach the same tool, and a deployment carrying only one of the two runtimes can still have it.

## Roadmap, and the one non-goal

**Comment directives** — `<!-- unwrap-ignore -->` at line and block level — are next, after publishing. They are deliberately not in this document, for a reason that is about sequencing rather than appetite: unlike ignore globs, directives change the transform itself, so their cases belong in `corpus/cases/` and every one of them is a decision about what the tool *does* to a document rather than which documents it sees. That deserves its own design pass, not a paragraph at the end of this one.

The questions it will have to answer are worth naming now so they are not rediscovered: whether a block directive nests, what closes one that is never closed, whether a directive inside a fenced code block is inert, and whether the directive comment itself survives into the output. None of those have obvious answers, and all of them are cheap to settle in the corpus and expensive to settle twice in two languages.

By then the arrangement this document builds is exactly what makes that work safe. Directives get specified once and implemented twice against the same cases, which is the steady state the second implementation exists to create.

The single non-goal is **correcting the code-span approximation**. It is a change to the specification rather than to either implementation, and folding it into the port would disguise a deliberate behavior change as a translation.
