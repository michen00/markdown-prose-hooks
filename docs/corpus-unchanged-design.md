# Stating that a corpus case changes nothing

Most of this tool is the part that declines to act, so a large share of the conformance corpus pins documents the unwrap must leave alone. Before this change, every one of those cases stated that twice: once in the counts it records, and once in an answer key that repeated its own input byte for byte. This records the decision to state it once, as a declaration, and the rules that go with it.

## Duplication costs, measured

Measured on 2026-09-14, against the tree this change starts from. In `corpus/cases/`, 39 of 90 cases had an `expected.md` byte-identical to their `input.md`. In `corpus/cli/`, 23 of 52 had an `expected/` tree identical to their `tree/`. The duplicated content came to about 2.3 KB in the transform tier and under 1 KB in the CLI tier.

Storage was not the reason to change this. Git addresses blobs by content, so each duplicated document was already stored once: `corpus/cases` held 270 tree entries against 231 distinct blobs, and that difference was exactly the no-op set. Neither the repository nor a clone gets measurably smaller.

Three other costs were real. A reader could not tell which cases were no-ops without comparing files. Anything reading the whole tree, a person or a program, paid for 68 entries whose contents were recoverable from entries next to them. And the two copies can drift: editing `input.md` without editing `expected.md` turns a case that means "this is left alone" into one asserting a transform nobody chose, silently, in the tier that has no regeneration command to catch it.

## What absence is allowed to mean

The CLI tier already gives absence meaning twice. An absent `stdin.md` means nothing was piped in, and an absent `stdout.txt` means nothing was printed. Extending that to the answer key is tempting and is not safe, because those two differ from this one in a way worth stating as a rule:

> Absence may mean nothing. It may never mean something.

An absent `stdin.md` and an absent `stdout.txt` both denote the empty case, which is the common default, and a wrong guess about either is caught by the assertion that reads it. "The output equals the input" is not an empty case; it is a claim.

## The key

A new optional key in `case.txt`, in both tiers:

```text
expected: unchanged
```

In `corpus/cases/`, it states that the output is byte-identical to `input.md`. In `corpus/cli/`, it states that the tree after the run is byte-identical to `tree/`. Each tier's four required keys stay required. In `corpus/cli/`, this is a second optional key beside `chmod`; in `corpus/cases/`, it is the first.

It carries a value instead of standing alone as a flag because a line with no colon is malformed in both readers. `tests/corpus.rs` parses metadata with `split_once(':')`, which cannot split such a line, and `tests/test_corpus.py` with `partition(':')`, which takes the whole line as a key with an empty value; the two agree only where the line is rejected outright, and a flag standing alone is exactly such a line.

Given that it must carry a value, `expected: unchanged` is preferred to a boolean such as `unchanged: true`. The value names a relation between the expected output and the input, and identity is the only relation needed today. A boolean could never hold a second one. This is an enumeration with a single member rather than a boolean written as a key and a value, and it is worth being plain that no second member is currently foreseen.

## The rules

Two structural rules, both checkable from the files alone and neither overlapping the other:

**A case states its expected output exactly once.** Either the key is present or the answer key is present, never both and never neither. Both is a contradiction with no defensible tiebreak. Neither is a case that asserts nothing, which deserves a name rather than the two different accidents it otherwise produces: a file-not-found in the transform tier, where the reader opens `expected.md`, and a diff against an empty tree in the CLI tier, where `Path.rglob` over a missing directory yields nothing.

**An answer key differs from its input.** A file or tree that merely repeats the input states nothing the input did not already state, and must use the key instead. This is what keeps one form in the tree as cases are added, rather than letting the duplicated form return with the next contributor.

One diagnostic check, which earns its place for the message rather than the coverage:

**A case declaring `unchanged` records zero counts.** A case declaring that nothing changed while recording a removed line break already fails today, because whichever way the tool behaves, either the output assertion or the counts assertion catches the disagreement. Checking it at load time turns a diff into an error that names the contradiction.

## The declaration is optional rather than required

Requiring every zero-count case to declare `unchanged` would give the corpus a single form and is the wrong trade. It would encode, as a corpus rule, a property of the current implementation: that removing zero line breaks implies unchanged bytes. That property does hold today, by construction rather than by accident, since every byte-modifying write in `flush()` in `src/markdown_prose_hooks/unwrap.py` is paired with an increment of at least one and every other write emits the original line verbatim over a rejoinable split. A randomized probe over 200,000 generated documents on 2026-09-14 found no counterexample.

It is still a fact about one implementation, and the corpus is the specification that implementations answer to rather than the other way around. A future case pinning "zero breaks removed, bytes changed" would be inexpressible under a requirement, and the format would have to change to admit it. Left optional, that case needs nothing new: it records zero counts, omits the key, and ships a differing answer key. The rule that an answer key differs from its input keeps the tree in one form without the schema forbidding the other shape, because such a case's answer key does differ from its input and the check never fires on it.

The count guard encodes that same property. A case recording a non-zero count over byte-identical output can neither declare `unchanged`, which the guard rejects, nor ship an answer key equal to its input, which the redundancy rule rejects, so the mirror of the case this section keeps expressible is jointly forbidden. Nothing in the corpus needs that case, and the guard buys a named error for a contradiction, at a cost this section otherwise declines to pay.
