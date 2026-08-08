# Contributing

## Setup

```bash
make develop
```

That installs dependencies with [uv](https://docs.astral.sh/uv/) and wires the git hooks, including the commit-message gate.

## The loop

```bash
make check
```

`check` tidies, runs the suite, and re-runs it on the oldest supported interpreter. Individual targets are listed by `make help`.

## What this project optimizes for

Declining to act. A formatter that unwraps a paragraph it should have left alone destroys information the author put there on purpose, and the damage is silent — a passing run and a clean report. Every structural guard exists because joining across it lost something. New behavior is welcome; new joining is expensive, and the burden is on the change to show what it will not eat.

Practice test-driven development for real logic: write the failing case, watch it fail, then implement.

The specification of that boundary is the conformance corpus, not the Python tests. A change to what gets joined is a **corpus case first** — see [corpus/README.md](corpus/README.md) for the format, which is three files in a directory and needs no parser worth the name. `tests/test_unwrap.py` covers only what a corpus cannot describe, because no other implementation shares it: argument handling, file discovery, encoding failures, exit codes.

Two things about the corpus are load-bearing rather than stylistic. Its cases are literal files because a GFM hard break *is* two trailing spaces and a CRLF case *is* `\r\n`, and any inline format puts both where a tidying hook eats them silently — leaving a case that passes while testing nothing. And `.pre-commit-config.yaml` carries `exclude: ^corpus/[^/]+/` because this repository runs its own unwrap hook over `types: [markdown]`; without it, one commit would rewrite every input into its own expected output and turn the suite green against nothing. That key does not reach every caller — `pre-commit try-repo` builds its config from `.pre-commit-hooks.yaml`, and the composite action sweeps with its own `git ls-files` — which is why exclusion also belongs to the tool. A `.unwrapignore` at the repository root names both corpus tiers, and because the tool reads it wherever it is invoked from, CI and `make hook-test` can both just say `--all-files`.

Each case earns three checks — output, reported counts, and idempotency — so cases are cheap and worth adding freely. A case whose expected output equals its input is not wasted: most of this tool is the part that declines to act, and those are the cases a change is likeliest to break.

## The version floor

`pyproject.toml` declares `requires-python = ">=3.10"`, and that is a promise to every repository that installs this hook rather than a preference. The development interpreter is newer, so it will not notice the day a 3.11-only construct lands. `make floor` runs the whole suite on 3.10 and CI runs the matrix; treat a failure there as a bug in the change, not in the floor.

The one place this has already bitten: `Path.read_text(newline=...)` exists only on 3.13, and the tool spells it `Path.open(...)` instead. Line-ending handling cannot be dropped — this tool decides what a line break is, and normalizing `\r\n` to `\n` on read would rewrite every line of a CRLF file on the first run that touched it.

## The second implementation

There is a Rust crate in this tree — `Cargo.toml`, `src/lib.rs`, `src/bin/`, `tests/corpus.rs` — answering to the same `corpus/` as the Python. Neither implementation is the specification; the corpus is, which is what makes parity checkable rather than asserted. `make rust-test` and `make rust-lint` run it, and its MSRV lives in `rust-version` and in the toolchain CI pins, which move together.

`cargo test` is red on purpose until the paragraph pass lands, so `make check` deliberately leaves it out: a `check` that stays red for weeks is one nobody reads. Both suites join it once both implementations answer the same tiers.

## Both entry points

The hook and the action share the CLI and nothing else. A green test suite says nothing about whether `.pre-commit-hooks.yaml` resolves or the composite action runs, so CI exercises all three paths. Run the framework path locally with `make hook-test`.

## Commits and pull requests

Conventional Commit messages; imperative, lowercase subjects of 50 characters or fewer. Commit atomically — one concern per commit. Pull request titles become the squash subject, so write them the same way.
