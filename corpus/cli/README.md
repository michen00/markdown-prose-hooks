# CLI conformance tier

The transform tier next door specifies what the unwrap does to a document. This tier specifies everything a document cannot describe: which files the tool opens, what it writes, what it prints, and what it exits with. Every implementation runs this directory through its own binary.

It exists because `corpus/cases/` calls `unwrap_markdown_prose` directly, so nothing it contains can reach argument parsing, file walking, `--write`, `--fail-on-change`, or the transcript skip — and all of those are behavior an implementation can get wrong.

## Layout

One directory per case, named by its slug:

```text
corpus/cli/<slug>/
  case.txt      metadata and rationale
  tree/         the input file tree, copied to a scratch directory before the run
  expected/     the tree exactly as it must look afterward
  stdout.txt    expected stdout, verbatim; absent means empty
```

## `case.txt`

Plain `key: value` lines, one per line. Four keys, all required:

| key | meaning |
| -- | -- |
| `name` | What invariant the case pins, as a sentence |
| `why` | The reasoning. Surfaces in the failure message, so it is what a reader gets when the case breaks |
| `argv` | Arguments after the program name, split on whitespace |
| `exit_code` | The expected process exit status |

`argv` splits on whitespace with no quoting rules, which every language does in one line. A case needing a path with a space in it is a reason to extend the format deliberately rather than to smuggle in a shell.

One optional key:

| key | meaning |
| -- | -- |
| `chmod` | Comma-separated `path octal` pairs, applied to the copied tree before the run |

Git stores one executable bit and nothing else, so a case pinning behavior against an unreadable file cannot express that in `tree/` and says it here instead. A mode is a request rather than a guarantee — Windows has no POSIX permission bits worth the name, and a process running as root reads a mode-`000` file regardless — so a harness applies the mode, confirms it took effect, and skips the case loudly when it did not. Silently running against a readable file would take the success path and fail with a diff that says nothing about why.

The harness restores the original modes before comparing trees. The mode constrains the tool under test, not the harness; left in place, it makes the *verifier* the thing that cannot read the file.

## The rules that make it unambiguous

Each of these is a question the format would otherwise leave to whoever writes the second harness.

**`expected/` is the whole tree, not a diff.** Every file that must exist after the run appears in it, including the ones the run did not touch. A file present in `tree/` and absent from `expected/` must have been *deleted*. This is more typing than absent-means-unchanged, and it is the only version that can express a deletion at all.

**Empty directories cannot be expressed**, because git does not store them. A case needing one is a reason to extend the format.

**The working directory is the copied tree.** `argv` therefore holds relative paths and needs no substitution, and a case may put a `.unwrapignore` in its `tree/` and have it found.

**stdout is compared byte for byte. stderr is not compared at all.** Byte-identical error prose across two languages is maintenance cost with no user-visible payoff, so the tier asserts the first and leaves the second free. Stating the boundary is the point; an unstated one gets litigated at every divergence.

**No case asserts `--help` or a usage message.** Those carry the program name, and the program name is exactly what differs between implementations — `unwrap-markdown-prose` against `unwrap-markdown-prose-rs`, and `__main__.py` when the harness invokes a module. Usage goes to stdout on `--help` and to stderr on a parse error; the first can never match and the second is not compared.

**Line endings are bytes.** `.gitattributes` marks `corpus/cli/**` as `-text -diff` for the reason the transform tier is marked: a case pinning CRLF stops pinning anything the moment git normalizes it on checkout. The net is the whole subtree rather than `*.md`, because `case.txt` and `stdout.txt` are asserted just as literally as the fixtures.

## What each case earns

Three checks, so adding one is cheap:

- the process exits with the recorded status
- stdout matches `stdout.txt` byte for byte
- the tree afterward matches `expected/` file for file and byte for byte

The third is the one that catches a tool writing a file it should not have, which no amount of output checking would notice.

## Adding a case

Write the files and it is picked up automatically; nothing registers cases by name. Prefer a case that pins one decision, and put the argument in `why` rather than in the slug — the slug becomes the test id, and the `why` is what the next person needs when they are staring at a failure and deciding whether the rule or the case is wrong.

Generate `expected/` and `stdout.txt` by running the tool rather than by writing them out. An answer key written by hand pins what its author believed, which is the one thing a conformance case must not do.
