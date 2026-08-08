# markdown-prose-hooks

[![Build Status](https://img.shields.io/github/actions/workflow/status/michen00/markdown-prose-hooks/CI.yml?style=plastic)](https://github.com/michen00/markdown-prose-hooks/actions)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=plastic)](CONTRIBUTING.md)
[![License](https://img.shields.io/github/license/michen00/markdown-prose-hooks?style=plastic)](LICENSE)

A [pre-commit](https://pre-commit.com/) hook and GitHub Action that removes manual soft-wrap line breaks from Markdown prose, so a paragraph is one line and a diff to it is one line.

Hard-wrapping prose at 80 columns makes every edit rewrite the whole paragraph. Unwrapping it makes a one-word change a one-word diff. The hard part is doing that without destroying the line breaks that carry meaning — and most of this tool is the part that declines.

## What it leaves alone

The conservative boundary is the feature. Every one of these is left exactly as written:

- Fenced code blocks, including tilde fences and nested longer fences
- YAML front matter
- GFM tables, and any line carrying a pipe outside an inline code span
- Lists, nested lists, and single-letter enumerators (`a.`, `b)`)
- Blockquote shape, including quoted fences and quoted HTML
- Hard breaks (two trailing spaces, or a backslash)
- Link reference definitions and runs of link-only lines (badge blocks)
- Label rows — `**Date:** ...` / `**Status:** ...` — which GFM renders as separate lines
- Speaker turns, and whole files that look like transcripts
- HTML blocks and raw-text elements
- The file's original line endings: `\r\n` and `\r` survive a rewrite

## Installation

### As a pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks
    rev: v0.0.0 # Use the latest version
    hooks:
      - id: unwrap-markdown-prose
```

Then:

```bash
pre-commit install
```

Two hook ids ship:

| id | behavior |
| -- | -- |
| `unwrap-markdown-prose` | Rewrites files in place. `pre-commit` fails the run when a file changed, so the commit stops and the rewrite gets staged. |
| `unwrap-markdown-prose-check` | Reports without rewriting, and exits non-zero if anything would change. |

### As a GitHub Action

```yaml
- uses: michen00/markdown-prose-hooks@v0.0.0
  with:
    write: 'false'
    fail-on-change: 'true'
```

With no `paths`, every tracked Markdown file is inspected. The action exposes a `changed` output so a later step can branch on it.

### As a command

```bash
pipx install markdown-prose-hooks
unwrap-markdown-prose docs/*.md --write
```

## Usage

```text
unwrap-markdown-prose [paths ...] [--files-from FILE] [--write] [--json] [--fail-on-change]
```

| flag | effect |
| -- | -- |
| `--write` | Rewrite files in place instead of only reporting. |
| `--json` | Emit a machine-readable summary on stdout. |
| `--fail-on-change` | Exit non-zero when any file changed or would change. |
| `--files-from` | Read additional newline-delimited paths from a file. |

Directories are not expanded — pass files. `git ls-files '*.md'` is the usual source.

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

An inline code span opened on one line and closed on the next is not recognised, since the matcher works a line at a time.

## Requirements

Python 3.10 or newer. No dependencies — standard library only.

## License

[MIT](LICENSE)
