# Conformance corpus

The corpus is the specification. Both implementations of the unwrap — the Python package and the Rust crate — run this directory and must produce identical output for every case. Tests written against a single implementation describe that implementation; these cases describe the behavior, which is what makes cross-language parity checkable rather than asserted.

## Two tiers

`corpus/cases/` is the transform tier, documented below: a document in, a document out. It reaches everything reachable from `unwrap_markdown_prose` and nothing else, which leaves out the transcript skip, the file walking, the flags, and the exit codes — all of them behavior an implementation can get wrong, and none of them expressible as a pair of documents.

`corpus/cli/` covers those by running a binary rather than calling a function. Its format is documented in [corpus/cli/README.md](cli/README.md). The two are deliberately separate rather than one tier with a mode flag: the transform tier is pure and fast and every implementation can run it in-process, while the CLI tier needs a built artifact and a scratch directory, and folding them together would make the cheap half pay the expensive half's setup.

## Layout

One directory per case, named by its slug:

```text
corpus/cases/<slug>/
  case.txt      metadata and rationale
  input.md      the document as given
  expected.md   the document the unwrap must produce
```

## `case.txt`

Plain `key: value` lines, one per line. Four keys, all required:

| key | meaning |
| -- | -- |
| `name` | What invariant the case pins, as a sentence |
| `why` | The reasoning. Surfaces in the failure message, so it is what a reader gets when the case breaks |
| `paragraphs_unwrapped` | Expected count reported by the run |
| `line_breaks_removed` | Expected count reported by the run |

Deliberately not YAML. This package has no dependencies and Python ships no YAML parser, so requiring one would burden every implementation for a file that holds four keys. `key: value` costs a few lines in any language.

## Why literal files rather than one file with delimiters

Two behaviors this tool must preserve cannot survive an inline format.

A GFM hard break is **two trailing spaces**. Any delimiter-based format puts that whitespace where a trailing-whitespace hook, an editor, or a careless reformat will silently eat it — and the case would then pass while testing nothing. As its own file it is bytes on disk.

Line endings are the other. The tool exists partly to *not* rewrite a CRLF file into LF, so a case pinning that has to contain literal `\r\n`. `.gitattributes` marks `corpus/cases/**/*.md` as `-text -diff` so git performs no end-of-line normalization on checkout or commit, and does not try to diff them as text.

Both readers must therefore open case files with newline translation disabled — `newline=""` in Python, and the equivalent elsewhere. Reading a case through universal newlines rewrites CRLF to LF before the assertion runs, which turns a real regression into a pass.

## What each case earns

A single case yields three checks, so adding one is cheap:

- the output matches `expected.md` exactly
- the reported counts match `case.txt`
- the unwrap is idempotent — running it on its own output changes nothing further

Idempotency matters most in practice: a formatter that keeps rewriting the same file makes every commit fail.

## Adding a case

Write the three files and it is picked up automatically; nothing registers cases by name. Prefer a case that pins one decision, and put the argument in `why` rather than in the slug — the slug becomes the test id, and the `why` is what the next person needs when they are staring at a failure and deciding whether the rule or the case is wrong.

A case whose expected output equals its input is not a wasted case. Most of this tool is the part that declines to act, and those are exactly the cases a change is most likely to break.
