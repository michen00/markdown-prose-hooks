# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

One tool, two implementations, one specification. The reasoning behind the corpus, the hooks and the release flow lives in [CONTRIBUTING.md](CONTRIBUTING.md), in [README.md](README.md), and in the comments of the config files themselves; this file holds what those cannot tell you. The repository is in rapid development with a sole maintainer, so the shortest correct path is the wanted one.

## Commands

| what | command |
| -- | -- |
| Install dependencies and the git hooks, once per clone | `make develop` |
| The gate before calling anything done | `make check` |
| Python suite | `make test` |
| One Python test | `uv run python -m pytest tests/test_unwrap.py::test_name` |
| One corpus case, either tier | `uv run python -m pytest -k <case-slug>` |
| Python suite on the version floor | `make floor` |
| Rust suite, and one Rust test | `make rust-test`, `cargo test scan::tests::name` |
| The CLI tier against both implementations | `make parity` |
| The hook the way a consumer resolves it | `make hook-test` |
| The CLI tier against what a registry serves | `gh workflow run smoke.yml -f tag=<tag>` |
| The differential fuzzer | `cargo run --release --example fuzz` |

`make check` runs tidy, the Python suite, the suite again on 3.10, the Rust lint and suite, and `parity`. Read its output rather than its exit code. `make help` lists every target.

## Architecture

**The corpus is the specification; neither implementation is.** `corpus/` is what makes cross-language parity checkable rather than asserted, and a change to what gets joined is a corpus case first. Two tiers, because a document cannot describe a process: `corpus/cases/` pins the transform by calling `unwrap_markdown_prose` directly, and `corpus/cli/` pins argument handling, file discovery, exit codes, stdout and the ignore rules by running a binary. Both implementations answer both tiers.

**The two implementations are decomposed differently on purpose.** The Python is one module, `src/markdown_prose_hooks/unwrap.py`: pattern constants, a paragraph accumulator, and the CLI. The Rust is one module per concern — `scan`, `code_span`, `label`, `links`, `paragraph`, `transcript`, `ignore`, `cli` — each a set of small matchers testable alone, with the binary at `src/bin/unwrap-markdown-prose-rs.rs`. Neither takes a dependency beyond its standard library, in either language.

**Parity beyond what anyone anticipated** comes from `examples/fuzz.rs`, which generates file trees and compares exit code, stdout and the whole resulting tree between the two binaries. A divergence it finds becomes a corpus case before it becomes a fix, because the generator's fragment bank renames every seed the moment it moves.

**Three invocation channels share the CLI and nothing else:** the four hook ids in `.pre-commit-hooks.yaml`, the composite action in `action.yml`, and the two commands, one per implementation. A green test suite says nothing about whether the manifest resolves or the action runs, which is why CI carries `hook` and `action` jobs. It also explains why exclusion belongs to the tool — `.unwrapignore` and `--exclude` reach all three, while `pre-commit`'s own `exclude:` key reaches one.

**Nothing but `smoke.yml` tests what a registry serves.** Every other job builds the thing it tests, so a wheel missing a module, or a crate that will not compile from its own package, would publish green. That workflow installs from PyPI and from crates.io, checks the released binaries against `SHA256SUMS`, and runs the CLI tier against all three; the release flow calls it after every publish and a weekly schedule calls it again. It gates nothing, because by the time it runs the version number is spent. Its two footholds in the harness are `RUST_BINARY` and `REQUIRE_INSTALLED_PACKAGE`, and it takes the harness from the ref it runs on while taking the corpus from the tag — the switches may postdate a tag, and the specification a version was published against may not be replaced by a later one.

**Two version floors are promises rather than preferences.** `requires-python = '>=3.10'` tracks what `pre-commit` itself supports, and `make floor` plus the CI matrix keep it honest. `rust-version = "1.86"` and the toolchain CI pins move together, which is why `dependabot.yml` holds `dtolnay/rust-toolchain` out of its actions group.

Both registries carry the package and the hook ids resolve from a tag; the first release was `v0.0.1`. What is still provisional, and what each thing becomes as the remaining stages land, are tracked in [docs/post-release-checklist.md](docs/post-release-checklist.md). Each one is marked in place with a `DEVIATION, blocked on` comment, and [docs/benchmarks.ipynb](docs/benchmarks.ipynb) collects those comments by reading them rather than by restating them.

## Ground rules

- **Land on `main` directly.** Do not open a pull request for your own work, do not create a branch, and do not ask whether to. Commit to `main` and push. The push will report bypassed rule violations — that is the configured outcome, not a warning to act on.
- **Wield repo admin liberally.** The branch ruleset carries a `bypass_actors` entry for the admin role; `gh pr merge --admin` and direct pushes are both sanctioned.
- **Pull requests exist for the bots.** `dependabot[bot]` and `pre-commit-ci[bot]` stay gated on the full check set, because `bot-automerge.yml` needs something to wait on. Never relax those gates to make a bot PR land.
- **Direct-to-main is not permission to skip verification.** Run `make check` before you call a change done.
- Commit atomically with Conventional Commits: imperative, lowercase, 50 characters or fewer in the subject, 72 in the body.
- The ruleset requires twelve contexts, and the Rust jobs are not among them. A red `rust-lint`, `rust-test` or `parity` does not stop a merge, so it is on you to read them.

## You are probably not the only agent in this tree

More than one session works this repository at once, and `HEAD` can move underneath you mid-task.

- Re-read `git status` rather than trusting a snapshot from earlier in your session.
- Stage explicit paths. Never `git add -A`, `git add .`, or `git commit -a` — you will sweep up another session's half-finished work and commit it under your own message. A path staged by an attempt that the commit gate rejected is still staged for your next commit; check what is in the index before committing again.
- Never `git checkout --`, `git stash`, or `git restore` a file you did not modify. Check `git diff` for that path first; if the change is not yours, leave it alone.
- If your edits land inside someone else's commit, that is fine. Say so and move on rather than trying to unpick it.
- The benchmark notebook times processes a few milliseconds long. Do not re-execute it while another session is working, and do not run a suite alongside it: the run reports a busy machine as a failed check.

## Claims in docs are measured, not remembered

Any statement about a measurement or about the state of this repository must be produced by recomputing it. Figures in prose carry the value on the day they were written, so recompute before editing one, and say in the commit message that it was re-measured. The notebook is the model: every figure in it comes from the cell above it, and cells that state a result also check it.

Some of those figures are quoted from files rather than restated, so an edit to a quoted comment only reaches the notebook through a run. Re-execute it with the command in [CONTRIBUTING.md](CONTRIBUTING.md#the-benchmark-notebook), which names the kernel deliberately: without that, nbconvert runs whichever kernel the notebook's own metadata names, and an editor rewrites that metadata.

## Two spell gates, not one

`typos` and `codespell` both run, and they divide the work: `typos` handles misspellings and splits identifiers, `codespell` adds the American-spelling dictionary `typos` has no equivalent for. House spelling is US English.

Their ignore directives are not interchangeable and both demand the end of the line, so no single comment silences both. Where a false positive needs documenting, describe it rather than quoting it. See [.codespellrc](.codespellrc) and [_typos.toml](_typos.toml).

## Traps worth knowing before you hit them

- **The commit-message gate reads the message, not only the diff.** `codespell` and `gitlint` both run at `commit-msg`, so a message quoting a corpus fixture name can be rejected as a misspelling — a name like `note.md` with a letter dropped, or a glob putting `?` inside a word. Describe such a token instead of quoting it, and keep body lines to 72 characters.
- **`corpus/` is fixture bytes, not prose.** Its cases pin trailing spaces and CRLF on purpose, and this repository runs its own reflowing hook over `types: [markdown]`. Never let a tidying tool near it, and never hand-edit an answer key to make a test pass.
- **Answer keys are generated, not written.** For the CLI tier, `REGENERATE_CLI_CORPUS=1 uv run python -m pytest tests/test_cli_corpus.py -k <slug>` rewrites `expected/` and `stdout.txt` from what the reference run did; `exit_code` in `case.txt` stays the one expectation you state rather than observe. The transform tier has no such path, so produce those keys by running the tool and reviewing the diff.
- **`pre-commit` refuses to run while `.pre-commit-config.yaml` is modified but unstaged.** If you are committing a hook change alongside other work, order the commits so the config change is staged when the hook runs.
- **A `.unwrapignore` pattern ending in `/` covers the whole subtree.** `corpus/cli/README.md` is excluded along with the tier's fixtures, which is why only the top-level `corpus/README.md` is in scope for the repository's own hook.
