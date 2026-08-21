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

`check` tidies, runs the Python suite, re-runs it on the oldest supported interpreter, lints and tests the Rust, and runs both implementations against the CLI corpus. Individual targets are listed by `make help`.

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

Both implementations now answer both tiers, so `make check` runs everything: the Python suite, the Rust suite, and `make parity`, which builds the release binary and runs `corpus/cli/` against each implementation in turn. Run `make parity` on its own when you have touched anything the CLI reaches.

Three layers sit under that, and each covers what the one above cannot. Rust unit tests pin the matchers, below the specification's altitude. `corpus/` pins the behavior, and is what both implementations answer to. `cargo run --release --example fuzz` generates file trees neither tier anticipated and runs both binaries over them, comparing exit code, stdout and the whole resulting tree.

**A divergence the fuzzer finds becomes a corpus case before it becomes a fix.** A seed number is not a specification: the generator's fragment bank renames every seed the moment it moves, so the fixed range CI runs is a regression net only while the generator is frozen. Writing the case first is what makes the corpus grow where drift actually lives rather than where it was anticipated.

Adding a fragment to that bank is cheap and worth doing whenever a hazard has no line that reaches it. Check the addition rather than assume it: mutation testing found two fragments already there that reported coverage they did not have.

## The benchmark notebook

[docs/benchmarks.ipynb](docs/benchmarks.ipynb) measures how much slower the Python implementation is, and only that. Which implementation to use is decided in the README, on grounds the notebook does not measure. The notebook is committed with its outputs, and its charts are committed beside it as SVG, because GitHub renders a notebook from what the file holds rather than by running it; the cell that writes them records why SVG rather than PNG.

Every figure in it is computed by the cell above it, so no number is written into the prose. Cells that state a result also check it, and print what went wrong in place of the result: that both implementations returned the same bytes and the same exit code, that no file changed underneath the run, and that no median sits too far above its own minimum. A check that fails is the notebook working.

The notebook is the source of truth for its own content, so edit it directly. Re-execute it with the kernel named:

```bash
uv run jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=python3 \
  --ExecutePreprocessor.timeout=1800 docs/benchmarks.ipynb
```

Both flags matter. Without `kernel_name`, nbconvert runs whichever kernel the notebook's own metadata names, and opening the notebook in an editor rewrites that metadata to the kernel used there — which is how this notebook once reported an interpreter that had run none of its timings. The default timeout is 30 seconds per cell, and several cells need longer.

Build the release binary before the run rather than during it, and leave the machine otherwise idle. These are process timings a few milliseconds long, so a test suite running alongside them arrives as a failed check rather than as a slower number.

## Both entry points

The hook and the action share the CLI and nothing else. A green test suite says nothing about whether `.pre-commit-hooks.yaml` resolves or the composite action runs, so CI exercises all three paths. Run the framework path locally with `make hook-test`.

## Commits and pull requests

Conventional Commit messages; imperative, lowercase subjects of 50 characters or fewer. Commit atomically — one concern per commit. Pull request titles become the squash subject, so write them the same way.

## Releasing

A tag is the whole trigger. `release.yml` runs on `v*.*.*` and nothing else, so a branch push cannot publish by accident, and there is no environment gate to catch a mistake — pushing the tag is the decision.

```bash
git tag -s vX.Y.Z -m 'vX.Y.Z'
git push origin vX.Y.Z
```

`-s` rather than `-a`. `commit.gpgsign` is on but `tag.gpgsign` is not, so an annotated tag is unsigned by default, which would leave the one object asserting "this commit is publishable" as the only unsigned thing in the repository.

Versions in `Cargo.toml` and `pyproject.toml` move together, and the tag matches both. Registry publication is irreversible: a version cannot be re-uploaded and a name cannot be reused, so `cargo publish --dry-run` and `twine check` are worth running before the tag rather than discovering a packaging error after the number is spent. If one registry job succeeds and the other fails, retagging will not recover the consumed version — move to the next patch.

The provisional forms this repository is still shipping, and what each becomes as the remaining stages land, are tracked in [docs/post-release-checklist.md](docs/post-release-checklist.md).
