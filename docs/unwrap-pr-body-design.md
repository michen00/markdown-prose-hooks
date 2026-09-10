# Tidying a pull request body

This document explains a proposed fourth surface for the transform, and the first that is not a file. Nothing described here is built.

## Why this is needed

A pull request body is prose, and the authors most likely to wrap it by hand are those composing it in an editor or a shell heredoc rather than in a browser field. Pull request #64 in this repository opened with 33 manual line breaks in its body, measured on 2026-09-09, written by an agent that carried a habit over from writing files. Someone typing into the browser sees the ragged result in the preview pane and corrects it immediately, so this problem belongs mostly to automated authors.

## How a body differs from a file

GitHub renders the two surfaces through different modes of the same renderer. The difference can be measured directly:

| input | `mode: gfm`, which a body uses | `mode: markdown`, which a `.md` file uses |
| -- | -- | -- |
| `A wrapped\nparagraph here.` | `<p dir="auto">A wrapped<br>\nparagraph here.</p>` | `<p>A wrapped\nparagraph here.</p>` |

In a file, a manual line break does not appear in the rendered output, and it is expensive in a diff, because editing one word reflows a paragraph and reports many changed lines. That diff cost is the original reason the tool exists. A body has no diff, and its manual line breaks are visible to every reader. Unwrapping a body therefore improves the rendered output, which is a different reason from the one that applies to a file.

## Why the transform is less reliable on a body

In a file, an author who wants a rendered line break must type one of the two hard-break syntaxes, because a bare newline renders as a space. The absence of that syntax is therefore evidence that the author did not intend a break. In a body, a bare newline already renders as a break, so an author who wanted one had no reason to type anything, and the absence of that syntax is evidence of nothing.

Two real body shapes show the consequence. Both transform correctly against the corpus and incorrectly against a body, measured 2026-09-09:

| body text | what the transform produces |
| -- | -- |
| `Fixes #12`, `Closes #13` and `Refs #14` on three lines | all three joined onto one line |
| `Reviewer guide:` above `Start at scan.rs, then paragraph.rs.` | the label joined onto its content |

`_is_label_line` recognizes a bold label and a speaker-colon shape, but not a bare word followed by a colon, so the second case is outside what the corpus pins. Neither case is a defect. Both are wrong in a body, and together they establish the constraint that governs the rest of this design: the action taken on a surface must not exceed the reliability of detection on that surface.

## How an author keeps a line break

Two mechanisms already exist, and both were confirmed on body-shaped input on 2026-09-09. Two trailing spaces or a trailing backslash mark a hard break that the transform preserves. An `unwrap-ignore` HTML comment on the line above a paragraph exempts that paragraph, and because HTML comments are not rendered, it does not appear in the displayed body. The second mechanism is the one an advisory comment should teach, because it protects a whole block and stays invisible.

## The three modes

This repository already distinguishes reporting from editing on every channel. The four hook ids are two per implementation, one running `--write` and one running `--fail-on-change`, and the check ids state that they exist for repositories that want the signal rather than the edit. The composite action makes the same distinction through `write`, which defaults to false.

| mode | what it does | what it requires | what a false positive costs |
| -- | -- | -- | -- |
| `comment` | posts the tidied body for the author to copy | `pull-requests: write` | noise the author can ignore |
| `check` | fails a status check | nothing beyond the default token | a pull request blocked for no reason |
| `write` | rewrites the body in place | `pull-requests: write` | the author's words silently altered |

There is no `mode` input. A repository selects among the three by choosing which workflow to call and by setting two boolean inputs on the reporting one, so no setting is expressed twice and no meaningless combination can be requested.

By default a consumer receives the comment alone: the reporting workflow posts, and its check reports success unless the repository sets `fail-on-wrapped`. The reason is the measured reliability drop described above rather than general caution. A gate that blocks a pull request because `Fixes #12` and `Closes #13` occupy separate lines is worse than a comment that nobody is obliged to act on, and a repository that has confirmed the behavior on its own bodies can enable the gate deliberately.

A `suggestion` block cannot strengthen the comment. The endpoint that creates a comment carrying the apply button requires `path` and `line`, and a body has neither. A bare `suggestion` fence in a conversation comment renders as an ordinary preformatted block whose label implies a button that does not exist. The comment therefore carries the tidied text in a collapsed block together with the command that produces it, and offers no single-click apply.

## Why there are two workflows

Reporting and commenting should both run on every push, because both describe the current state of the body. Editing should run once, because repeating it on every push would overwrite changes the author is still making. The two workflows divide on that difference rather than on what they output.

- `.github/workflows/unwrap-pr-body-check.yml` reports. It fails the check when the body contains wrapped prose, and it accepts an input controlling whether it also posts the comment.
- `.github/workflows/unwrap-pr-body.yml` edits the body, and runs once.

Both are reusable workflows declaring `on: workflow_call`, so the consumer supplies the trigger. Neither copies the structure of `unwrap-propose.yml` and `unwrap-comment.yml`. That pair is split because computing a patch for a fork's files requires the content of the head, whereas the body arrives in the event payload, so passing it through an artifact would add nothing. In the editing workflow, it would also introduce a risk, because an untrusted run would then determine the body that gets written.

## Why the editing workflow cannot use `pull_request`

A pull request from a branch in the same repository does receive a writable token under `pull_request` when the caller requests one. That was confirmed against two runs, one of which posted a real comment, and it holds even though this repository's default workflow permission is read, because an explicit permissions block raises that default rather than being limited by it.

`pull_request` is nevertheless the wrong trigger for an edit. Under that trigger the workflow file is read from the pull request's merge commit, which is the version its author wrote, and the workflow file is what grants the token. A caller requesting `pull-requests: write` on that trigger therefore extends write access to everyone who can push a branch, without an approving review. The editing workflow belongs on `pull_request_target`, which reads the caller from the default branch, and which for a body requires nothing extra, because no checkout of the head is needed.

The reporting workflow may use either trigger. `pull_request` is preferable where fork coverage is not wanted, because a pull request can exercise it.

## Security invariants

[SECURITY.md](../SECURITY.md) states two invariants for the existing pair, and a change to either has to move that file. These three would join them.

1. Nothing from the pull request is checked out, and nothing from it is executed. The body is treated as data throughout.
2. The body reaches the transform through a file or an environment variable, never through workflow expression interpolation into a shell command.
3. The transform runs from a pinned published release or from the default branch, never from the pull request.

One hazard belongs there for consumers rather than for this repository. Requesting `pull-requests: write` in a caller triggered by `pull_request` extends that write access to anyone who can push a branch, and the fork approval settings do not apply to a branch in the same repository.

## Verification

A caller triggered by `pull_request_target` reads its workflow file from the default branch, so a pull request here cannot exercise it. CLAUDE.md records the same limitation for the comment half of the existing pair. That limitation is partly self-inflicted, because no test under `tests/` reads `.github/workflows` at all, and a workflow that cannot be run can still have its wiring asserted. A test can require that the trigger is the intended one, that the permissions are the narrow set listed above, that no step checks out or executes anything from the pull request, and that the body never reaches a shell through expression interpolation. Writing those tests is part of this change, and they would cover the existing pair as well.

Using this repository as the first consumer proves less than it appears to. Measured 2026-09-09, the bodies of pull requests #31, #45, #47, #52, #54, #59, #62 and #64 pass through the transform unchanged, and so do both bot-authored bodies. Enabling the workflow here would demonstrate that it runs, not that it changes anything. Genuine verification is the contract tests together with one deliberately wrapped body on a pull request in `unwrap-fork-pair-check`.

## What a consumer configures

The reference version of this belongs in [README.md](../README.md) once the workflows exist, so this section records the decisions rather than the finished documentation.

| input | default | decision it records |
| -- | -- | -- |
| `comment` | `true` | the comment is the default output |
| `fail-on-wrapped` | `false` | gating is opt-in, for the reliability reason above |
| `marker` | `<!-- unwrap-pr-body -->` | the comment is found by its own marker |
| `targets` | `body` | reserved, so review comments can be added later |
| `implementation` | `auto` | matches the existing pair |
| `python-version` | `3.13` | matches the existing pair |

The first two belong to the reporting workflow. The editing workflow accepts neither.

A bot-authored pull request is skipped in every mode, a draft receives a comment but no edit, and an empty body produces no action at all.

The comment locates its previous copy by matching the marker at the start of a comment body and by requiring the author to be a bot, so a comment from a person quoting the marker is never edited. It is deleted rather than rewritten once the body is clean. A run with nothing to report calls no API at all, because the common case has to be silent or the surface becomes noise.

## Out of scope

Review comments and conversation comments hold more prose than bodies do, and a review reply is where the reasoning behind a change is recorded. They remain out of scope here. The `targets` input exists so that they can be added without changing the interface, and shipping bodies alone is a deliberate first step rather than the finished surface.

## Open questions

Three decisions are deliberately left open.

The first is whether `marker` should be configurable. It exists so that a consumer already using this comment surface for something else can avoid a collision, but a configurable marker is also how two callers in one repository would come to overwrite each other's comment.

The second is whether the editing workflow should run the transform itself immediately before writing, rather than accepting a body as an input. The transform is cheap enough to run twice, and an editing workflow that recomputes the body cannot be handed one to write by anything upstream.

The third is whether these false positives occur often enough on real bodies to justify a body-specific rule in the transform. Such a rule would be a corpus change rather than a workflow change, and it would need stronger evidence than this document gathers.
