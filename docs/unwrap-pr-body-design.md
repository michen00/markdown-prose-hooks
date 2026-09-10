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

## What changes when the surface is a body

An author who wants a rendered break in a file must type one of the two hard-break syntaxes, because a bare newline renders there as a space. The absence of that syntax is evidence that no break was intended. A body renders a bare newline as a break, so an author who wanted one had no reason to type anything, and the absence of that syntax proves nothing.

Measuring the consequence gives a precise answer. Of 451 pull request bodies collected from six repositories on 2026-09-09, the transform would change 27. Rendering every change through GitHub's own renderer in both modes shows that none of the 27 alters the structure of its document: the text a join brings together already shared one list item or one paragraph, and what the join removes is a line break inside that block.

Sixteen of the 27 still remove a break the author wanted. Fifteen are Dependabot's footer, where a sentence follows a bullet with no blank line between them, and the last is a block quote holding two URLs on separate lines. In each, the author used a bare newline to ask for a visible line, which a body grants and a file ignores. That is the mechanism above, observed: the transform reads the markup correctly and the intent wrongly, and no property of the text separates the two readings.

All sixteen were written by bots. All eleven human-authored changes remove breaks their authors plainly did not want.

## What the measurement settles

The transform needs no rule specific to bodies, and should not be given one. Conditioning its behavior on the surface would fork the specification the corpus holds and end the parity the two implementations answer for, which costs far more than sixteen joins in a bot template.

Inserting a blank line, instead of removing the break, would produce the separate paragraph Dependabot's template evidently intends, and would do so identically in both modes. That is a structural repair, not break removal, so it lies outside what this tool does.

Skipping bot-authored pull requests avoids every case observed here. That is a good reason to skip them, not a proof that they must be skipped.

The reason to default to the comment is neither unreliability nor a measured defect, because the sample shows neither. Removing a break from a body changes what every reader sees, and the author is the person entitled to approve a visible change to their own words.

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

By default a consumer receives the comment alone: the reporting workflow posts, and its check reports success unless the repository sets `fail-on-wrapped`. A repository that has run the reporting mode and read what it reports can then enable the edit, or the gate, deliberately.

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

The reference version of this belongs in [README.md](../README.md) once the workflows exist, so this section records the decisions, not the finished documentation.

| input | default | decision it records |
| -- | -- | -- |
| `comment` | `true` | the comment is the default output |
| `fail-on-wrapped` | `false` | gating is opt-in, for the reliability reason above |
| `targets` | `body` | reserved, so review comments can be added later |
| `implementation` | `auto` | matches the existing pair |
| `python-version` | `3.13` | matches the existing pair |

The first two belong to the reporting workflow. The editing workflow accepts neither.

A bot-authored pull request is skipped in every mode, for the reason the measurement gives. A draft receives a comment but no edit, and an empty body produces no action at all.

The comment carries the fixed marker `<!-- unwrap-pr-body -->` as its first line, and is not configurable. It is namespaced to this tool already, so a collision requires a consumer to have chosen the same string independently, and making it configurable is also how two callers in one repository would come to overwrite each other's comment. Adding the input later would not break a consumer, whereas removing it would. The comment locates its previous copy by matching that marker at the start of a comment body and by requiring the author to be a bot, so a comment from a person quoting the marker is never edited. It is deleted, not rewritten, once the body is clean. A run with nothing to report calls no API at all, because the common case has to be silent or the surface becomes noise.

## Out of scope

Review comments and conversation comments hold more prose than bodies do, and a review reply is where the reasoning behind a change is recorded. They remain out of scope here. The `targets` input exists so that they can be added without changing the interface, and shipping bodies alone is a deliberate first step, not the finished surface.

## Open questions

Whether the reporting workflow should present a check at all is undecided. With `fail-on-wrapped` defaulting to false, that check reports success whatever it finds, which is close to having no check, and the three modes then collapse to two. The alternatives are to fail by default, which the reasoning above argues against, or to drop the check and offer only the comment and the edit.
