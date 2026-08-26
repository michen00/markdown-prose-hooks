# markdown-prose-hooks

[![Build Status](https://img.shields.io/github/actions/workflow/status/michen00/markdown-prose-hooks/CI.yml?style=plastic)](https://github.com/michen00/markdown-prose-hooks/actions)
[![Coverage](https://img.shields.io/codecov/c/github/michen00/markdown-prose-hooks?style=plastic)](https://codecov.io/gh/michen00/markdown-prose-hooks)
[![Release](https://img.shields.io/github/v/release/michen00/markdown-prose-hooks?style=plastic)](https://github.com/michen00/markdown-prose-hooks/releases)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=plastic)](CONTRIBUTING.md)
[![License](https://img.shields.io/github/license/michen00/markdown-prose-hooks?style=plastic)](LICENSE)

A [pre-commit](https://pre-commit.com/) hook and GitHub Action that removes manual soft-wrap line breaks from Markdown prose, so a paragraph is one line and a diff to it is one line.

Before:

```markdown
A paragraph wrapped by hand ends its lines where the author's editor ran out
of room, not where the reader's screen does. Change one word near the top and
the words after it all shift, so the diff covers the whole paragraph rather
than the one word that changed.
```

After:

```markdown
A paragraph wrapped by hand ends its lines where the author's editor ran out of room, not where the reader's screen does. Change one word near the top and the words after it all shift, so the diff covers the whole paragraph rather than the one word that changed.
```

That shift is not always chosen. Leave the wrapping alone and the diff stays small, but the paragraph's line lengths become less even with every later edit; add a word that crosses a maximum-width rule and the linter requires the reflow anyway. Unwrapped, there is nothing to choose.

Whether those manual breaks reach a reader at all depends on who is rendering. A Markdown file renders a soft break inside a paragraph as a space, so the text reflows; GitHub renders the same break in an issue or a comment as `<br>`, as does any renderer configured for hard breaks, and there the paragraph is stuck at the width it was written to. Unwrapped prose reflows on all of them.

The hard part is doing either without destroying the line breaks that carry meaning — and most of this tool is the part that declines.

There are two implementations, one in Python and one in Rust. They answer to the same conformance corpus and produce the same bytes, so choosing between them changes what it costs to install and to run, never what it does. Both costs are measured in [docs/benchmarks.ipynb](docs/benchmarks.ipynb), which reports how the difference varies with the number of files and the amount of text in each.

## Requirements

As a GitHub Action, nothing. The action downloads a prebuilt binary and verifies it before running, and provisions nothing. A platform the release carries no binary for — a Windows arm64 machine, or one Actions offers before the release matrix covers it — falls back to Python, which a GitHub-hosted runner already has.

As a `pre-commit` hook or a command, Python 3.10 or newer for the Python implementation, or Rust 1.86 or newer for the Rust one. Neither implementation has any dependency beyond its own standard library.

## Using it

Before turning it on, check what else in your repository enforces a line length on Markdown: a rule that wraps prose and a hook that unwraps it will each undo the other on every run. In [markdownlint](https://github.com/DavidAnson/markdownlint/blob/main/doc/md013.md), that rule is `line-length`, which this repository sets to `false`. In [Prettier](https://prettier.io/docs/options#prose-wrap), `proseWrap` leaves prose alone at its default of `preserve` and reflows it to the print width when set to `always`. In [remark-lint](https://github.com/remarkjs/remark-lint/tree/main/packages/remark-lint-maximum-line-length), the rule is `maximum-line-length`.

### As a pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks-py
    rev: v0.3.0 # Use the latest version
    hooks:
      # Pick one. The first rewrites the file; the second only reports.
      - id: unwrap-markdown-prose-py
      # - id: unwrap-markdown-prose-py-check
```

Then:

```bash
pre-commit install
```

Each implementation is served by a repository carrying only itself — [markdown-prose-hooks-py](https://github.com/michen00/markdown-prose-hooks-py) and [markdown-prose-hooks-rs](https://github.com/michen00/markdown-prose-hooks-rs) — so this clones one of them rather than both plus the corpus that specifies them. For the Python pair, use the first of those and the `-py` ids; for the Rust pair, use the second of those and the `-rs` ids. The two are generated from this one on every release and hold the same version tags. A version tag is frozen on all three repositories — a ruleset refuses to move or delete one, for every actor including the release flow that created it — so a `rev:` you pin resolves to the same tree permanently, and following a newer release means changing the pin rather than waiting for the tag to change under you.

Four hook ids ship, two per implementation:

| id | behavior |
| -- | -- |
| `unwrap-markdown-prose-py` | Rewrites files in place. `pre-commit` fails the run when a file changed, so the commit stops with the rewrite sitting unstaged in the working tree. Stage it and commit again. |
| `unwrap-markdown-prose-py-check` | Reports without rewriting, and exits non-zero if anything would change. |
| `unwrap-markdown-prose-rs` | The Rust implementation of the same rewrite. |
| `unwrap-markdown-prose-rs-check` | The Rust implementation of the same check. |

**Which pair to use turns on whether cargo is already installed.**

- **No cargo:** use `-py`. A `language: rust` hook builds from source, so `pre-commit` downloads and installs a whole Rust toolchain before it can check the first commit. That cost dwarfs anything the choice saves.
- **cargo already installed:** use `-rs`. Building the Rust hook costs about the same as creating a virtual environment and installing the Python one, but the Rust program is faster every time it runs.
- **A large repository, or `--all-files` over thousands of files:** use `-rs`. This is where a run saves the most time, even though the multiple between them is smaller than for a single file: startup is most of a one-file run, and the per-file cost is most of a sweep.
- **No Python at all:** use `-rs`. It is a single executable with no runtime to install.

**Which of the two ids to use turns on whether anything else already writes your Markdown.**

Where nothing else does, take the rewriting id and let the hook hold the convention. Where something already does -- `markdownlint --fix`, Prettier with `proseWrap: always`, or an automation that reflows prose in CI -- there is a writer already, and two of them competing for the same lines never converge: each run undoes the last and reports "files were modified by this hook" forever. Take the `-check` id there and leave the file to the writer that owns it:

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks-py
    rev: v0.3.0 # Use the latest version
    hooks:
      - id: unwrap-markdown-prose-py-check
```

It reports the files that carry manual line breaks and exits non-zero, so the convention is still gated -- the edit is simply somebody else's to make.

### As a GitHub Action

```yaml
- uses: michen00/markdown-prose-hooks@v0.3.0
  with:
    write: 'false'
    fail-on-change: 'true'
```

It is listed on [GitHub Marketplace](https://github.com/marketplace/actions/unwrap-markdown-prose), which is where the workflow editor's action picker finds it.

`@v0` is also a tag, moved by the release flow to the newest `0.x` release, for a workflow that would rather follow the line than bump a pin. It is the only tag here that moves: every `vX.Y.Z` is frozen, as above, which is the difference between the two and the whole of it.

With no `paths`, every tracked Markdown file is inspected. The action picks an implementation itself, and `implementation` is there to override that rather than to be set routinely.

The binary it runs is checked against the release's `SHA256SUMS` first, and a digest that disagrees is never a fallback: it stops the run. The fallback is `pip install`, which is also what `implementation: 'python'` selects outright.

| input | default | effect |
| -- | -- | -- |
| `paths` | every tracked Markdown file | Space-separated files or globs. |
| `write` | `'false'` | Rewrite files in the workspace. |
| `fail-on-change` | `'true'` | Exit non-zero when anything would change. |
| `annotate` | `'true'` | Annotations and a job-summary table. |
| `implementation` | `'auto'` | `auto`, `rust` or `python`. `rust` makes a missing binary an error instead of a fallback. |
| `python-version` | `'3.13'` | Interpreter for the fallback path, and only there. |

The action also exposes a `changed` output, which is what the recipe below branches on, and an `implementation` output naming the build that ran.

By default the step annotates each offending file and writes a table to the job summary, so a failure says which files and how much rather than only that something is wrong. Annotations need no token permissions, which is what makes them work the same on a pull request from a fork. Set `annotate: 'false'` to turn both off.

#### Fixing instead of failing

The action never commits, pushes, or opens a pull request — it reports, and leaves the writing to a step you control. For a branch in your own repository, that step is short:

```yaml
permissions:
  contents: write

steps:
  - uses: actions/checkout@v7
  - uses: michen00/markdown-prose-hooks@v0.3.0
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
    uses: michen00/markdown-prose-hooks/.github/workflows/unwrap-propose.yml@v0.3.0
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
    uses: michen00/markdown-prose-hooks/.github/workflows/unwrap-comment.yml@v0.3.0
```

The contributor then gets one comment, edited in place on every push rather than added to, naming the files, the single command that fixes them, and the patch folded underneath. Three things about `workflow_run` are worth knowing before you wire it: it matches the **caller's** `name:` and never the reusable file, it fires only for a copy of the workflow already on your default branch, and it does not appear among the pull request's own checks.

`annotate` is the fork-safe signal that needs no second file at all. It costs no permissions, so it reaches a fork's pull request on its own, and it stays on underneath the pair.

### As a command

Both implementations are published under the one name `markdown-prose-hooks`, on [PyPI](https://pypi.org/project/markdown-prose-hooks/) and on [crates.io](https://crates.io/crates/markdown-prose-hooks).

```bash
pipx install markdown-prose-hooks   # the -py implementation
unwrap-markdown-prose-py docs/*.md --write
```

```bash
cargo install markdown-prose-hooks  # the -rs implementation
unwrap-markdown-prose-rs docs/*.md --write
```

The two binaries are named apart on purpose: installing both leaves each reachable rather than having one shadow the other on `PATH`.

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

## Ignoring files and paragraphs

### Whole files, by path

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

### One paragraph, by comment

Some line breaks are deliberate, and `<!-- unwrap-ignore -->` on a line of its own says so about the paragraph after it:

```markdown
<!-- unwrap-ignore -->
The break after this line is
the whole point of the paragraph.
```

It covers one paragraph and is spent by anything else. A blank line between the comment and the paragraph is allowed; a heading, a fence, or any other content in between spends the directive, and the paragraph then unwraps as usual. Staying armed until some later paragraph was the other option, and it lets a stray directive exempt text nobody meant to protect: a directive that visibly does nothing is the better failure.

The match is exact, so a comment carrying more than the one word is prose about the tool rather than an instruction to it, and a directive spelled across a multi-line comment is a note to a human. One inside a fenced code block is inert, which is what lets this section print it. Blockquote markers come off first, so `> <!-- unwrap-ignore -->` exempts the quoted paragraph from inside the quote rather than from outside the block it governs.

This governs one paragraph where `.unwrapignore` and `--exclude` above govern whole files, and like them it reaches all three ways of running the tool, because it travels in the document rather than in anyone's configuration. For a run of paragraphs there is the marker pair below. A directive on a list-marker line is not one — though an indented comment inside a list item ends that item's paragraph wherever it appears, whatever the comment says.

### A run of paragraphs, by comment pair

Where several paragraphs in a row are written the way they are on purpose, `<!-- unwrap-ignore-start -->` and `<!-- unwrap-ignore-end -->` exempt everything between them:

```markdown
<!-- unwrap-ignore-start -->

Roses are red,
violets are blue.

This tool joins prose,
and it would join this too.

<!-- unwrap-ignore-end -->
```

The names follow `prettier-ignore-start` and its partner, so a reader who knows that pair knows this one. Both markers are matched the same way the single directive is — exactly, with blockquote markers off first — and both are inert inside a fenced code block, front matter, or a multi-line comment, which is what lets this section print them. A region suspends the transform rather than narrowing it, so a wrapped list item or blockquote inside one is left as written too, and neither count moves, so `--fail-on-change` passes a file whose only prose is exempt.

Three questions a pair of markers raises, and the answers here:

**A missing closing marker exempts the rest of the file**, and the command reports it, naming the file and the line the region opened on. Prettier exempts nothing in that case. This tool goes the other way, because the two failures are not equal: exempting too much declines to improve a file, while exempting too little joins lines somebody marked as unjoinable. The report is what keeps the wider exemption from being silent — nothing changed, so a check would otherwise pass while the file quietly stopped being processed. It is a warning and not an error, and the exit code is unchanged, because a document missing one marker still renders correctly.

**A second opening marker inside a region does nothing**, and one closing marker ends the region however many openings came before it. The markers are a switch rather than a counter, which is what `prettier`, `markdownlint` and `ruff` all do with their equivalents. A counter would turn one missing inner marker into an exemption reaching the end of the file.

**A closing marker with no region open does nothing.** One left behind by an edit that removed its partner is not worth an error.

## How it works

### What it leaves alone

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
- Any paragraph an `<!-- unwrap-ignore -->` comment claims, covered in [One paragraph, by comment](#one-paragraph-by-comment), and any run of paragraphs inside a [marker pair](#a-run-of-paragraphs-by-comment-pair)

Two of those are about shape rather than about every line. Prose wrapped inside a `-` or `1.` item joins at the indentation its marker implies, and prose inside a blockquote joins behind its marker: what the tool preserves there is the container, not the line breaks within it. A single-letter enumerator is structural, so those lines do stay as written.

### Known limitations

A **bare** pipe in running prose is treated as table syntax and blocks unwrapping for that paragraph. This is deliberate. Every row of a GFM table contains a pipe, so the pipe test is what protects tables; narrowing it to real tables needs full table state rather than a delimiter-row lookahead, because body rows do not follow a delimiter row. Corrupting a table is a worse outcome than declining to unwrap a paragraph. A pipe inside an inline code span does **not** block unwrapping — code spans are masked before the test.

An inline code span opened on one line and closed on the next is not recognized, since the matcher works a line at a time.

## Documentation [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/michen00/markdown-prose-hooks)

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, the check gate, the version floor, and the release flow
- [SECURITY.md](SECURITY.md) — supported versions, reporting a vulnerability, and what to check about a release before you run it
- [corpus/README.md](corpus/README.md) — the conformance corpus, which is the specification both implementations answer to
- [docs/rust-port-design.md](docs/rust-port-design.md) — why there is a second implementation, and how it is decomposed
- [docs/benchmarks.ipynb](docs/benchmarks.ipynb) — what each implementation costs to install and to run
