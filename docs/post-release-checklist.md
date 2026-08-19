# Post-release checklist

Everything currently written in a provisional form, and what each thing becomes once the release flow has actually run. Written before the first tag, while the reasons are fresh, because every item here is a small edit that is obvious today and archaeology in three months.

Each item names its file and why it exists. An item is done when the caveat is gone, not when the feature works — a stale caveat is worse than none, because a reader who finds one wrong stops trusting the rest.

The stages are ordered by what unblocks them, and are deliberately keyed to conditions rather than to version numbers. Nothing in stage B can start before stage A, and nothing in stage C should land before stage B is proven.

How many tags that takes is not knowable in advance. `v0.0.1` may not publish cleanly, and the `0.0.x` series exists precisely so that it can fail without costing anything — stage B might begin at `v0.0.2` or at `v0.0.4`. A checklist that named the numbers would be wrong the first time a tag had to be re-cut, and wrong in the direction that matters, since the reader would trust it.

## Stage A — the first tag that publishes cleanly

Registry publication is irreversible, so this stage is mostly verification, and the hardening that could not be done before a crate existed.

- [ ] Confirm the release carries all six binaries and a `SHA256SUMS` manifest, and that the checksums match
- [ ] Confirm the package is on PyPI, and that the pending publisher converted to a normal one
- [ ] Configure Trusted Publishing on the crate's settings page: owner `michen00`, repository `markdown-prose-hooks`, workflow `release.yml`, environment blank. This is the step that has no pending equivalent, which is the entire reason the token fallback exists.
- [ ] `gh secret delete CARGO_REGISTRY_TOKEN` once that publisher is configured. A long-lived registry token is the thing Trusted Publishing exists to avoid, and this one expires around 2026-09-10 regardless.
- [ ] `.github/workflows/release.yml` — drop `continue-on-error: true` from the `rust-lang/crates-io-auth-action` step, and drop `|| secrets.CARGO_REGISTRY_TOKEN` from the `cargo publish` env. Both exist only to make the *first* tag work. Left in place after the secret is deleted they turn an auth failure into an empty token that fails later, at the registry, with a worse error.
- [ ] `.github/workflows/release.yml` — the long comment above the `pypi:` job explains the pending-publisher asymmetry in the future tense. Rewrite it as a record of what was done.
- [ ] `README.md` — remove the `[!IMPORTANT]` admonition under `## Installation`. It says nothing is published, which stops being true here.
- [ ] Verify all three channels against the published artifacts rather than the working tree: `pipx install markdown-prose-hooks`, `cargo install markdown-prose-hooks`, and a `pre-commit try-repo` at the tag

## Stage B — the mirrors, proven by the next patch tag

Unblocked by stage A: the `-rs` mirror is a thin wrapper crate depending on the published crate, so it needs a crate on the registry to depend on.

- [ ] Create `markdown-prose-hooks-py` and `markdown-prose-hooks-rs`
- [ ] Write the generator and run it on tag. The mirrors are generated and force-pushed, never hand-edited: a hook manifest maintained in two places is a manifest that eventually disagrees with itself.
- [ ] `action.yml` — the `DEVIATION` comment above `runs:` is the specification for this work. Download the prebuilt binary for the tag, add an `implementation` input taking `auto`, `rust` or `python` and defaulting to `auto`, and keep `pip install` as the fallback for a runner with no published binary. **Verify the downloaded binary against `SHA256SUMS` before executing it.** Delete the comment when the work lands.
- [ ] `action.yml` — rewrite the `python-version` description. It stops governing the tool and starts governing only the fallback path.
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
