# Stating that a corpus case changes nothing

Most of this tool is the part that declines to act, so a large share of the conformance corpus pins documents the unwrap must leave alone. Every one of those cases currently states that twice: once in the counts it records, and once in an answer key that repeats its own input byte for byte. This records why that second copy is being replaced by a declaration, and what the rules around the declaration are.

## Duplication costs, measured

Measured on 2026-09-14. In `corpus/cases/`, 39 of 90 cases have an `expected.md` byte-identical to their `input.md`. In `corpus/cli/`, 23 of 52 have an `expected/` tree identical to their `tree/`. The duplicated content is about 2.3 KB in the transform tier and under 1 KB in the CLI tier.

Storage is not the reason to change this. Git addresses blobs by content, so each duplicated document is already stored once: `corpus/cases` holds 270 tree entries against 231 distinct blobs, and that difference is exactly the no-op set. Neither the repository nor a clone gets measurably smaller.

Three other costs are real. A reader cannot tell which cases are no-ops without comparing files. Anything that reads the whole tree, a person or a program, pays for 67 files whose contents are recoverable from files next to them. And the two copies can drift: editing `input.md` without editing `expected.md` converts a case that meant "this is left alone" into one asserting a transform nobody chose, silently, in the tier that has no regeneration command to catch it.

## What absence is allowed to mean

The CLI tier already gives absence meaning twice. An absent `stdin.md` means nothing was piped in, and an absent `stdout.txt` means nothing was printed. Extending that to the answer key is tempting and is not safe, because those two differ from this one in a way worth stating as a rule:

> Absence may mean nothing. It may never mean something.

An absent `stdin.md` and an absent `stdout.txt` both denote the empty case, which is the common default, and a wrong guess about either is caught by the assertion that reads it. "The output equals the input" is not an empty case; it is a claim.

## The key

A new optional key in `case.txt`, in both tiers:

```text
expected: unchanged
```

In `corpus/cases/`, it states that the output is byte-identical to `input.md`. In `corpus/cli/` it states that the tree after the run is byte-identical to `tree/`. The four required keys stay required; this joins `chmod` as optional.

It carries a value instead of standing alone as a flag since the Python and Rust readers differ in how they treat a valueless line. `tests/corpus.rs` parses metadata with `split_once(':')` and skips any line without a colon, whereas `tests/test_corpus.py` uses `partition(':')`, which yields the key with an empty value and inserts it.

Given that it must carry a value, `expected: unchanged` is preferred to a boolean such as `unchanged: true`. The value names a relation between the expected output and the input, and identity is the only relation needed today. A boolean could never hold a second one. This is an enumeration with a single member rather than a boolean written as a key and a value, and it is worth being plain that no second member is currently foreseen.

## The rules

Two structural rules, both checkable from the files alone and neither overlapping the other:

**A case states its expected output exactly once.** Either the key is present or the answer key is present, never both and never neither. Both is a contradiction with no defensible tiebreak. Neither is a case that asserts nothing, which today surfaces as a file-not-found and deserves a name.

**An answer key differs from its input.** A file or tree that merely repeats the input states nothing the input did not already state, and must use the key instead. This is what keeps one form in the tree as cases are added, rather than letting the duplicated form return with the next contributor.

One diagnostic check, which earns its place for the message rather than the coverage:

**A case declaring `unchanged` records zero counts.** A case declaring that nothing changed while recording a removed line break already fails today, because whichever way the tool behaves, either the output assertion or the counts assertion catches the disagreement. Checking it at load time turns a diff into an error that names the contradiction.

## The declaration is optional rather than required

Requiring every zero-count case to declare `unchanged` would give the corpus a single form and is the wrong trade. It would encode, as a corpus rule, a property of the current implementation: that removing zero line breaks implies unchanged bytes. That property does hold today, by construction rather than by accident, since every byte-modifying write in `flush()` in `src/markdown_prose_hooks/unwrap.py` is paired with an increment of at least one and every other write emits the original line verbatim over a rejoinable split. A randomized probe over 200,000 generated documents on 2026-09-14 found no counterexample.

It is still a fact about one implementation, and the corpus is the specification that implementations answer to rather than the other way around. A future case pinning "zero breaks removed, bytes changed" would be inexpressible under a requirement, and the format would have to change to admit it. Left optional, that case needs nothing new: it records zero counts, omits the key, and ships a differing answer key. The rule that an answer key differs from its input keeps the tree in one form without the schema forbidding the other shape, because such a case's answer key does differ from its input and the check never fires on it.

## What changes

`corpus/README.md` and `corpus/cli/README.md` gain the key, the two rules and the principle about absence. Each transform reader gains a branch of a few lines where it currently reads a second file, at `tests/test_corpus.py` and `tests/corpus.rs`. The CLI reader changes one comparison, snapshotting `tree/` when the key is set; it is the only reader for that tier, since it drives both binaries. `.github/pull_request_template.md` points at the two READMEs rather than restating them, so it needs no change.

`docs/rust-port-design.md` restates the CLI tier's format in a block of its own, and that copy is already unreliable. It was last written on 2026-08-21 and carries neither `stdin.md`, which reached `corpus/cli/README.md` on 2026-09-01, nor `chmod`, which predates the block and was never added to it. Putting the new key there would create a third place to drift from, so the block is deleted and the section points at `corpus/cli/README.md` instead. That doc argues why the two tiers exist and what each one covers, which this change does not touch, and its own layout listing counts cases rather than files, so it needs no edit either.

`REGENERATE_CLI_CORPUS` needs one deliberate change. For a case declaring `unchanged` it must refuse to write an `expected/`, failing with the reason when the run did modify the tree, rather than materializing a tree and converting a no-op case into a transform case. The declaration is a statement of intent by a person, and regeneration must not overwrite intent with observation.

Removing the existing duplicates is mechanical: where the two sides already compare equal, delete the file or tree and add the key. Nothing is written by hand, so nothing can be written wrong, and the suite passing afterward is the evidence the deletion was safe. That clears 39 files from the transform tier and 28 files across 23 directories from the CLI tier.
