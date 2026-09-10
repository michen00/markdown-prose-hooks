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

That mechanism predicts unreliability in general. Measuring it gives a narrower and more useful answer. Of 451 pull request bodies collected from six repositories on 2026-09-09, the transform would change 27:

| what the transform does | count | authored by |
| -- | -- | -- |
| joins a hard wrap, correctly | 11 | 4 people and 7 bots |
| joins a sentence that follows a list item into that item | 15 | bots only |
| flattens a block quote holding separate URL lines | 1 | a bot |

Every incorrect change in the sample is bot-authored, and every human-authored change is correct. The 15 identical cases are Dependabot's standard footer, where a sentence follows a bullet with no blank line between them. Joining them is right in a file, which treats that line as a continuation of the list item, and wrong in a body, which renders the two lines separately.

Two conclusions follow. Skipping bot-authored pull requests removes the entire measured population of incorrect changes, which makes it a correctness requirement rather than a courtesy. And the transform's measured accuracy on human-authored bodies is 4 of 4, which is better than the mechanism above predicts.

The sample does not justify editing a consumer's bodies by default, because its 148 human-authored bodies have a single author and another repository's contributors write differently. It does justify editing in this repository.

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

By default a consumer receives the comment alone: the reporting workflow posts, and its check reports success unless the repository sets `fail-on-wrapped`. The reason is the narrowness of the sample above rather than a measured failure on human prose. One author's 148 bodies cannot predict how another repository's contributors write, and a wrong edit to someone's prose is harder to notice than a wrong comment. A repository that has run the reporting mode and read what it reports can enable editing, and can enable the gate, deliberately.

A `suggestion` block cannot strengthen the comment. The endpoint that creates a comment carrying the apply button requires `path` and `line`, and a body has neither. A bare `suggestion` fence in a conversation comment renders as an ordinary preformatted block whose label implies a button that does not exist. The comment therefore carries the tidied text in a collapsed block together with the command that produces it, and offers no single-click apply.

## Why there are two workflows

Reporting and commenting should both run on every push, because both describe the current state of the body. Editing should run once, because repeating it on every push would overwrite changes the author is still making. The two workflows divide on that difference rather than on what they output.

- `.github/workflows/unwrap-pr-body-check.yml` reports. It fails the check when the body contains wrapped prose, and it accepts an input controlling whether it also posts the comment.
- `.github/workflows/unwrap-pr-body.yml` edits the body, and runs once.

Both are reusable workflows declaring `on: workflow_call`, so the consumer supplies the trigger. Neither copies the structure of `unwrap-propose.yml` and `unwrap-comment.yml`. That pair is split because computing a patch for a fork's files requires the content of the head, whereas the body arrives in the event payload, so passing it through an artifact would add nothing. In the editing workflow, it would also introduce a risk, because an untrusted run would then determine the body that gets written. The editing workflow therefore takes no body as an input. It reads the body, transforms it, and writes the result within one job, so nothing upstream can choose what it writes.

## Why the editing workflow cannot use `pull_request`

A pull request from a branch in the same repository does receive a writable token under `pull_request` when the caller requests one. That was confirmed against two runs, one of which posted a real comment, and it holds even though this repository's default workflow permission is read, because an explicit permissions block raises that default rather than being limited by it.

`pull_request` is nevertheless the wrong trigger for an edit. Under that trigger, the workflow file is read from the pull request's merge commit, which is the version its author wrote, and the workflow file is what grants the token. A caller requesting `pull-requests: write` on that trigger therefore extends write access to everyone who can push a branch, without an approving review. The editing workflow belongs on `pull_request_target`, which reads the caller from the default branch and requires nothing extra for a body, because it doesn't need to check out the head.

The reporting workflow may use either trigger. `pull_request` is preferable where fork coverage is not wanted, because a pull request can exercise it.

## Security invariants

[SECURITY.md](../SECURITY.md) states two invariants for the existing pair, and a change to either has to move that file. These three would join them.

1. Nothing from the pull request is checked out, and nothing from it is executed. The body is treated as data throughout.
2. The body reaches the transform through a file or an environment variable, never through workflow expression interpolation into a shell command.
3. The transform runs from a pinned published release or from the default branch, never from the pull request.

One hazard belongs there for consumers rather than for this repository. Requesting `pull-requests: write` in a caller triggered by `pull_request` extends that write access to anyone who can push a branch, and the fork approval settings do not apply to a branch in the same repository.

## Verification

A caller triggered by `pull_request_target` reads its workflow file from the default branch, so a pull request here cannot exercise it. CLAUDE.md records the same limitation for the comment half of the existing pair. That limitation is partly self-inflicted, because no test under `tests/` reads `.github/workflows` at all, and a workflow that cannot be run can still have its wiring asserted. A test can require that the trigger is the intended one, that the permissions are the narrow set listed above, that no step checks out or executes anything from the pull request, and that the body never reaches a shell through expression interpolation. Writing those tests is part of this change, and they would cover the existing pair as well.

Using this repository as the first consumer proves less than it appears to. Every open pull request body here already passes through the transform unchanged, which `gh pr view <n> --json body -q .body | unwrap-markdown-prose -` reports for any of them. Enabling the workflow here would demonstrate that it runs, not that it changes anything. Genuine verification is the contract tests together with one deliberately wrapped body on a pull request in `unwrap-fork-pair-check`.

## What a consumer configures

The reference version of this belongs in [README.md](../README.md) once the workflows exist, so this section records the decisions rather than the finished documentation.

| input | default | decision it records |
| -- | -- | -- |
| `comment` | `true` | the comment is the default output |
| `fail-on-wrapped` | `false` | gating is opt-in, for the reliability reason above |
| `targets` | `body` | reserved, so review comments can be added later |
| `implementation` | `auto` | matches the existing pair |
| `python-version` | `3.13` | matches the existing pair |

The first two belong to the reporting workflow. The editing workflow accepts neither.

A bot-authored pull request is skipped in every mode, for the correctness reason measured above rather than as a preference. A draft receives a comment but no edit, and an empty body produces no action at all.

The comment carries the fixed marker `<!-- unwrap-pr-body -->` as its first line, and is not configurable. It is namespaced to this tool already, so a collision requires a consumer to have chosen the same string independently, and making it configurable is also how two callers in one repository would come to overwrite each other's comment. Adding the input later would not break a consumer, whereas removing it would. The comment locates its previous copy by matching that marker at the start of a comment body and by requiring the author to be a bot, so a comment from a person quoting the marker is never edited. It is deleted rather than rewritten once the body is clean. A run with nothing to report calls no API at all, because the common case has to be silent or the surface becomes noise.

## Out of scope

Review comments and conversation comments hold more prose than bodies do, and a review reply is where the reasoning behind a change is recorded. They remain out of scope here. The `targets` input exists so that they can be added without changing the interface, and shipping bodies alone is a deliberate first step rather than the finished surface.

## Open questions

One decision is left open, and the measurement above sharpens it. Whether the transform should gain a rule that leaves a line following a list item alone is undecided. That single shape accounts for 15 of the 16 incorrect changes in the sample, and all 15 are Dependabot's footer. Suppressing it would remove almost every incorrect change outright, rather than only those that skipping bots already avoids, which matters for a consumer that chooses to process bot pull requests. Such a rule would be a corpus change rather than a workflow change, and it needs a wider sample than one account's repositories before it earns one.
