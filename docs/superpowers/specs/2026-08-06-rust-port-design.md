# Rust port design

A second implementation of the unwrap, in Rust, answering to the same conformance corpus as the Python one. Both are maintained; neither is a throwaway.

## Why

Two reasons, and they are different in kind. The first is that the corpus was written to be a language-neutral specification and has never been tested as one — a spec with a single implementation is a description of that implementation wearing a spec's clothes. A second implementation is the only thing that proves the corpus says what it means. The second reason is learning Rust, which argues for writing more of it by hand rather than less.

Those two reasons point the same direction more often than not, and where they conflict this document says which one wins.

## Constraints established by measurement

These were verified against the installed `pre-commit` 4.6.0 and the local toolchain rather than assumed, because each one decides part of the design.

**Both manifests must sit at the repository root.** `pre-commit` installs a `language: python` hook with `python -mpip install .` and a `language: rust` hook with `cargo install --bins --root <env> --path .`, both run with `cwd` set to the repository root. Moving `pyproject.toml` into a `python/` directory would break the existing hook, and `Cargo.toml` cannot live in `rust/`. This turns out to cost nothing at all: with both manifests at the root, both languages simply share `src/` and `tests/`, and every Cargo target is autodiscovered.

**One of the nineteen patterns cannot be a regex in Rust.** A scan of every pattern constant found exactly one using constructs the `regex` crate excludes by design: `_SUB_CODE_SPAN`, which needs both a backreference and a negative lookahead. It must be hand-written whatever else is decided.

**Dependencies are expensive for consumers.** A crate with `regex = "1"` compiles ten crates in 6.6 s; an empty crate compiles one in 0.12 s. `pre-commit` does not pass `--locked`, so a consumer does not even get lockfile-pinned versions in exchange.

**A lib-only crate cannot back a mirror repository.** `cargo install --bins --path .` on a crate with no binary fails with `error: no packages found with binaries or examples`, and `pre-commit` always installs the hook repository's own crate.

## Decisions

### Zero dependencies

The Rust crate takes no dependencies, matching the Python package's own promise. Eighteen of the nineteen patterns are mostly anchored, mostly literal matches that hand-write in a few lines each and run faster than a regex engine can dispatch; the nineteenth cannot use the crate anyway. Argument parsing is hand-written for the same reason.

This is the decision where learning and shipping agree. Hand-written scanners are where the Rust actually is — slices, `char_indices`, `strip_prefix`, exhaustive `match` — and they are also what keeps the hook cheap to install.

The cost is honest: the port stops being mechanical. With `regex` it would be a transliteration. Without it, every matcher is a small design problem, and the corpus is what makes that trade safe.

### Parity means matching Python, not matching CommonMark

`_SUB_CODE_SPAN` is an approximation. Against `` `a``` `` it matches `` `a` ``, closing on the first backtick of a three-run, where CommonMark requires a span opened with a one-backtick run to close on a run of exactly one. The corpus pins the Python's behavior, so the Rust scanner reproduces the approximation rather than correcting it.

Correcting it is a separate change to the specification, made in the corpus first and then in both implementations. Doing it silently inside the port turns a spec question into what looks like a Rust bug.

### The naming is symmetric

Hook ids become `unwrap-markdown-prose-py` and `unwrap-markdown-prose-rs`, each with a `-check` variant. The Rust binary is `unwrap-markdown-prose-rs`, distinct from the Python console script — otherwise `cargo install` shadows the Python one on `PATH` and the parity harness has no unambiguous way to name each.

The rename landed with the four ids, before the first tag. It was free at that point and is a breaking change from the first one: a consumer pinning a `rev` pins the ids at that rev, so an id that changes afterward breaks their configuration rather than theirs changing under them.

### The symmetry stops at the Action: one, not two

Four hook ids and one action is not an oversight, and the question is worth answering here because the shape of the hooks invites the opposite conclusion.

The hooks are split because the install cost differs per consumer and persists. `pre-commit` is itself a Python application, so a `language: python` hook reuses an interpreter every consumer of the framework already has; a `language: rust` hook runs `cargo install` from source into pre-commit's cache, and a consumer without cargo pays a full toolchain download before the first commit is checked. Which side of that a repository sits on is knowable only to that repository, so exposing both and recommending one is the honest arrangement.

None of that survives the move to a runner. The runner is provisioned fresh for every job, so nothing is already there in the sense that matters; a prebuilt binary of about a megabyte installs faster than either toolchain provisions; and there is no cache persisting between runs for a from-source build to amortize against. The Rust path is not a trade in this channel, it is dominant — which is the same observation that makes rewriting `action.yml` worth doing at all.

So a second action would offer a choice that is strictly worse on one side, and — because the corpus guarantees both implementations emit the same bytes — carries no behavioral meaning on either. That is the worst kind of option: real maintenance cost, no information content. A repository's root `action.yml` is also the repository's action, so a second one needs a subdirectory that consumers have to know about, for nothing.

What the channel does need is a fallback rather than a choice. A runner on a platform with no published binary must still work, so the action detects and falls back to `pip install` of the Python package. An `implementation` input taking `auto`, `rust` or `python` sits on top of that, defaulting to `auto`: the explicit values exist for pinning behavior deliberately or for isolating a suspected divergence, not for routine use. The `python-version` input then governs only the Python path, and says so.

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

### Publishing, and the mirror repositories

Publishing to PyPI and to crates.io is worth doing on its own merits: `pip install`, `cargo install`, discoverability, and consumers not using `pre-commit` at all.

**Two mirror repositories, one per implementation, and this repository stops serving hook ids when they land.** `markdown-prose-hooks-py` carries the two `-py` ids and the Python package; `markdown-prose-hooks-rs` carries the two `-rs` ids and a thin wrapper crate depending on the published crate, whose binary calls into that crate's library — a shape that works only because this design keeps `lib.rs` separate from the binary, and one that cannot exist until there is a crate to depend on.

The measurement that decides it is what `pre-commit` downloads, and it is not what an earlier draft of this section assumed. `pre-commit` shallow-clones a hook repository at `--depth=1` for a tag rev, so history is not the cost and the tree at that rev is: 1442K across 432 files, of which 373 are corpus fixtures and 397K is `docs/`, 239K of that being the benchmark notebook and its charts. It was 1224K when this was written, and the notebook is what grew it, which strengthens the same conclusion rather than weakening it. A Python shop pinning this repository takes 172K of Rust it will never read; a Rust shop takes the Python package and the same fixtures. The mirrors deliver roughly 60K and 10K.

That earlier draft argued the opposite — defer, and one mirror rather than two — and both arguments are recorded here as errors, because the shape of each generalizes. The first answered *is the gain large?* when the question was *what does the gain cost?*; a lighter delivery is a gain, and forgoing one needs a sacrifice on the other side rather than a small numerator. The second held that a single mirror is less to keep in sync, which is a claim about our convenience wearing the clothes of a claim about the consumer's — and it still hands a Rust user the Python files, which is the one thing a mirror exists to prevent.

Retiring this repository's own `.pre-commit-hooks.yaml` is the part carrying an expiry date. `repo:` is a URL rather than a version, so a consumer who adopts this repository and later finds the ids gone has a configuration edit rather than a `rev` bump. While nobody is pinned that costs nothing, which is what the `0.0.x` series is for; after `v0.1.0` it is a breaking change to somebody real. The same reasoning that put the id rename before the first tag puts this before the first tag anybody is asked to trust.

The order is therefore forced rather than chosen, though the numbers along it are not. The first tag that publishes cleanly proves the release machinery, and is also the first moment a crate exists for the `-rs` mirror to depend on; the mirrors are then built and the next patch tag exercises them end to end; `v0.1.0` is the first tag anybody is pointed at, with the ids served only from the mirrors and this repository's manifest gone. How many `0.0.x` tags that takes is a question about how many attempts the machinery needs, and the `0.0.x` series exists so that the answer can be more than one; naming a number here would only produce a document that disagrees with the tags.

What this repository is afterward is then unambiguous: the specification, both implementations, the action, and the generator that produces the mirrors. The mirrors are generated on tag and never hand-edited, because a hook manifest maintained in two places is a manifest that eventually disagrees with itself.

The crate's `include` key is load-bearing for the `-rs` mirror rather than a tidiness measure. Without it the crate ships the whole repository — 432 files and 1.4 MiB — so a consumer who cloned a 10K mirror would pull all of it down at `cargo install` time, and the mirror would have bought them nothing.

## Layout

```text
Cargo.toml                  a [package] block and nothing else
pyproject.toml              unchanged
.pre-commit-hooks.yaml      four ids: {py,rs} x {write,check}
corpus/cases/<slug>/        transform tier, 54 cases; 51 when this was written
corpus/cli/<slug>/          CLI tier, new
src/                        lib.rs, bin/unwrap-markdown-prose-rs.rs, and the Rust modules
src/markdown_prose_hooks/   the Python package, unchanged
tests/                      both languages, cargo and pytest each seeing only their own
```

**The two languages share `src/` and `tests/`, and the payoff is a manifest with no paths in it.** Every target is autodiscovered: `src/lib.rs`, the modules it declares, the binary under `src/bin/`, and the integration tests under `tests/`. `Cargo.toml` needs no `[lib]`, no `[[bin]]`, no `[[test]]`, and no `autotests` key. A manifest that says nothing cannot say anything wrong.

The binary lives at `src/bin/unwrap-markdown-prose-rs.rs` rather than at `src/main.rs`, and that is what buys the bare manifest rather than a stylistic preference. An autodiscovered `src/main.rs` takes the *package* name, so it would build `markdown-prose-hooks` and the symmetric naming would need a `[[bin]]` block to override it. A file under `src/bin/` takes its own filename instead. Verified against the command `pre-commit` actually runs: `cargo install --bins --root <env> --path .` installs exactly `unwrap-markdown-prose-rs` and nothing else.

Both directions were verified rather than assumed, because the opposite was asserted first and turned out to be false. Cargo's target discovery is extension-scoped: it takes `lib.rs`, `main.rs`, and whatever they `mod`, and a sibling directory named `markdown_prose_hooks` is invisible to it. Hatchling's `packages = ["src/markdown_prose_hooks"]` names its directory explicitly, so a built wheel contains the two Python files and no `.rs` at all. In `tests/`, cargo sees one target and pytest sees one test.

The crowding argument does not survive contact with the actual file count. The Python package is `unwrap.py` and `__init__.py`; `src/` today holds exactly one entry. A dozen Rust files beside one package directory is a normal `src/`, and separating them would buy tidiness at the cost of five manifest lines that can drift.

## Modules

The Python is one file, 1204 lines as this is written. That suits Python and does not suit learning Rust, so the port decomposes into units that can each be understood and tested alone.

| module | responsibility |
| -- | -- |
| `scan.rs` | the structural matchers: fence, blockquote and its prefix, list markers, setext, thematic break, link reference, HTML tag name, GFM alert |
| `code_span.rs` | the backreference matcher, alone, because it is the subtle one |
| `label.rs` | label, speaker, and bracketed-line classification |
| `links.rs` | link-only lines and link-block indexes |
| `paragraph.rs` | the accumulator and the row-wise flush |
| `transcript.rs` | `is_transcript_like_markdown` |
| `ignore.rs` | the glob subset and the `.unwrapignore` reader |
| `cli.rs`, `bin/unwrap-markdown-prose-rs.rs` | argument parsing, file walking, exit codes |
| `fuzz.rs` | the seeded generator and its fragment bank, which `examples/fuzz.rs` drives |

`scan.rs` carries most of the learning: small `fn(&str) -> Option<_>` functions, each independently testable, none of them interesting enough to hide a bug in.

## Known hazards

Each of these was established by running the reference interpreter, and two of them correct an earlier draft of this section that named the wrong pattern.

**Character counts versus byte offsets.** The hazard is real and the example first given for it was not. `_MATCH_BARE_SPEAKER_HEADING` is `^[A-Z][a-zA-Z0-9_. -]{0,39}:$`, and `{0,39}` does count characters — but it counts them over an ASCII-only class, so a non-ASCII heading is rejected by the character class and never reaches the quantifier. `'A' + 'é' * 39 + ':'` does not match, and neither would a byte-counting port.

The one pattern that carried both halves was `_MATCH_TIMESTAMPED_SPEAKER_HEADING`, `^[A-Z][a-zA-Z0-9_.-]{0,19} \d{1,2}:\d{2}$`, whose counted quantifiers ranged over `\d` — Unicode `Nd` on a `str` pattern — so `MC ٠:١٥` and `MC १२:३३` both matched, and a Devanagari digit is three bytes to one character. The fourth specification change below removes it: with the digits narrowed to `[0-9]`, **every counted quantifier over a character class in this tool now ranges over an ASCII class**, which is what makes a byte-counting port safe rather than merely lucky. The remaining `{n,m}` quantifiers count *group repetitions* (`_MATCH_THEMATIC`, `_MATCH_SPEAKER_PREFIX`), which is not a character count in either language.

Character-versus-byte reasoning still applies where the port slices rather than counts, and one place is worth naming because the narrowing quietly fixed it too: `match_list_marker` returns `content_col` from `match.end()`, a character index. Its pattern is now ASCII throughout — a bounded run of ASCII spaces, then `[-+*]|[0-9]+[.)]`, then one or more ASCII spaces — so the index is the same number either way. Before the narrowing it was not.

**`\s` is Unicode, and Rust's nearest equivalent is the wrong set.** `\s` and `str.strip()` share one definition of 29 code points, which is the Unicode `White_Space` property *plus* the four C0 separators `U+001C`–`U+001F`. Rust's `char::is_whitespace` omits those four, so `str::trim` is not `str.strip()` and must not be used to port it. Unlike `\d`, this set is stable: it is byte-identical on 3.10 and 3.13, so it is ported as written rather than narrowed.

**Line endings, and what counts as a line at all.** The tool exists partly to not rewrite CRLF into LF. `split_inclusive('\n')` keeps the terminator attached and slices without allocating, but the `\r` needs handling explicitly, and Windows is in the test matrix for this reason.

The larger trap is that `split_inclusive('\n')` and `str.splitlines(keepends=True)` are not the same function, which an earlier draft of this document assumed they were. `splitlines` breaks on ten boundaries — `\n`, `\r`, `\r\n`, `\v`, `\f`, `U+001C`, `U+001D`, `U+001E`, `U+0085`, `U+2028`, `U+2029` — eight of which a `\n` splitter never sees. The divergence is not theoretical: `alpha wrapped\vbeta wrapped\n\ntail\n` is two prose lines to Python, which joins them *and deletes the `\v`*, because the join runs `strip()` and `\v` is whitespace to Python. A `\n`-splitting port sees one line and emits the input unchanged. Silent deletion of a character is the worse of the two behaviors, so this is a specification question and not a porting detail.

## Four specification changes the port found

Deriving the port turned up four places where the Python's behavior is not what anyone would specify, and each had to be settled before the Rust could be written against it. Each is a change to the specification, so each goes into the corpus first and into both implementations after — the same discipline the code-span approximation is held to, applied to cases where the answer is that the current behavior is wrong.

That these surfaced before a line of Rust exists is the second implementation paying for itself early. None of them is a porting detail; each is a question the single implementation never had to answer.

**A line boundary is `\n`, `\r\n`, or `\r`.** `str.splitlines` recognizes ten, and the extra seven produce a bug rather than a feature: `alpha wrapped\vbeta wrapped` becomes `alpha wrapped beta wrapped`, joined as two prose lines *and* with the `\v` deleted, because the join calls `strip()` and `\v` is whitespace. Silent character deletion is worse than not unwrapping. The Python narrows to the three Markdown boundaries, which was measured against the whole corpus before being chosen: over all 51 cases — inputs and expected outputs both — plus every tracked Markdown file in the repository, 106 distinct files, the narrowed splitter produces byte-identical output and identical counts. Nothing the corpus pins today depends on the other seven. The narrow rule is also the version-stable one, since the boundary set is a property of the interpreter rather than of this tool.

**An ordered list marker is ASCII `0-9`.** `\d` on a `str` pattern is the runtime's `Nd` category, and the fourth change is the one the port could not have merely ported: the Python did not agree with itself. `\d` selects 650 code points on 3.10's Unicode 13.0 and 680 on 3.13's 15.1, and both interpreters are in this repository's own test matrix, so "match the Python" was not a defined target — a second implementation would have had to pin a Unicode version to agree with either one. CommonMark settles it in the other direction anyway: an ordered list marker is "a sequence of 1–9 arabic digits (0-9)", so no renderer ever read `١. x` as a list, and matching one only declined to unwrap prose that renders as prose. Measured over the 360 distinct lines in both corpus tiers, narrowing `_MATCH_LIST`, `_MATCH_LIST_MARKER` and `_MATCH_TIMESTAMPED_SPEAKER_HEADING` to `[0-9]` changes nothing the corpus already pins. It also deletes a 61-range table from the Rust in favor of one comparison, and the timestamp pattern was internally inconsistent before it: its speaker half is `[A-Z]`, ASCII by construction.

**An unreadable file is reported, not raised.** `main` catches `UnicodeDecodeError` and nothing else, so a file the process cannot open exits 1 through a traceback with empty stdout — verified against a mode-`000` file. A formatter must not do that, and a traceback is not specifiable in the CLI tier except as a case asserting a crash. Both implementations gain an `errors[]` entry and keep exit 1.

That fix wrapped the read and not the three stat calls in front of it, and the port found the gap it left. `Path.is_symlink` re-raises anything outside its own ignore list of `ENOENT`, `ENOTDIR`, `EBADF` and `ELOOP`, so a path too long for the filesystem still escaped through a traceback — abandoning every path after it, which is the precise failure the errors list exists to prevent one level down. The Rust skipped it silently, because a failed `symlink_metadata` is just a path it cannot show to be a regular file. That reading is now the specification: **a path the tool cannot stat is out of scope the way a missing one is**, skipped silently and with the files named beside it still formatted. Reporting it instead was the alternative and was declined, because nothing at that point can tell an over-long name from a name that simply does not exist, and the second is already silent. `corpus/cli/a-path-too-long-to-stat-is-skipped-silently` pins it.

**Error strings are the tool's vocabulary, not the operating system's.** They travel in the `--json` payload on stdout, which the parity boundary requires to match byte for byte, and they cannot: Python renders `[Errno 2] No such file or directory: 'x'` where Rust's `io::Error` renders `No such file or directory (os error 2)`. Neither is portable across platforms or locales either — the same errno carries different prose on Linux, macOS and Windows. Both implementations therefore emit a fixed string naming the condition rather than quoting the OS, which is what lets the corpus pin it at all.

The vocabulary belongs to neither language, and that is deliberate. `PermissionError` would privilege Python and make Rust spell out a class name it does not have; `PermissionDenied` would do the reverse. A phrase maps cleanly from Python's exception classes and from Rust's `io::ErrorKind` alike:

| condition | phrase | Python | Rust |
| -- | -- | -- | -- |
| the path does not exist | `not found` | `FileNotFoundError` | `ErrorKind::NotFound` |
| the process may not open it | `permission denied` | `PermissionError` | `ErrorKind::PermissionDenied` |
| it is a directory | `is a directory` | `IsADirectoryError` | `ErrorKind::IsADirectory` |
| a path component is not a directory | `not a directory` | `NotADirectoryError` | `ErrorKind::NotADirectory` |
| the bytes are not UTF-8 | `not valid UTF-8` | `UnicodeDecodeError` | `Utf8Error` |
| anything else | `unreadable` | any other `OSError` | any other `ErrorKind` |

The two messages carrying it are `{path}: cannot read ({phrase})` and `{path}: cannot read --files-from ({phrase})`. Anything unrecognized answers `unreadable` rather than leaking a message, because an open-ended tail is an open-ended parity risk — one unmapped errno on one platform and the tier goes red for a reason that has nothing to do with the tool.

`ErrorKind::IsADirectory` and `NotADirectory` stabilized in Rust 1.83, which is below the 1.86 floor, so the mapping costs nothing at the MSRV.

## The one divergence that could not be removed

The four changes above all end the same way: the specification moves, both implementations follow, and the corpus pins the result. One question the port raised cannot end that way, and it is recorded here rather than left to be rediscovered at a red job.

argparse decides whether a `-`-leading token is an option or a positional partly by asking whether it looks like a negative number, and its `_negative_number_matcher` is `^-\d+$|^-\d*\.\d+$`. That `\d` is the same Unicode `Nd` category the fourth change removed from this tool's own patterns, carrying the same defect: 650 code points on 3.10 and 680 on 3.13. So `--json -١٢` binds `-١٢` as a *path* under CPython, and which non-ASCII digits do that depends on the interpreter.

The pattern belongs to the standard library rather than to this tool, so narrowing it the way `_MATCH_LIST` was narrowed is not available. It could be overwritten — it is an instance attribute — and that was rejected: it trades a rare, documented divergence for a silent breakage on any interpreter that renames or restructures a private attribute, which is the worse failure of the two. Reproducing Unicode `Nd` on the Rust side is not available either, since Rust's tables carry their own Unicode version and would drift against CPython's in the same way.

The resolution is to state the boundary rather than to close it. The Rust matches `^-[0-9]+$|^-[0-9]*\.[0-9]+$`. Every ASCII spelling agrees — `-12`, `-0`, `-1.5`, `-.5` are paths in both, `-5.` and `-1a` are unknown options in both — and `corpus/cli/a-negative-number-argument-is-a-path` pins that half. A token whose digits are not ASCII is a path under Python and an unknown option under Rust, and no corpus case pins it, because there is no answer both implementations can give.

The practical reach of this is a file literally named `-١٢` passed as a bare argument. It is unreachable through the `pre-commit` and Action channels, which never pass a `-`-leading token, and `--` in front of it makes both implementations agree.

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

One commit per step. From step six onward the corpus is the gate.

**Ignore rules come before the port, not after it.** They are needed as soon as this repository dogfoods its own tool across more than one channel, which it already does and which is already failing, and a formatter that rewrites its own fixtures turns a suite green against nothing.

1. Broaden the hook config's `exclude` from `^corpus/cases/` to `^corpus/`, ahead of any case tier that does not exist yet
2. The CLI corpus tier: format, harness, and cases covering today's behavior, run against Python alone
3. The three specification changes above — cases in both tiers first, then the Python
4. Ignore rules — cases in the corpus first, then the Python implementation, then a root `.unwrapignore` holding `corpus/` — **`main` goes green here**
5. Cargo scaffold, `.gitignore` for `target/`, CI skeleton, and one deliberately failing corpus test that proves the harness reads the corpus at all
6. `scan.rs` and its unit tests
7. `code_span.rs`, including the approximation
8. `label.rs` and `links.rs`
9. `paragraph.rs` and the line state machine — **the transform tier turns green here**
10. `transcript.rs`
11. `cli.rs`, `ignore.rs`, and the binary
12. The CLI tier parameterized over both binaries — **the CLI tier turns green here**
13. The differential fuzzer
14. Release plumbing: a cross-compilation matrix publishing prebuilt binaries, `action.yml` switched to download one instead of provisioning Python, and the four hook ids

Step one is first because the gap is real and currently open: the existing `exclude` names `corpus/cases/` specifically, so the CLI tier's fixture Markdown would be rewritten by this repository's own hook the moment it lands. Widening the pattern before the directory exists costs one character and closes a window rather than discovering it.

What it does not do is close the *other two* windows, and the first push to the remote proved it by turning `main` red on two jobs the same afternoon this was written. `pre-commit try-repo` synthesizes a configuration holding nothing but the hook id, so `.pre-commit-config.yaml` — and therefore its `exclude` — is never read; the `hook` job rewrote twenty-six `input.md` files. The `action` job defaults to `git ls-files '*.md'`, has no exclusion mechanism at all, and reported the same twenty-six, whereupon its `fail-on-change` gate did exactly what it exists to do.

So step one governs `pre-commit run` in this repository and nothing else, which is one channel of three and neither of the two that are failing. That is the ignore-configuration decision above restated as a bug report, and it is worth recording as evidence rather than as principle: the design claimed a per-hook `exclude` reaches one channel, and the first thing that ever exercised the other two agreed. `main` stays red until step four, which is the correct amount of time — a stopgap would be a commit written to be reverted, and the real fix is three steps away.

Step one keeps its place regardless, because `exclude` is what holds the corpus back from the *other* hooks in `.pre-commit-config.yaml`. Those know nothing about `.unwrapignore` and would still normalize a CRLF fixture or eat the two trailing spaces a hard-break case is made of.

Step four is the first feature this project builds the way it intends to build all of them, and the ordering is the point rather than a formality. Everything around it ports or ships behavior that already exists, where the corpus is a regression net. Ignore rules exist nowhere yet, so the cases are written against nothing, fail, and are then made to pass — twice, months apart, by two languages that never see each other. What was lost by moving it earlier is only that the two failures are no longer simultaneous, which was never the part that mattered. Specified-before-implemented is.

It also lands in the right order relative to publishing. The glob subset becomes a compatibility promise the moment it is released, and settling it while there are no consumers costs nothing.

Building the CLI tier at step two against one implementation and generalizing it at step twelve is deliberate. A harness that must serve two implementations before it has served one is being designed against a guess.

Step fourteen is gated on the fuzzer rather than on the corpus. Enumerated cases prove the implementations agree about what was anticipated; only the fuzzer speaks to what was not, and shipping a second implementation means shipping the claim that they agree.

## Shipping, and the three channels

The Rust implementation ships. What it ships *through* differs by channel, and conflating them produced a wrong answer once already, so they are separated here.

Measured over twenty runs each, a Rust binary starts in 8.4 ms, a bare interpreter in 12.8 ms, and the interpreter plus this module in 28.2 ms. These were re-measured properly in [benchmarks.ipynb](../../benchmarks.ipynb), which reproduces them and is the place to look for current figures; the numbers here are left as the estimate the design was made on rather than updated, because two places quoting a measurement is how one of them goes stale. Shell process creation is common to all three, so the per-invocation saving is about 20 ms, on top of a throughput difference that only shows up on `--all-files` runs. Twenty milliseconds against a hundred commits a day is two seconds a day per developer. That is real, it compounds across a team, and agent-driven work commits far more often than human-driven work does — but it is not on its own the argument for a second implementation.

**Through `pre-commit`, Python stays the default.** `pre-commit` is itself a Python application, so every consumer of it already has an interpreter; a `language: python` hook is close to free for everyone, including Rust shops. A `language: rust` hook builds from source, and a consumer without cargo pays a full rustup toolchain download first. The Rust ids are offered, not recommended, and the audience for them is a repository that already has cargo — where `language: rust` resolves to the system toolchain and the hook costs one small crate build. The ids are served from the two mirror repositories rather than from here, so the choice is made once in the `repo:` line rather than per id, and a consumer never downloads the implementation they did not pick.

**Through the GitHub Action, Rust is strictly better, and the action should use it.** `action.yml` currently provisions Python. Because this project controls that channel it can instead publish prebuilt binaries to GitHub Releases and have the action download one: about a megabyte, no toolchain, no build. That is faster to *install* as well as faster to run, which removes the install-cost objection rather than trading against it. Prebuilt binaries are therefore a planned artifact, not a later optimization, and the release workflow gains a cross-compilation matrix.

**Through direct installation the choice is the consumer's, which is the point of the symmetric naming.** `pip install` and `cargo install` reach the same tool, and a deployment carrying only one of the two runtimes can still have it.

## Roadmap, and the one non-goal

**Comment directives** — `<!-- unwrap-ignore -->` at line and block level — are next, after publishing. They are deliberately not in this document, for a reason that is about sequencing rather than appetite: unlike ignore globs, directives change the transform itself, so their cases belong in `corpus/cases/` and every one of them is a decision about what the tool *does* to a document rather than which documents it sees. That deserves its own design pass, not a paragraph at the end of this one.

The questions it will have to answer are worth naming now so they are not rediscovered: whether a block directive nests, what closes one that is never closed, whether a directive inside a fenced code block is inert, and whether the directive comment itself survives into the output. None of those have obvious answers, and all of them are cheap to settle in the corpus and expensive to settle twice in two languages.

By then the arrangement this document builds is exactly what makes that work safe. Directives get specified once and implemented twice against the same cases, which is the steady state the second implementation exists to create.

The single non-goal is **correcting the code-span approximation**. It is a change to the specification rather than to either implementation, and folding it into the port would disguise a deliberate behavior change as a translation.
