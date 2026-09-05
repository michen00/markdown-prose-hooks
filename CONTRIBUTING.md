# Contributing

## Reporting something

[Open an issue](https://github.com/michen00/markdown-prose-hooks/issues/new/choose). The defect form asks for the document as given, the output, the output you wanted, and the reasoning, because those four are what a conformance case is made of and a report that describes them cannot become one. It also asks which of the hook ids, the action, or the two commands you ran, and the `rev:` you had pinned; behavior differs between them and between versions.

Report against this repository rather than either mirror. The mirrors are generated from this tree, so a fix that does not land here does not survive the next release, and their issues are turned off for that reason.

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

Three of those need a Rust toolchain at the version `Cargo.toml` names. A change touching no Rust can run `make test` instead and leave the rest to the pull request, where the Rust contexts are required and run on three platforms. The CLI corpus is built to allow this: it runs against whichever implementations are present and skips a missing binary rather than failing on it, so a Python-only checkout still exercises the tier.

## What this project optimizes for

Declining to act. A formatter that unwraps a paragraph it should have left alone destroys information the author put there on purpose, and the damage is silent — a passing run and a clean report. Every structural guard exists because joining across it lost something. New behavior is welcome; new joining is expensive, and the burden is on the change to show what it will not eat.

Practice test-driven development for real logic: write the failing case, watch it fail, then implement.

The specification of that boundary is the conformance corpus, not the Python tests. A change to what gets joined is a **corpus case first** — see [corpus/README.md](corpus/README.md) for the format, which is three files in a directory and needs no parser worth the name. `tests/test_unwrap.py` covers only what a corpus cannot describe, because no other implementation shares it: argument handling, file discovery, encoding failures, exit codes.

Both tiers explain how to add a case, and the CLI tier's answer keys are generated rather than written: `REGENERATE_CLI_CORPUS=1 uv run python -m pytest tests/test_cli_corpus.py -k <slug>` writes `expected/` and `stdout.txt` from what the reference run did, leaving `exit_code` as the one expectation you state rather than observe. There is no such path for the transform tier, so produce those two files by running the tool and reading the diff. Never edit an answer key to make a test pass; a key written by hand pins what its author believed, which is the one thing a conformance case must not do.

Corpus cases are literal files because a GFM hard break *is* two trailing spaces and a CRLF case *is* `\r\n`, and any inline format puts both where a tidying hook eats them silently — leaving a case that passes while testing nothing. And `.pre-commit-config.yaml` carries `exclude: ^corpus/[^/]+/` because this repository runs its own unwrap hook over `types: [markdown]`; without it, one commit would rewrite every input into its own expected output and turn the suite green against nothing. That key does not reach every caller — `pre-commit try-repo` builds its config from the hook manifest it is pointed at, and the composite action sweeps with its own `git ls-files` — which is why exclusion also belongs to the tool. A `.unwrapignore` at the repository root names both corpus tiers, and because the tool reads it wherever it is invoked from, CI and `make hook-test` can both just say `--all-files`.

Each case earns three checks — output, reported counts, and idempotency — so cases are cheap and worth adding freely. A case whose expected output equals its input is not wasted: most of this tool is the part that declines to act, and those are the cases a change is likeliest to break.

## The version floor

`pyproject.toml` declares `requires-python = ">=3.10"`, and that is a promise to every repository that installs this hook rather than a preference. The development interpreter is newer, so it will not notice the day a 3.11-only construct lands. `make floor` runs the whole suite on 3.10 and CI runs the matrix; treat a failure there as a bug in the change, not in the floor.

The one place this has already bitten: `Path.read_text(newline=...)` exists only on 3.13, and the tool spells it `Path.open(...)` instead. Line-ending handling cannot be dropped — this tool decides what a line break is, and normalizing `\r\n` to `\n` on read would rewrite every line of a CRLF file on the first run that touched it.

## The second implementation

There is a Rust crate in this tree — `Cargo.toml`, `src/lib.rs`, `src/bin/`, `tests/corpus.rs` — answering to the same `corpus/` as the Python. Neither implementation is the specification; the corpus is, which is what makes parity checkable rather than asserted. `make rust-test` and `make rust-lint` run it, and its MSRV lives in `rust-version` and in the pinned toolchain refs, which move together. `rust-test-stable` is the exception and floats on purpose: it asks whether the crate still builds on a current toolchain, and it does not gate a pull request, so an upstream release cannot block one. Why there is a second implementation at all, and why it is decomposed the way it is, is [docs/rust-port-design.md](docs/rust-port-design.md).

Both implementations now answer both tiers, so `make check` runs everything: the Python suite, the Rust suite, and `make parity`, which builds the release binary and runs `corpus/cli/` against each implementation in turn. Run `make parity` on its own when you have touched anything the CLI reaches.

Three layers sit under that, and each covers what the one above cannot. Rust unit tests pin the matchers, below the specification's altitude. `corpus/` pins the behavior, and is what both implementations answer to. `cargo run --release --example fuzz` generates file trees neither tier anticipated and runs both binaries over them, comparing exit code, stdout and the whole resulting tree. Pass the interpreter that has this package importable -- `-- --python "$PWD/.venv/bin/python3 -m markdown_prose_hooks"` from a `make develop` clone. The default is a bare `python3`, and where that cannot import the package every seed diverges with Python exiting 1 and printing nothing, which reads as a fuzzer finding rather than as a fuzzer misconfigured.

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

The hook and the action share the CLI and nothing else. A green test suite says nothing about whether a hook manifest resolves or the composite action runs, so CI exercises all three paths. The ids live in the two generated mirrors rather than here, so the framework path resolves them from a generated tree. Run the framework path locally with `make hook-test`.

## Commits and pull requests

Fork, branch, and open a pull request; `main` takes no direct pushes. A pull request merges once it has one approving review, every review thread resolved, and the required contexts green. Squash is the only merge method enabled, which is why the title matters below.

Conventional Commit messages; imperative, lowercase subjects of 50 characters or fewer. Commit atomically — one concern per commit. Pull request titles become the squash subject, so write them the same way.

`coverage` is deliberately not a required context — it mints its credential through OIDC, which a pull request from a fork cannot be granted, so requiring it would block outside contribution permanently. And a commit whose author email is not linked to your GitHub account asks for a second approval, under a rule that gives no reason on the page; linking the address in your account settings clears it.

## Releasing

This section is the maintainer's, and what it needs is push access to the tag. Both registries authorize through trusted publishing, so the workflow mints its own short-lived token and there is no registry credential to hold here or to have locally. A tag is the whole trigger. `release.yml` runs on `v*.*.*` and nothing else, so a branch push cannot publish by accident, and there is no environment gate to catch a mistake — pushing the tag is the decision.

```bash
make bump VERSION=X.Y.Z # then commit what it wrote
make check
git status --short      # anything listed has to be committed before the tag
# open a pull request and let it merge, then tag the commit that landed:
git fetch origin && git switch main && git merge --ff-only origin/main
git tag -s vX.Y.Z -m 'vX.Y.Z'
git push origin vX.Y.Z
```

The pull request is not skippable here, and squash is the reason. `main` takes no direct pushes, and a squash merge replaces the commit the bump was made on, so a tag applied before the merge names a commit that never reaches `main` -- `v0.4.0` points at `build: bump the version to 0.4.0 (#12)`, which is the squashed one. Tagging what landed is the only order that leaves the tag on an ancestor of `main`.

`-s` rather than `-a`. `commit.gpgsign` is on but `tag.gpgsign` is not, so an annotated tag is unsigned by default, which would leave the one object asserting "this commit is publishable" as the only unsigned thing in the repository.

The tag is not the end of the checking. `release.yml`'s `verify` job re-runs both suites and the differential fuzzer at the tagged commit, and `binaries`, `pypi` and `crates` all wait on it, so a red `verify` publishes nothing. It builds and tests the Rust with `--locked`, which `make check` does not, so a `Cargo.lock` that disagrees with `Cargo.toml` passes locally and fails there -- and by then the tag is frozen, so the fix is the next patch number rather than a retag. `uv run` is not given `--locked` in that job, so only the Cargo side carries this hazard.

One gate sits after the publishes, and it is the only one there: `alias` waits on `smoke`, so a red smoke run leaves `@v0` pointing at the previous release while the version itself has already shipped. Nothing else in the flow waits on it, which is the right way round -- moving a tag is reversible and a publish is not.

`make bump` moves every version pin at once, and writes nothing at all if it cannot find one of them. Six files carry the number and they are not alike: the two manifests, the two lockfiles derived from them, the readme snippets a consumer copies, and the `uses:` pin in `unwrap-propose.yml` that the reusable workflow runs. Naming a subset of that list here is what let `v0.1.1` ship with the propose pin a release behind, against the comment directly above it, so the list lives in `scripts/bump_version.py` where it runs rather than in this sentence where it rotted. The tag matches what the bump wrote.

Registry publication is irreversible: a version cannot be re-uploaded and a name cannot be reused, so `cargo publish --dry-run` and `twine check` are worth running before the tag rather than discovering a packaging error after the number is spent. If one registry job succeeds and the other fails, retagging will not recover the consumed version — move to the next patch. It is refused as well as useless: a ruleset on all three repositories freezes `refs/tags/v*.*.*` against update and deletion, with no bypass for anybody, so a version tag is written once. `v0` does not match that pattern and is the one tag the release flow moves. A second ruleset, over `refs/tags/v*`, stops any of them being deleted, `v0` included: moving is the only thing the alias should be able to do, and before that rule existed it was the least protected ref here. Turning the rule off is the only way past it, which is the point — that is a deliberate and visible act rather than something a `--force` does quietly.

The same freeze reaches the mirrors, so a change to `scripts/generate_mirrors.py` cannot be shipped to a version already published: the mirrors workflow refuses to advance a mirror past a tag that cannot follow it, and says to bump instead. A generator change travels with a release, the same way an implementation change does. A dispatch is the one exception, because it is a person rather than a release: it may move a mirror's `main` past its newest tag, so a fix to a mirror readme reaches the page somebody actually reads without spending a version on it. What a pinned `rev:` resolves to is unchanged either way, which is what makes the exception safe.

Marketplace needed a browser once and does not need one again. Creating [the listing](https://github.com/marketplace/actions/unwrap-markdown-prose) is a checkbox on the release form, and it asks for a two-factor confirmation that `release.yml`, which creates its release through the API, cannot give. After that first publish the listing follows the newest release on its own. `v0.1.1` is where that stopped being an inference: the tag published it end to end, and the listing advertised the new version with nobody opening a page. So there is no step to remember after a release, only a page worth a glance. If it ever stops following, the damage is bounded rather than silent — a stale snippet pins a version tag that is now immutable, so it resolves and runs, and the readme points at `@v0` regardless.
