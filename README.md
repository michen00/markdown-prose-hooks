# markdown-prose-hooks

[![Build Status](https://img.shields.io/github/actions/workflow/status/michen00/markdown-prose-hooks/CI.yml?style=plastic)](https://github.com/michen00/markdown-prose-hooks/actions)
[![Coverage](https://img.shields.io/codecov/c/github/michen00/markdown-prose-hooks?style=plastic)](https://codecov.io/gh/michen00/markdown-prose-hooks)
[![Release](https://img.shields.io/github/v/release/michen00/markdown-prose-hooks?style=plastic)](https://github.com/michen00/markdown-prose-hooks/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=plastic)](CONTRIBUTING.md)
[![License](https://img.shields.io/github/license/michen00/markdown-prose-hooks?style=plastic)](LICENSE)

A [pre-commit](https://pre-commit.com/) hook and GitHub Action that removes manual soft-wrap line breaks from Markdown prose, so a paragraph is one line and a diff to it is one line.

Hard-wrapping prose at 80 columns makes every edit rewrite the whole paragraph. Unwrapping it makes a one-word change a one-word diff. The hard part is doing that without destroying the line breaks that carry meaning — and most of this tool is the part that declines.

## What it leaves alone

The conservative boundary is the feature. Every one of these is left exactly as written:

- Fenced code blocks, including tilde fences and nested longer fences
- YAML front matter
- GFM tables, and any line carrying a pipe outside an inline code span
- List structure: markers, nesting, indentation, and single-letter enumerators (`a.`, `b)`) as whole lines
- Blockquote shape, including quoted fences and quoted HTML
- Hard breaks (two trailing spaces, or a backslash)
- Link reference definitions and runs of link-only lines (badge blocks)
- Label rows — `**Date:** ...` / `**Status:** ...` — which GFM renders as separate lines
- Speaker turns, and whole files that look like transcripts
- HTML blocks and raw-text elements
- The file's original line endings: `\r\n` and `\r` survive a rewrite

Two of those are about shape rather than about every line. Prose wrapped inside a `-` or `1.` item joins at the indentation its marker implies, and prose inside a blockquote joins behind its marker: what the tool preserves there is the container, not the line breaks within it. A single-letter enumerator is structural, so those lines do stay as written.

## Installation

### As a pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks-py
    rev: v0.1.1 # Use the latest version
    hooks:
      - id: unwrap-markdown-prose-py
```

Each implementation is served by a repository carrying only itself, so this clones one of them rather than both plus the corpus that specifies them. For the Rust pair, use `markdown-prose-hooks-rs` and the `-rs` ids. The two are generated from this one on every release and hold the same version tags. A version tag is frozen on all three repositories — a ruleset refuses to move or delete one, for every actor including the release flow that created it — so a `rev:` you pin resolves to the same tree permanently, and following a newer release means changing the pin rather than waiting for the tag to change under you.

Then:

```bash
pre-commit install
```

Four hook ids ship, two implementations of one specification:

| id | behavior |
| -- | -- |
| `unwrap-markdown-prose-py` | Rewrites files in place. `pre-commit` fails the run when a file changed, so the commit stops with the rewrite sitting unstaged in the working tree. Stage it and commit again. |
| `unwrap-markdown-prose-py-check` | Reports without rewriting, and exits non-zero if anything would change. |
| `unwrap-markdown-prose-rs` | The Rust implementation of the same rewrite. |
| `unwrap-markdown-prose-rs-check` | The Rust implementation of the same check. |

**Which pair to use turns on whether cargo is already installed.**

- **No cargo:** use `-py`. A `language: rust` hook builds from source, so `pre-commit` downloads and installs a whole Rust toolchain before it can check the first commit. That cost dwarfs anything the choice saves.
- **cargo already installed:** use `-rs`. Building the Rust hook costs about the same as creating a virtual environment and installing the Python one, and the Rust program is then faster every time it runs.
- **A large repository, or `--all-files` over thousands of files:** use `-rs`. This is where a run saves the most time, even though the multiple between them is smaller than for a single file: startup is most of a one-file run, and the per-file cost is most of a sweep.
- **No Python at all:** use `-rs`. It is a single executable with no runtime to install.

The two implementations answer to the same conformance corpus and produce the same bytes, so switching between them changes what it costs to install and to run, never what it does. Both costs are measured in [docs/benchmarks.ipynb](docs/benchmarks.ipynb), which reports how the difference varies with the number of files and the amount of text in each.

### As a GitHub Action

```yaml
- uses: michen00/markdown-prose-hooks@v0.1.1
  with:
    write: 'false'
    fail-on-change: 'true'
```

It is listed on [GitHub Marketplace](https://github.com/marketplace/actions/unwrap-markdown-prose), which is where the workflow editor's action picker finds it.

`@v0` is also a tag, moved by the release flow to the newest `0.x` release, for a workflow that would rather follow the line than bump a pin. It is the only tag here that moves: every `vX.Y.Z` is frozen, as above, which is the difference between the two and the whole of it.

With no `paths`, every tracked Markdown file is inspected. The action picks an implementation itself, and `implementation` is there to override that rather than to be set routinely.

The action downloads the prebuilt Rust binary for its own version, verifies it against the release's `SHA256SUMS` before running it, and provisions nothing. A runner the release carries no binary for — a Windows arm64 machine, or a platform Actions offers before the release matrix covers it — falls back to `pip install`, which is also what `implementation: 'python'` selects outright. A checksum that does not match is never a fallback: it stops the run. Which one ran is on the `implementation` output.

By default the step annotates each offending file and writes a table to the job summary, so a failure says which files and how much rather than only that something is wrong. Annotations need no token permissions, which is what makes them work the same on a pull request from a fork. Set `annotate: 'false'` to turn both off.

| input | default | effect |
| -- | -- | -- |
| `paths` | every tracked Markdown file | Space-separated files or globs. |
| `write` | `'false'` | Rewrite files in the workspace. |
| `fail-on-change` | `'true'` | Exit non-zero when anything would change. |
| `annotate` | `'true'` | Annotations and a job-summary table. |
| `implementation` | `'auto'` | `auto`, `rust` or `python`. `rust` makes a missing binary an error instead of a fallback. |
| `python-version` | `'3.13'` | Interpreter for the fallback path, and only there. |

The action also exposes a `changed` output, which is what the recipe below branches on, and an `implementation` output naming the build that ran.

#### Fixing instead of failing

The action never commits, pushes, or opens a pull request — it reports, and leaves the writing to a step you control. For a branch in your own repository, that step is short:

```yaml
permissions:
  contents: write

steps:
  - uses: actions/checkout@v7
  - uses: michen00/markdown-prose-hooks@v0.1.1
    id: unwrap
    with:
      write: 'true'
      fail-on-change: 'false'
  - if: steps.unwrap.outputs.changed == 'true'
    run: |
      git config user.name 'github-actions[bot]'
      git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
      git commit --all --message 'style: unwrap Markdown prose'
      git push
```

**This works on branches in your own repository and not on pull requests from forks**, and that is GitHub's design rather than a gap here: a fork's `GITHUB_TOKEN` is read-only whatever the workflow's `permissions:` block asks for, because the pull request contains code nobody has reviewed yet. The usual workaround, `pull_request_target`, hands a writable token to a job that then checks out that unreviewed code, and is a well-known way to give away write access.

The safe shape for forks splits the work in two, and both halves ship here as reusable workflows. The job triggered by `pull_request` runs with the read-only token a fork gets and leaves the patch behind as an artifact; a second workflow triggered by `workflow_run` — defined on your default branch, so you wrote it rather than the contributor — has the permission to post it, checks out nothing, and treats that artifact as data all the way through. Wiring it takes two files.

```yaml
# .github/workflows/prose.yml — runs on the pull request and writes nothing
name: Prose
on: [pull_request]
permissions:
  contents: read
jobs:
  propose:
    uses: michen00/markdown-prose-hooks/.github/workflows/unwrap-propose.yml@v0.1.1
```

```yaml
# .github/workflows/prose-comment.yml — has to be on your default branch
name: Prose comment
on:
  workflow_run:
    workflows: [Prose] # the `name:` of the file above, never the reusable one
    types: [completed]
jobs:
  comment:
    if: github.event.workflow_run.event == 'pull_request'
    permissions:
      actions: read
      pull-requests: write
    uses: michen00/markdown-prose-hooks/.github/workflows/unwrap-comment.yml@v0.1.1
```

The contributor then gets one comment, edited in place on every push rather than added to, naming the files, the single command that fixes them, and the patch folded underneath. Three things about `workflow_run` are worth knowing before you wire it: it matches the **caller's** `name:` and never the reusable file, it fires only for a copy of the workflow already on your default branch, and it does not appear among the pull request's own checks.

`annotate` is the fork-safe signal that needs no second file at all. It costs no permissions, so it reaches a fork's pull request on its own, and it stays on underneath the pair.

### As a command

```bash
pipx install markdown-prose-hooks   # the -py implementation
unwrap-markdown-prose-py docs/*.md --write
```

```bash
cargo install markdown-prose-hooks  # the -rs implementation
unwrap-markdown-prose-rs docs/*.md --write
```

The two binaries are named apart on purpose: installing both leaves each reachable rather than having one shadow the other on `PATH`.

## Usage

```text
unwrap-markdown-prose-py [paths ...] [--files-from FILE] [--ignore-file PATH]
                         [--exclude GLOB] [--write] [--json] [--fail-on-change]
```

| flag | effect |
| -- | -- |
| `--write` | Rewrite files in place instead of only reporting. |
| `--json` | Emit a machine-readable summary on stdout. |
| `--fail-on-change` | Exit non-zero when any file changed or would change. |
| `--files-from` | Read additional newline-delimited paths from a file. |
| `--ignore-file` | Read ignore patterns from this file instead of `./.unwrapignore`. |
| `--exclude` | Skip paths matching a glob. Repeatable; applied after the ignore file. |

Directories are not expanded — pass files. `git ls-files '*.md'` is the usual source.

## Ignoring files

A `.unwrapignore` in the working directory lists paths this tool should leave alone, and `--exclude GLOB` adds more from the command line. Both filter the file list however it was produced — named arguments, `--files-from`, or a future directory walk — which is the point: `pre-commit` passes filenames explicitly, so a tool that honored exclusions only during its own discovery would ignore them exactly where they are most used. An excluded file is skipped silently, and cannot trip `--fail-on-change`, because exclusion is a statement about scope rather than an error.

This is deliberately not `pre-commit`'s `exclude:` key. That key reaches one of the three ways this tool is invoked, so a repository configuring exclusions there gets nothing from the GitHub Action and nothing from the CLI. Exclusion belongs to the tool.

The pattern syntax is a small subset of gitignore's:

| syntax | meaning |
| -- | -- |
| `#` | Comment. A blank line is skipped too. |
| `*` | Any run of characters within one path component, including none. |
| `?` | Exactly one character within one path component. |
| `**` | Zero or more whole path components — the only wildcard crossing a `/`. |
| `/` leading | Anchors the pattern to the directory the ignore file sits in. |
| `/` trailing | Restricts the pattern to directories, so `build/` covers `build/x.md`. |
| `!` leading | Negates. The last matching pattern wins. |
| `\` | Escapes a leading `#` or `!`, or a trailing space. |

Character classes are not supported. One rule differs from gitignore on purpose: **only a leading slash anchors**. Gitignore also anchors any pattern containing a non-trailing slash, which makes `docs/note.md` mean two different things depending on where the slash falls; here it matches at any depth, and a reader has one rule to remember instead of two.

Every one of these is pinned by a case in `corpus/cli/`, which is what both implementations answer to. The escaped trailing space is the exception, and cannot be one: Windows cannot create a file whose name ends in a space, so no fixture can hold the case.

## Example

Before:

```markdown
Runs only when the previous step reported success and the runner pushed at
least one commit during this run. If the runner changed nothing, the body
already matches the branch and a refresh is pure noise.
```

After:

```markdown
Runs only when the previous step reported success and the runner pushed at least one commit during this run. If the runner changed nothing, the body already matches the branch and a refresh is pure noise.
```

## Known limitations

A **bare** pipe in running prose is treated as table syntax and blocks unwrapping for that paragraph. This is deliberate. Every row of a GFM table contains a pipe, so the pipe test is what protects tables; narrowing it to real tables needs full table state rather than a delimiter-row lookahead, because body rows do not follow a delimiter row. Corrupting a table is a worse outcome than declining to unwrap a paragraph. A pipe inside an inline code span does **not** block unwrapping — code spans are masked before the test.

An inline code span opened on one line and closed on the next is not recognized, since the matcher works a line at a time.

## Requirements

Python 3.10 or newer for the `-py` hooks, the Action, and the command. Rust 1.86 or newer for the `-rs` hooks. Neither implementation has any dependency beyond its own standard library.

## Documentation [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/michen00/markdown-prose-hooks)

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, the check gate, the version floor, and the release flow
- [SECURITY.md](SECURITY.md) — supported versions, reporting a vulnerability, and what to check about a release before you run it
- [corpus/README.md](corpus/README.md) — the conformance corpus, which is the specification both implementations answer to
- [docs/rust-port-design.md](docs/rust-port-design.md) — why there is a second implementation, and how it is decomposed
- [docs/benchmarks.ipynb](docs/benchmarks.ipynb) — what each implementation costs to install and to run

## License

[MIT](LICENSE)
