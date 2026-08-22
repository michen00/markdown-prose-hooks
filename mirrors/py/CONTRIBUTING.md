# Contributing

Not to this repository. Every file here is written by `scripts/generate_mirrors.py` in [markdown-prose-hooks](https://github.com/michen00/markdown-prose-hooks) and pushed by that repository's release flow, which replaces this whole tree on every release. A commit landed here is a commit the next release deletes, so a pull request against this repository cannot be accepted whatever it proposes: merging one would only schedule its own reversal.

Open it upstream instead. That is where the implementation lives, along with the conformance corpus both implementations answer to, the tests that run against it, and the contributing guide: <https://github.com/michen00/markdown-prose-hooks/blob/main/CONTRIBUTING.md>.

Issues are turned off here for the same reason, so upstream's tracker is the one to use. Two things make a report about these Python hooks easy to act on: which of the two ids you ran, and the `rev:` you had pinned.

## What this repository does not carry

No workflows, so nothing runs here on a push, and nothing here decides whether a release is fit to publish — upstream's checks do that before the release flow generates this tree.

No releases either. `pre-commit` resolves a hook repository by cloning it and checking out the `rev:` you pin, and `pre-commit autoupdate` moves that pin to the newest tag reachable from the default branch. Neither reads the Releases API, so a release here would list no artifact and describe a version upstream's release already describes. The binaries and their checksums belong to that one.

No dependency updates either, and that is a policy rather than an omission. The Python mirror declares no dependencies at all. The Rust one pins the published crate at exactly the version its own tree names, so a bot raising that pin would build a different tool than the one the commit says it is, under a tag that cannot move to admit it. Both follow an upstream release instead, which is the only thing that changes either file.
