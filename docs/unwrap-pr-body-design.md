# Tidying a pull request body

A fourth surface for the transform, and the first one that is not a file. This document is the design; nothing in it is built yet.

## What prompts it

A pull request body is prose, and the authors most likely to hard-wrap it are the ones composing it in an editor or a heredoc rather than in a browser field. Measured on 2026-09-09: pull request #64 in this repository opened with 33 manual line breaks in its body, written by an agent carrying a habit from writing files. A person typing into the browser sees the ragged render in the preview pane and fixes it in seconds, so the failure this addresses belongs mostly to automated authors.

## A body is not a file, and the difference reverses the argument

GitHub renders the two surfaces through different modes of the same renderer, which is checkable rather than arguable:

| input | `mode: gfm`, which a body uses | `mode: markdown`, which a `.md` file uses |
| -- | -- | -- |
| `A wrapped\nparagraph here.` | `<p dir="auto">A wrapped<br>\nparagraph here.</p>` | `<p>A wrapped\nparagraph here.</p>` |

So in a file a manual break is invisible in the rendered output and harmful in a diff, because a one-word edit reflows a paragraph into many changed lines. That diff cost is the tool's original justification. In a body there is no diff at all, and the break is visible to every reader. The reason to unwrap a body is rendering fidelity, and it has nothing to do with the reason to unwrap a file.

## The transform is less certain on a body than on a file

This is the finding that sets the default mode, and it is a limitation rather than a bug.

In a file, an author who wants a rendered line break has to type one of the two hard-break syntaxes, because a bare newline renders as a space. The absence of that marker is therefore evidence that a break was not intended. In a body a bare newline already renders as a break, so an author who wanted one had no reason to type anything, and the absence of a marker is evidence of nothing.

The consequence is measurable. Both of these transform correctly against the corpus and wrongly against a body, measured 2026-09-09:

| body text | what the transform produces |
| -- | -- |
| `Fixes #12` / `Closes #13` / `Refs #14` on three lines | `Fixes #12 Closes #13 Refs #14` on one |
| `Reviewer guide:` above `Start at scan.rs, then paragraph.rs.` | the label pulled onto its content |

`_is_label_line` recognizes a bold label and a speaker-colon shape, not a bare word followed by a colon, so the second case is outside what the corpus pins. Neither case is a defect in the transform. Both are wrong in a body, and together they mean the action this surface takes must not exceed the certainty of its detection.

## Keeping a break on purpose

Two escape hatches already exist and both were confirmed on 2026-09-09 to work on body-shaped input. Two trailing spaces or a trailing backslash mark a hard break the transform preserves. An `unwrap-ignore` HTML comment on the line above a paragraph exempts it, and because it is an HTML comment the rendered body does not show it at all. The second is the one worth teaching an author, since it protects a whole block and leaves no visible trace.

## Three modes, ordered by what they risk

The repository already carries this axis on every channel. The four hook ids are two per implementation, one running `--write` and one running `--fail-on-change`, and the check ids describe themselves as being for repositories that want the signal rather than the edit. The composite action carries the same split through `write` defaulting to false. A body surface offering both is the existing convention rather than a new idea.

| mode | what it does | what it needs | what it risks on a false positive |
| -- | -- | -- | -- |
| `comment` | posts the tidied body for the author to copy | `pull-requests: write` | noise the author can ignore |
| `check` | fails a status check | nothing beyond the default token | blocks a pull request for no reason |
| `write` | rewrites the body in place | `pull-requests: write` | silently mangles the author's words |

There is no `mode` input. Which of the three a repository gets follows from which workflow it calls and from two booleans on the reporting one, so nothing has to be spelled twice and no combination is expressible that does not make sense.

Out of the box a consumer gets the comment and nothing else: the reporting workflow posts, and its check reports success unless the repository opts into `fail-on-wrapped`. The measured precision drop above is the reason rather than caution. A gate that blocks because `Fixes #12` and `Closes #13` are on separate lines is worse than a comment nobody has to act on, and a repository that has satisfied itself about the false positives on its own bodies can turn the gate on deliberately.

A `suggestion` block cannot make the comment mode stronger. The endpoint that carries the apply affordance requires `path` and `line`, which a body has neither of, and a bare `suggestion` fence in a conversation comment renders as an inert preformatted block labeled with a promise of a button that is not there. The comment therefore carries the tidied text in a collapsed block plus the exact command that produces it, and offers no one-click apply.

## Two files, split on lifecycle rather than on output

`check` and `comment` share a lifecycle: both reflect the current state of the body and want to run on every push. `write` wants to fire once and stop, because running it on every push fights an author who is still editing. The split falls there.

- `.github/workflows/unwrap-pr-body-check.yml` reports. It fails the check when the body carries wrapped prose, and takes an input for whether to also leave the comment.
- `.github/workflows/unwrap-pr-body.yml` edits, once.

Both are reusable workflows taking `on: workflow_call`, so the consumer supplies the trigger. Neither clones the propose and comment pair. That pair exists because computing a patch for a fork's files needs the head's content, and a body arrives in the event payload instead, so the artifact handshake buys nothing here. In write mode it would actively cost something, by letting an untrusted run name the body that gets written.

## Why the edit cannot sit on `pull_request`

A same-repository pull request does get a writable token under `pull_request` when the caller asks for one. That is confirmed against two runs, one of which posted a real comment, and it holds even though this repository's default workflow permission is read, because an explicit permissions block raises the floor rather than being capped by it.

It is still the wrong trigger for an edit. Under `pull_request` the workflow file comes from the pull request's merge commit, which is to say the version its author wrote, and the workflow file is what grants the token. So a caller holding `pull-requests: write` on that trigger extends write access to everyone who can push a branch, with no approving review in the way. The edit therefore belongs on `pull_request_target`, which reads the caller from the default branch. For a body that costs nothing, because no checkout of the head is needed in the first place.

The reporting workflow may use either trigger. `pull_request` is the better choice where fork coverage is not wanted, because it can be exercised from a branch.

## Invariants, which belong in SECURITY.md

The existing pair states two invariants there, and a change to either has to move that file. These three join them.

1. Nothing from the pull request is checked out and nothing from it is executed. The body is data throughout.
2. The body reaches the transform through a file or an environment binding, never through workflow expression interpolation into a shell command.
3. The transform runs from a pinned published release or from the default branch, never from the pull request.

The consumer-facing hazard belongs there too: granting `pull-requests: write` in a `pull_request`-triggered caller extends that write to anyone who can push a branch, and the fork approval policies do not reach a same-repository branch.

## Verification, and what it honestly covers

A `pull_request_target` caller reads from the default branch, so it cannot be exercised from a branch here, which is the hole CLAUDE.md already records for the comment half of the existing pair. That hole is one this repository left rather than one the trigger imposes. Nothing under `tests/` reads `.github/workflows` at all, and a workflow that cannot be run can still have its wiring asserted: that its trigger is the intended one, that its permissions are the narrow set claimed above, that no step checks out or executes anything from the pull request, and that the body never reaches a shell through expression interpolation. Those tests are part of this change, and writing them shrinks the existing pair's blind spot as well.

Dogfooding is worth stating precisely, because the appealing claim is false. Measured 2026-09-09, the bodies of pull requests #31, #45, #47, #52, #54, #59, #62 and #64 are all byte-identical through the transform, and so are the two bot-authored bodies. Wiring this repository up demonstrates that the workflow runs, not that it changes anything. The verifiable dogfood is the contract tests plus one deliberately wrapped body on a throwaway pull request, which is what `unwrap-fork-pair-check` exists for.

## Consumer surface

| input | default | meaning |
| -- | -- | -- |
| `comment` | `true` | leave the advisory comment |
| `fail-on-wrapped` | `false` | fail the check as well, turning the report into a gate |
| `marker` | `<!-- unwrap-pr-body -->` | how the workflow finds its own previous comment |
| `targets` | `body` | reserved, so review comments can join without a breaking change |
| `implementation` | `auto` | matches the existing pair |
| `python-version` | `3.13` | matches the existing pair |

`comment` and `fail-on-wrapped` belong to the reporting workflow; the editing one takes neither, since it neither reports nor gates.

Per-state behavior: a bot-authored pull request is skipped in every mode, a draft gets a comment but no edit, and an empty body does nothing at all.

The comment finds its own previous copy by matching a marker at the start of the body and by requiring the author to be a bot, so a human quoting the marker is never edited. It is deleted rather than edited to say resolved once the body is clean, and a run with nothing to say touches no API at all, because the common case has to be silent or the surface becomes noise.

## Out of scope

Review comments and conversation comments carry more prose than a body does, and a review reply is where the reasoning behind a change is actually recorded. They are still out of scope here, and the `targets` input exists so they can arrive without changing the interface. Shipping bodies alone is a deliberate first step rather than the finished surface.

## Open questions

Whether `marker` should be configurable at all. It exists so a consumer already using the same comment surface for something else can avoid a collision, but a configurable marker is also how two callers of this workflow in one repository would end up fighting over a single comment.

Whether the editing workflow should refuse a body it did not measure itself, rather than trusting an input. The transform is cheap enough to run twice, and an edit that reruns the transform immediately before writing cannot be handed a body to write by anything upstream of it.

Whether the false positives are common enough on real bodies to warrant a body-specific rule in the transform, which would be a corpus change rather than a workflow one, and therefore a different piece of work with a much higher bar.
