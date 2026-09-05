# Security policy

## Supported versions

Fixes go to the latest release, and what changed in each one is on the [releases page](https://github.com/michen00/markdown-prose-hooks/releases), generated from the pull requests it carries. `v0` is an alias that the release flow moves to the newest `0.x`; every `vX.Y.Z` tag is frozen where it was published, by a ruleset over `refs/tags/v*.*.*` that blocks update and deletion for every actor with no bypass. A second ruleset over `refs/tags/v*` blocks deletion alone, so the alias can move but cannot disappear.

Release tags are annotated. Signing is a step in the release procedure rather than a rule anything enforces: `commit.gpgsign` is on in this repository and `tag.gpgsign` is not, so `-s` is written out by hand each time and the immutability rule above means a tag that missed it cannot be signed afterwards. Check the tag you are pinning with `git verify-tag vX.Y.Z` rather than assuming, and expect the `v0` alias never to verify -- the release flow moves it from a runner, which holds no key.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: [report a vulnerability](https://github.com/michen00/markdown-prose-hooks/security/advisories/new). Please do not open a public issue for a security report.

Report here rather than on [markdown-prose-hooks-py](https://github.com/michen00/markdown-prose-hooks-py) or [markdown-prose-hooks-rs](https://github.com/michen00/markdown-prose-hooks-rs). Those two repositories are generated from this tree and replaced wholesale on every release, so a fix that does not land here does not survive the next one.

This is a personal project maintained on a best-effort basis. Expect an acknowledgment within a week, and a fix as a patch release.

## What the tool can reach

Both implementations read Markdown files and write Markdown files, and do nothing else. Neither has a dependency beyond its own standard library, neither opens a network connection, and neither evaluates or executes anything it reads. A document written to attack the transform therefore produces wrong text rather than an executed instruction, and `git diff` shows you that text before you commit it.

## Verifying a release

Each release publishes a binary per supported platform and a `SHA256SUMS` manifest beside them, so a binary you downloaded yourself can be checked against the manifest from the same release.

The action does that check on every run that downloads a binary. It downloads the manifest first, declines the binary when the manifest does not list an asset for the runner's platform, and treats a digest that disagrees as fatal. A mismatch is never a fallback: it stops the run. There is no path through the action that executes a binary it could not verify. Two paths download no binary at all and so verify none: `implementation: 'python'`, and the fallback an uncovered platform takes. Both install the package from the action's own checked-out tree, and what vouches for that tree is the ref you pinned the action to.

Neither registry is published with a stored credential. PyPI and crates.io both authorize a release through trusted publishing, so the identity is the workflow's rather than a token held in this repository.

## Consumer guidance

- Pin the action to a full commit SHA if your threat model includes compromise of this repository. `@v0` moves by design, and a `vX.Y.Z` tag cannot. The pin fixes the action and the version it resolves, and not the release asset it fetches at run time: the binary and the `SHA256SUMS` it is checked against come from the same release, and a release asset is not a ref, so neither tag ruleset reaches it and no attestation is published beside it. The digest check proves the download matches the manifest from that release rather than the bytes any particular release once held. `implementation: 'python'` is the path that depends on no asset at all, since it installs from the tree your pin already fixes.
- Pin a `pre-commit` hook to a version tag rather than to a branch, for the same reason. A mirror's `main` moves on every release, and while the tree it carries is replaced wholesale, the history is appended to rather than rewritten and there is no force path, so for as long as that mirror repository exists a commit SHA stays resolvable and is a durable pin as well. Each mirror's version tags are frozen by a `refs/tags/v*.*.*` ruleset of its own, matching the first one described above; the deletion rule over `refs/tags/v*` is this repository's alone, because a mirror carries no moving alias to protect. Both guarantees stop at the repository's own lifetime: deleting a mirror takes its rulesets with it, and a new repository under the same name is free to serve those tag names against a different tree, which is what `scripts/check_mirror_identity.py` watches the numeric repository id for. A commit SHA cannot be made to name a different tree that way, since the name is derived from the content; it can only stop resolving.
- The action needs no token, so grant it none. `write: 'true'` rewrites files in the checkout and nothing else; `contents: write` belongs to the step you add afterwards to commit and push those rewrites, not to the action. Its default reporting path annotates and writes a job summary, which needs no token permissions at all, and that is what lets it behave identically on a pull request from a fork.
- If you adopt the `unwrap-propose.yml` and `unwrap-comment.yml` pair, two properties are what make it safe to hand a writable token to a workflow that reacts to a fork's pull request, and changing either is a security regression rather than a preference. The commenting half checks out nothing from the pull request and runs nothing from it. It also refuses an artifact whose claimed pull request number is not the one the producing run's own head repository, branch and commit belong to.
- In particular, do not "fix" the commenting half by checking out the pull request head. That is the mistake `pull_request_target` makes, and it gives away write access to anyone who opens a pull request.
