# Post-release checklist

Everything currently written in a provisional form, and what each thing becomes once the release flow has actually run. Written before the first tag, while the reasons are fresh, because every item here is a small edit that is obvious today and archaeology in three months.

Each item names its file and why it exists. An item is done when the caveat is gone, not when the feature works — a stale caveat is worse than none, because a reader who finds one wrong stops trusting the rest.

The stages are ordered by what unblocks them, and are deliberately keyed to conditions rather than to version numbers. Nothing in stage B can start before stage A, and nothing in stage C should land before stage B is proven.

How many tags that takes is not knowable in advance. `v0.0.1` may not publish cleanly, and the `0.0.x` series exists precisely so that it can fail without costing anything — stage B might begin at `v0.0.2` or at `v0.0.4`. A checklist that named the numbers would be wrong the first time a tag had to be re-cut, and wrong in the direction that matters, since the reader would trust it.

In the event, `v0.0.1` reached both registries. The tag had to be re-cut once before it was pushed, for a reason unrelated to publishing, and the `crates` job needed one re-run; neither cost a version number. So the condition stage B waits on is met — a crate exists for the `-rs` mirror to depend on — and stage B is now gated on the remaining stage A items rather than on a further tag.

## Stage A — the first tag that publishes cleanly

Registry publication is irreversible, so this stage is mostly verification, and the hardening that could not be done before a crate existed.

Every item here is done, at `v0.0.1`. Two things were falsified by the release that this stage did not anticipate and that are recorded with the work rather than here: both `DEVIATION, blocked on` markers named the first tag as what they waited on, and the promised download size was an unweighed budget. Neither is a caveat that stage B or C removes, so both were corrected in place.

- [x] Confirm the release carries all six binaries and a `SHA256SUMS` manifest, and that the checksums match. Settled at `v0.0.1`: seven assets, and `sha256sum -c` verified all six binaries against the manifest.
- [x] Confirm the package is on PyPI, and that the pending publisher converted to a normal one. Settled at `v0.0.1`: a wheel and a 449,341-byte sdist, and the publishing page lists an active publisher on the project rather than a pending one.
- [x] Configure Trusted Publishing on the crate's settings page: owner `michen00`, repository `markdown-prose-hooks`, workflow `release.yml`, environment blank. This is the step that has no pending equivalent, which is the entire reason the token fallback exists. Two details the API enforces and no error message anticipates: the workflow field takes a bare filename, rejecting any value containing a slash, and a blank environment means "matches any" while an empty string is a separate error. crates.io also stores the owner's numeric GitHub account id alongside the name and matches on the id, so an account rename requires recreating the config.
- [x] `gh secret delete CARGO_REGISTRY_TOKEN` once that publisher is configured. A long-lived registry token is the thing Trusted Publishing exists to avoid, and this one expires around 2026-09-10 regardless.
- [x] `.github/workflows/release.yml` — drop `continue-on-error: true` from the `rust-lang/crates-io-auth-action` step, and drop `|| secrets.CARGO_REGISTRY_TOKEN` from the `cargo publish` env. Both exist only to make the *first* tag work. Left in place after the secret is deleted they turn an auth failure into an empty token that fails later, at the registry, with a worse error. Nothing proves the new publisher until a tag mints against it, and there is no way to rehearse that: the only trigger is `workflow_dispatch` on the whole release flow, which would also build a release from a branch ref and re-attempt a published version. Removing these before that proof is still the right order, because a wrong config costs one job on one tag while the binaries and PyPI publish regardless, and the job re-runs once fixed.
- [x] `.github/workflows/release.yml` — the long comment above the `pypi:` job explains the pending-publisher asymmetry in the future tense. Rewrite it as a record of what was done, and add the part the comment predicted wrongly: the first `cargo publish` did not fail on credentials. The fallback worked, the token authenticated, and the registry rejected the upload because the account had no verified email address. That is an account-state check rather than an authorization one, which is why it returned 400 rather than 403, and it cost a re-run rather than a version number.
- [x] `README.md` — remove the `[!IMPORTANT]` admonition under `## Installation`. It says nothing is published, which stops being true here.
- [x] `CLAUDE.md` — the paragraph under `## Architecture` opens by saying nothing is published and no tag exists, which stops being true here too. The rest of it, about every caveat being marked in place with a `DEVIATION, blocked on` comment and the notebook reading those comments rather than restating them, holds until stage C removes the last of them.
- [x] Verify all three channels against the published artifacts rather than the working tree: `pipx install markdown-prose-hooks`, `cargo install markdown-prose-hooks`, and a `pre-commit try-repo` at the tag. Done for `v0.0.1` on 2026-08-20, with an install from each registry and both hook ids resolved from the tag; the two implementations produced byte-identical output on the same input. It is a manual check and carries no forward guarantee, which is what `smoke.yml` was then built to provide.
- [x] Re-execute [benchmarks.ipynb](benchmarks.ipynb) and commit the result. Its closing section is computed from the `DEVIATION` comments in the tree and from `git tag`, so the notes saying nothing is published clear on a re-run and not on an edit. Repeat it whenever a later stage deletes one of those comments. The command is in [CONTRIBUTING.md](../CONTRIBUTING.md#the-benchmark-notebook), and it names the kernel on purpose

## Stage B — the mirrors, proven by the next patch tag

Unblocked by stage A: the `-rs` mirror is a thin wrapper crate depending on the published crate, so it needs a crate on the registry to depend on.

- [ ] Create `markdown-prose-hooks-py` and `markdown-prose-hooks-rs`
- [ ] Write the generator and run it on tag. The mirrors are generated and force-pushed, never hand-edited: a hook manifest maintained in two places is a manifest that eventually disagrees with itself.
- [ ] `action.yml` — the `DEVIATION` comment above `runs:` is the specification for this work. Download the prebuilt binary for the tag, add an `implementation` input taking `auto`, `rust` or `python` and defaulting to `auto`, and keep `pip install` as the fallback for a runner with no published binary. **Verify the downloaded binary against `SHA256SUMS` before executing it.** Delete the comment when the work lands.
- [ ] `action.yml` — rewrite the `python-version` description. It stops governing the tool and starts governing only the fallback path.
- [ ] Replace the estimated binary size with the measured one wherever it is still an estimate. The six stopped being estimates at `v0.0.1`, where they ran from 204,288 bytes for the Windows target to 491,992 bytes for the musl one. The largest is therefore 480 KiB, so about a megabyte overstates the download by more than a factor of two, and the smallest and largest are 2.4 times apart, so any single figure describing all six is wrong for five of them. `README.md` and `action.yml` were corrected as soon as the release made those numbers knowable. Still to do: the port spec and the plan both describe the download as about a megabyte. `Cargo.toml` names the same figure as a budget rather than a measurement, so it stays as written, and the release came in comfortably under it. The notebook prints 344 KB for the host build on every run, which is not a seventh number: on Apple Silicon it is the 352,656-byte `aarch64-apple-darwin` asset counted in binary units. Re-measure per release rather than carrying any of these forward.
- [ ] `README.md` — remove the `[!NOTE]` about the action provisioning Python
- [ ] Decide whether either mirror publishes to a registry of its own, because the answer changes what the generator has to configure and the spec does not settle it. `pre-commit` builds a hook from the repository it clones, so the `-rs` wrapper crate needs to exist as source in the mirror and not necessarily on crates.io. If it is published, it is a second crate and it repeats the whole first-publish problem solved here: no settings page until a crate exists, so a manual publish or a token first, then a publisher, then the fallback removed. If it is not published, it needs none of that.
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
- [x] The notebook's deviation list promises more than it prints. Its lead-in says each file records "what it is waiting on", but the render took the second and third sentences of each comment block and the blocker is the first, so the one thing the lead-in promised was the one thing omitted. Done by rendering the blocker as a closing sentence rather than by widening the slice, which would have repeated the marker phrase the heading already carries. The order now matches the lead-in: what the file cannot yet be, then what it waits on. Re-executing the notebook to print it also re-measured every figure in it, as any run does.

### Testing what the registries serve

Every other job in both workflows builds the thing it tests. `hook` runs `pre-commit try-repo .` against the local path, `action` runs `uses: ./`, `build` runs `uv build` and uploads the result without installing it, and `verify` in the release flow is another checkout. Nothing installed this package from PyPI or from crates.io, so the corpus had never judged a published artifact: a wheel missing a module, or a crate that will not compile from its own package, would have published green. Stage A closed that by hand, for one tag, on one day. `.github/workflows/smoke.yml` closes it for every tag and again every week.

It cannot be turned into a gate, and is not built as one. A version does not exist until it is published, and publication is irreversible, so any test of a registry necessarily runs after the only decision it could have informed. The remedy for a red run is to yank and publish a new version, and a yank hides a version from resolvers rather than removing it. It is built for how fast it reports, not for what it prevents.

"The registry" is three artifacts, and they fail independently, so the tier runs three times rather than once and a red result names the artifact:

| artifact | how the smoke run exercises it |
| -- | -- |
| the PyPI wheel | installed into a fresh virtual environment, then the CLI tier |
| the crates.io crate source | `cargo install --locked --version` at the tag's version, then the CLI tier |
| the release's prebuilt binaries | every checksum against `SHA256SUMS`, then the CLI tier against the one this host can execute |

The third is the one stage B depends on, because `action.yml` starts downloading and executing those binaries. The sdist is not covered: `pip install` prefers the wheel, and forcing the sdist would test a build backend rather than a published artifact.

- [x] `tests/test_cli_corpus.py` — let `_runners()` take the Rust binary's path from the environment rather than only from `target/release`. The docstring already promises that a second implementation is one entry in `_runners()` and no change to any test, and this is that entry. Done as `RUST_BINARY`, which resolves the path it is given, because a case runs with its working directory inside a scratch tree and a relative path would otherwise mean one thing to the harness and another to the process it starts. A path that was named and is missing raises rather than skipping: the caller stated which binary it meant. The Python side needed nothing, as expected — `-m` resolves through `sys.executable`, and with a `src` layout a checkout on the working directory does not shadow an installed package. Measured on 2026-08-20 against the wheel from PyPI, with the first entry of the module search path empty and the import landing in `site-packages`.
- [x] `tests/test_cli_corpus.py` — a companion switch that fails when the package under test resolves inside the repository. Without it, a smoke run whose install step quietly did nothing still tests the working tree and still reports green. `REQUIRE_RUST_BINARY` exists for that reason on the Rust side, and this is the same argument on the Python one. Done as `REQUIRE_INSTALLED_PACKAGE`, which asks the interpreter under test where it imports the package from. It tests against `src/` rather than against the whole checkout, because a virtual environment inside the repository is the ordinary layout here: a `site-packages` under the repository root holds a real install, while `src/markdown_prose_hooks` is the working tree whether an editable install or the current directory led there.
- [x] `.github/workflows/release.yml` — a job needing `[binaries, pypi, crates]` that installs the exact version the tag published and runs the CLI tier against all three artifacts. Pin the version rather than resolving the newest, or a release running concurrently makes the job test something else. Bound the retry on the crates.io index: it can lag a publish by seconds, and an unbounded wait converts a propagation delay into a job that never finishes. Done as a `smoke` job calling `smoke.yml`, which takes the tag as an input. Both installs retry six times at twenty seconds, so a lagging index costs at most two minutes and cannot hang the job.
- [x] A scheduled workflow doing the same against the current published version. This is the one that finds later breakage rather than publication mistakes: a yanked transitive dependency, a change in registry behavior, a new Python the wheel does not cover. The release-time job cannot find any of those, because it runs once and passes. Done as a weekly `schedule` on the same file, which resolves the newest release rather than reading a version out of the manifests — those are bumped before a tag is cut, so a manifest read would spend the interval failing to install a version nobody published. One thing to know about it: GitHub disables a schedule after 60 days without repository activity, and reports nothing when it does.
- [x] Decide whether the smoke runs anywhere but Linux. The CLI tier is the tier that pins path handling, line endings and exit codes, which is where Windows diverges, so a Linux-only smoke exercises the platform least likely to break. Decided: all three, matching the `parity` matrix, on the argument in the sentence above. Proven on 2026-08-21 against `v0.0.1` in run 32455079116, where each platform verified all six checksums and ran the tier three times. The interpreter follows the runner image rather than a pin, which is how a Python the wheel does not survive shows up here — Ubuntu resolved 3.12.3, Windows 3.12.10, and macOS 3.14.6, so the wheel is already known to run on an interpreter released after it. Windows skips one case and so reports 35 where the others report 36, which is the permission case `_apply_modes` skips wherever a mode does not take, exactly as it does in `parity`.

The first run of that workflow failed on all three platforms, for a reason none of these items anticipated: it checked out the tag, so it ran the harness that tag carried, and `v0.0.1` predates both switches above. Both were ignored, the guard against an install step doing nothing was inert, and the Rust runner went looking in a build tree it had never built. The harness now comes from the ref the workflow runs on and the corpus still comes from the tag, which is the one split worth remembering here: the switches may postdate a tag, while the specification an artifact was published against may not be replaced by a later one.
