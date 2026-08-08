#!/usr/bin/env bash
# Every tracked Markdown file except the conformance corpus fixtures.
#
# The corpus is bytes, not prose: its inputs are deliberately malformed, and
# unwrapping them rewrites each case into its own expected output. Under
# `--write` that turns the suite green against nothing; as a check it just goes
# red, which is what `hook` and `action` were doing.
#
# `.pre-commit-config.yaml` already excludes the corpus with `exclude:`, but that
# key reaches neither caller here. `pre-commit try-repo` builds its config from
# `.pre-commit-hooks.yaml` and so never reads it, and the composite action does
# its own `git ls-files` sweep. Both ask for the list here instead, so the
# exclusion has one spelling rather than three that can drift.
#
# The net is any tier under `corpus/`, not `corpus/cases/` alone, so a second
# tier arrives already covered -- the same reasoning, and the same shape, as
# .markdownlintignore. `corpus/README.md` is prose *about* the corpus and stays
# in, which a blanket `corpus/` would not allow.
#
# Fails closed: `pipefail` means an empty result exits non-zero rather than
# handing back a silently empty list, and a caller asked to check no files at all
# would otherwise report success without having read anything.
set -euo pipefail

git ls-files '*.md' '*.markdown' | grep -v '^corpus/[^/]*/'
