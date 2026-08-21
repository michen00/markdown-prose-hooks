# Post-release checklist

Everything currently written in a provisional form, and what each thing becomes once the release flow has actually run. Written before the first tag, while the reasons are fresh, because every item here is a small edit that is obvious today and archaeology in three months.

Each item names its file and why it exists. An item is done when the caveat is gone, not when the feature works — a stale caveat is worse than none, because a reader who finds one wrong stops trusting the rest.

The stages are ordered by what unblocks them, and are deliberately keyed to conditions rather than to version numbers. Nothing in stage B can start before stage A, and nothing in stage C should land before stage B is proven.

How many tags that takes is not knowable in advance. `v0.0.1` may not publish cleanly, and the `0.0.x` series exists precisely so that it can fail without costing anything — stage B might begin at `v0.0.2` or at `v0.0.4`. A checklist that named the numbers would be wrong the first time a tag had to be re-cut, and wrong in the direction that matters, since the reader would trust it.

In the event, `v0.0.1` reached both registries. The tag had to be re-cut once before it was pushed, for a reason unrelated to publishing, and the `crates` job needed one re-run; neither cost a version number. So the condition stage B waits on is met — a crate exists for the `-rs` mirror to depend on — and stage B is now gated on the remaining stage A items rather than on a further tag.

## Stage A — the first tag that publishes cleanly

Registry publication is irreversible, so this stage is mostly verification, and the hardening that could not be done before a crate existed.

- [x] Confirm the release carries all six binaries and a `SHA256SUMS` manifest, and that the checksums match. Settled at `v0.0.1`: seven assets, and `sha256sum -c` verified all six binaries against the manifest.
- [x] Confirm the package is on PyPI, and that the pending publisher converted to a normal one. Settled at `v0.0.1`: a wheel and a 449,341-byte sdist, and the publishing page lists an active publisher on the project rather than a pending one.
- [x] Configure Trusted Publishing on the crate's settings page: owner `michen00`, repository `markdown-prose-hooks`, workflow `release.yml`, environment blank. This is the step that has no pending equivalent, which is the entire reason the token fallback exists. Two details the API enforces and no error message anticipates: the workflow field takes a bare filename, rejecting any value containing a slash, and a blank environment means "matches any" while an empty string is a separate error. crates.io also stores the owner's numeric GitHub account id alongside the name and matches on the id, so an account rename requires recreating the config.
- [ ] `gh secret delete CARGO_REGISTRY_TOKEN` once that publisher is configured. A long-lived registry token is the thing Trusted Publishing exists to avoid, and this one expires around 2026-09-10 regardless.
- [ ] `.github/workflows/release.yml` — drop `continue-on-error: true` from the `rust-lang/crates-io-auth-action` step, and drop `|| secrets.CARGO_REGISTRY_TOKEN` from the `cargo publish` env. Both exist only to make the *first* tag work. Left in place after the secret is deleted they turn an auth failure into an empty token that fails later, at the registry, with a worse error. Nothing proves the new publisher until a tag mints against it, and there is no way to rehearse that: the only trigger is `workflow_dispatch` on the whole release flow, which would also build a release from a branch ref and re-attempt a published version. Removing these before that proof is still the right order, because a wrong config costs one job on one tag while the binaries and PyPI publish regardless, and the job re-runs once fixed.
- [ ] `.github/workflows/release.yml` — the long comment above the `pypi:` job explains the pending-publisher asymmetry in the future tense. Rewrite it as a record of what was done, and add the part the comment predicted wrongly: the first `cargo publish` did not fail on credentials. The fallback worked, the token authenticated, and the registry rejected the upload because the account had no verified email address. That is an account-state check rather than an authorization one, which is why it returned 400 rather than 403, and it cost a re-run rather than a version number.
- [ ] `README.md` — remove the `[!IMPORTANT]` admonition under `## Installation`. It says nothing is published, which stops being true here.
- [ ] `CLAUDE.md` — the paragraph under `## Architecture` opens by saying nothing is published and no tag exists, which stops being true here too. The rest of it, about every caveat being marked in place with a `DEVIATION, blocked on` comment and the notebook reading those comments rather than restating them, holds until stage C removes the last of them.
- [x] Verify all three channels against the published artifacts rather than the working tree: `pipx install markdown-prose-hooks`, `cargo install markdown-prose-hooks`, and a `pre-commit try-repo` at the tag. Done for `v0.0.1` on 2026-08-20, with an install from each registry and both hook ids resolved from the tag; the two implementations produced byte-identical output on the same input. It is a manual check and carries no forward guarantee, which is what the smoke-test items at the end of this file are for.
- [ ] Re-execute [benchmarks.ipynb](benchmarks.ipynb) and commit the result. Its closing section is computed from the `DEVIATION` comments in the tree and from `git tag`, so the notes saying nothing is published clear on a re-run and not on an edit. Repeat it whenever a later stage deletes one of those comments. The command is in [CONTRIBUTING.md](../CONTRIBUTING.md#the-benchmark-notebook), and it names the kernel on purpose

## Stage B — the mirrors, proven by the next patch tag

Unblocked by stage A: the `-rs` mirror is a thin wrapper crate depending on the published crate, so it needs a crate on the registry to depend on.

- [ ] Create `markdown-prose-hooks-py` and `markdown-prose-hooks-rs`
- [ ] Write the generator and run it on tag. The mirrors are generated and force-pushed, never hand-edited: a hook manifest maintained in two places is a manifest that eventually disagrees with itself.
- [ ] `action.yml` — the `DEVIATION` comment above `runs:` is the specification for this work. Download the prebuilt binary for the tag, add an `implementation` input taking `auto`, `rust` or `python` and defaulting to `auto`, and keep `pip install` as the fallback for a runner with no published binary. **Verify the downloaded binary against `SHA256SUMS` before executing it.** Delete the comment when the work lands.
- [ ] `action.yml` — rewrite the `python-version` description. It stops governing the tool and starts governing only the fallback path.
- [ ] Replace the estimated binary size with the measured one. `README.md`, `action.yml` and the port spec all describe the download as about a megabyte, which is the budget `Cargo.toml` names for it rather than anything weighed: the release build in this checkout is 344 KB, and the notebook prints that figure on every run. Six targets ship, so there are six numbers, and the honest claim is the largest of them. Those six stopped being estimates at `v0.0.1`, where they ran from 204,288 bytes for the Windows target to 491,992 bytes for the musl one. The 344 KB above is not a seventh number: it is the host build, and on Apple Silicon it is the 352,656-byte `aarch64-apple-darwin` asset counted in binary units. Of the published six, the largest is 480 KiB, so about a megabyte overstates the download by more than a factor of two. Re-measure per release rather than carrying these numbers forward, and note that the smallest and largest are 2.4 times apart, so a single figure describing all six is wrong for five of them.
- [ ] `README.md` — remove the `[!NOTE]` about the action provisioning Python
- [ ] Cut the next patch tag and confirm the mirrors regenerate, and that a consumer can install each pair *from its mirror* rather than from here

## Stage C — `v0.1.0`, the first tag anybody is pointed at

`v0.1.0` is named by what it means rather than by what it counts: the first version this project asks somebody to depend on. It comes after however many `0.0.x` tags the two stages above needed.

- [ ] Delete `.pre-commit-hooks.yaml`, and with it the `DEVIATION` comment at its head
- [ ] `README.md` — point the `repo:` lines at the mirrors, and remove the `[!NOTE]` saying the ids will move
- [ ] `.github/workflows/CI.yml` — the `hook` job runs `pre-commit try-repo .` four times, which reads the file deleted above. It breaks the moment that file is gone. Point it at the generated mirrors, or move the job into them.
- [ ] The `main-protect` ruleset requires the `hook` context. If that job is renamed or removed without updating the ruleset, nothing can merge to `main` again — the required check will never report.
- [ ] Publish to GitHub Marketplace
- [ ] Create the moving `v0` tag, and move it from a release workflow step rather than by hand. A moving tag that a person updates is a moving tag that eventually points at the wrong commit.
- [ ] Bump every version string — see the map below

### Where the version is written

| file | what |
| -- | -- |
| `Cargo.toml` | `version` |
| `pyproject.toml` | `version` |
| `README.md` | the `rev:` in the pre-commit snippet |
| `README.md` | two `uses:` refs, in the action snippet and the fixing recipe |

## Not blocked on any of this

Worth doing whenever, and listed here so they are not mistaken for release work.

- [ ] **The Rust implementation does not gate a merge.** The `main-protect` ruleset requires twelve contexts — `lint`, `hook`, `action`, `build`, and the eight `test` matrix entries. `rust-lint`, the three `rust-test` entries, the three `parity` entries and `coverage` are all absent, so a red Rust build or a diverging fuzz run does not stop a merge. That is the differential-testing guarantee not actually being enforced.
- [ ] `README.md` — the fork-safe `workflow_run` split is described and then caveated with "until that exists here". Shipping it as a reusable workflow removes the caveat.
- [ ] The spec's publishing section and the plan's step 6 are both written in anticipation. Once the release has run, revise them to say what happened. They are living documents rather than artifacts to delete, so they earn a pass each time reality overtakes them.
