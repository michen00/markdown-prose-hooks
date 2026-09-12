"""Tests for the PR link freeze.

The head branch is deleted on merge, so a link pointing at
``blob/<head_branch>/<path>`` stops resolving the moment the PR lands. The
transform rewrites exactly those links to the merged head SHA and must leave
every other reference alone: SHA pins and tags (deliberate history), other
branches and repositories, commit, compare, and issue URLs, and bare SHAs.
Each test pins one edge of that boundary.
"""

import json
from pathlib import Path

import pytest
from scripts.freeze_pr_links import FreezeResult, freeze_pr_links, main

REPO = 'michen00/markdown-prose-hooks'
FORK = 'outside-contributor/markdown-prose-hooks'
HEAD_REF = 'feat/freeze-pr-links'
HEAD_SHA = '1' * 40
OTHER_SHA = '2' * 40
FILES = frozenset({'README.md', 'docs/rust-port-design.md', 'docs/a note.md'})
DIRECTORIES = frozenset({'docs', 'scripts'})


def url(ref: str, path: str, repository: str = REPO, kind: str = 'blob') -> str:
    """Return the GitHub URL for one ref and path, as a file or a directory."""
    return f'https://github.com/{repository}/{kind}/{ref}/{path}'


def freeze(
    body: str,
    *,
    head_ref: str = HEAD_REF,
    head_repository: str = REPO,
    files: frozenset[str] = FILES,
    directories: frozenset[str] = DIRECTORIES,
) -> FreezeResult:
    """Run the transform with this module's default PR coordinates."""
    return freeze_pr_links(
        body,
        head_repository=head_repository,
        base_repository=REPO,
        head_ref=head_ref,
        head_sha=HEAD_SHA,
        files_at_head=files,
        directories_at_head=directories,
    )


# -- what it freezes --


def test_a_head_branch_link_is_frozen_to_the_head_sha() -> None:
    """A Markdown link to a file on the head branch is pinned to the head SHA."""
    result = freeze(f'See [README.md]({url(HEAD_REF, "README.md")}) for more.')
    assert result.body == f'See [README.md]({url(HEAD_SHA, "README.md")}) for more.'
    assert result.changed
    assert result.rewritten == ('README.md',)


def test_a_bare_url_in_prose_is_frozen() -> None:
    """A bare URL ends at the sentence period, which is not part of the path."""
    result = freeze(f'Read {url(HEAD_REF, "docs/rust-port-design.md")}.')
    assert result.body == f'Read {url(HEAD_SHA, "docs/rust-port-design.md")}.'


def test_an_anchor_survives_the_rewrite() -> None:
    """Only the ref is replaced; a line anchor rides along untouched."""
    result = freeze(f'[design]({url(HEAD_REF, "docs/rust-port-design.md")}#L22-L31)')
    assert (
        result.body == f'[design]({url(HEAD_SHA, "docs/rust-port-design.md")}#L22-L31)'
    )
    assert result.rewritten == ('docs/rust-port-design.md',)


def test_every_head_branch_link_on_a_line_is_frozen() -> None:
    """Two matching links on one line are both rewritten."""
    body = (
        f'{url(HEAD_REF, "README.md")} and {url(HEAD_REF, "docs/rust-port-design.md")}'
    )
    expected = (
        f'{url(HEAD_SHA, "README.md")} and {url(HEAD_SHA, "docs/rust-port-design.md")}'
    )
    assert freeze(body).body == expected


def test_a_branch_name_containing_slashes_is_parsed_as_the_ref() -> None:
    """The known branch name resolves the ref-versus-path ambiguity."""
    result = freeze(
        f'[docs]({url("lint/ruff-all", "docs/rust-port-design.md")})',
        head_ref='lint/ruff-all',
    )
    assert result.body == f'[docs]({url(HEAD_SHA, "docs/rust-port-design.md")})'


def test_a_head_branch_tree_link_is_frozen() -> None:
    """A directory link rots exactly as a file link does, so it freezes too."""
    result = freeze(f'[docs]({url(HEAD_REF, "docs", kind="tree")})')
    assert result.body == f'[docs]({url(HEAD_SHA, "docs", kind="tree")})'
    assert result.rewritten == ('docs',)


def test_a_trailing_slash_on_a_directory_link_still_resolves() -> None:
    """A directory URL copied from the browser may carry a trailing slash."""
    result = freeze(f'[docs]({url(HEAD_REF, "docs/", kind="tree")})')
    assert result.body == f'[docs]({url(HEAD_SHA, "docs/", kind="tree")})'


def test_a_differently_cased_repository_is_recognized() -> None:
    """Owner and repository are case-insensitive in a URL, so this is a match.

    The rewrite emits the canonical repository name rather than preserving the
    author's casing, because the ref is not the only thing being made durable.
    """
    body = f'[README.md]({url(HEAD_REF, "README.md", "Michen00/Markdown-Prose-Hooks")})'
    result = freeze(body)
    assert result.body == f'[README.md]({url(HEAD_SHA, "README.md")})'
    assert result.rewritten == ('README.md',)


def test_a_fork_link_is_frozen_into_the_repository_that_merged_it() -> None:
    """A fork branch link is pinned to the SHA in the base repository.

    The fork's branch, and possibly the fork itself, can disappear; the merged
    commit stays reachable from the base repository, so that is the durable
    home for the reference.
    """
    body = f'[README.md]({url(HEAD_REF, "README.md", FORK)})'
    result = freeze(body, head_repository=FORK)
    assert result.body == f'[README.md]({url(HEAD_SHA, "README.md")})'
    assert result.rewritten == ('README.md',)


def test_a_base_repository_link_on_a_fork_pr_is_left_alone() -> None:
    """On a fork PR the head branch lives in the fork, so this names nothing."""
    body = f'[README.md]({url(HEAD_REF, "README.md")})'
    assert freeze(body, head_repository=FORK).body == body


def test_a_hostile_body_is_inert_text() -> None:
    """A body is data: shell metacharacters pass through byte for byte.

    Under pull_request_target the body is attacker-controlled and the token can
    write, so this pins that the transform neither interprets nor mangles it.
    """
    hostile = '$(touch pwned) && `id`; rm -rf / "double" \'single\' | tee ${IFS}'
    result = freeze(f'{hostile}\n[README.md]({url(HEAD_REF, "README.md")})\n')
    assert result.body == f'{hostile}\n[README.md]({url(HEAD_SHA, "README.md")})\n'


def test_a_percent_encoded_path_is_verified_decoded() -> None:
    """An escaped space in the URL is decoded before the path is verified."""
    result = freeze(f'[note]({url(HEAD_REF, "docs/a%20note.md")})')
    assert result.body == f'[note]({url(HEAD_SHA, "docs/a%20note.md")})'
    assert result.rewritten == ('docs/a note.md',)


# -- what it leaves alone --


def test_a_sha_pinned_link_is_left_alone() -> None:
    """An author's SHA pin is a deliberate historical reference."""
    body = f'[README.md]({url(OTHER_SHA, "README.md")})'
    result = freeze(body)
    assert result.body == body
    assert not result.changed


def test_a_tag_link_is_left_alone() -> None:
    """A tag is as intentional as a SHA, and just as durable."""
    body = f'[README.md]({url("v0.4.0", "README.md")})'
    assert freeze(body).body == body


def test_a_default_branch_link_is_left_alone() -> None:
    """A link to main means the current state of main, not this PR's head."""
    body = f'[README.md]({url("main", "README.md")})'
    assert freeze(body).body == body


def test_another_branch_sharing_a_prefix_is_left_alone() -> None:
    """A different branch under the same namespace is not the head branch."""
    body = f'[docs]({url("lint/other-branch", "docs/rust-port-design.md")})'
    assert freeze(body, head_ref='lint/ruff-all').body == body


def test_another_repository_is_left_alone() -> None:
    """The head branch name means nothing in someone else's repository."""
    body = f'[README.md]({url(HEAD_REF, "README.md", "other-org/other-repo")})'
    assert freeze(body).body == body


def test_commit_urls_and_bare_shas_are_left_alone() -> None:
    """Commit references, and the bare SHAs that autolink, are not blob links."""
    body = (
        f'Landed in https://github.com/{REPO}/commit/{OTHER_SHA} '
        f'as {OTHER_SHA}, following {OTHER_SHA[:7]}.'
    )
    assert freeze(body).body == body


def test_a_compare_url_is_left_alone() -> None:
    """A compare view names two refs and is not a file link."""
    body = f'https://github.com/{REPO}/compare/main...{HEAD_REF}'
    assert freeze(body).body == body


def test_an_issue_link_is_left_alone() -> None:
    """Issue and PR links carry no ref component to freeze."""
    body = f'Supersedes https://github.com/{REPO}/pull/21 and #12.'
    assert freeze(body).body == body


def test_a_fenced_code_block_is_left_alone() -> None:
    """A link inside a fence is sample text, not a live reference."""
    body = f'```text\n{url(HEAD_REF, "README.md")}\n```\n'
    assert freeze(body).body == body


def test_an_inline_code_span_is_left_alone() -> None:
    """A backticked URL is a sample too."""
    body = f'Write `{url(HEAD_REF, "README.md")}` in the body.'
    assert freeze(body).body == body


def test_a_double_backtick_span_is_left_alone() -> None:
    """A span opened with two backticks closes on two, per CommonMark."""
    body = f'``{url(HEAD_REF, "README.md")}`` shows the form.'
    assert freeze(body).body == body


def test_a_link_after_a_closed_code_span_is_still_frozen() -> None:
    """Only the span is protected; a live link later on the line still freezes."""
    body = f'`sample` then [README.md]({url(HEAD_REF, "README.md")})'
    assert (
        freeze(body).body == f'`sample` then [README.md]({url(HEAD_SHA, "README.md")})'
    )


def test_an_unpaired_backtick_protects_nothing() -> None:
    """A stray tick opens no span, so the link after it is still a live one."""
    body = f'a ` stray tick [README.md]({url(HEAD_REF, "README.md")})'
    assert (
        freeze(body).body == f'a ` stray tick [README.md]({url(HEAD_SHA, "README.md")})'
    )


def test_a_ref_differing_only_in_case_is_left_alone() -> None:
    """Git refs are case-sensitive, so a near-miss names a different branch."""
    body = f'[README.md]({url(HEAD_REF.upper(), "README.md")})'
    assert freeze(body).body == body


def test_a_path_missing_at_the_head_sha_is_skipped() -> None:
    """A file deleted or renamed during the PR would 404 at the head SHA."""
    body = f'[gone]({url(HEAD_REF, "docs/removed.md")})'
    result = freeze(body)
    assert result.body == body
    assert not result.changed
    assert result.skipped == ('docs/removed.md',)


def test_a_missing_directory_is_skipped() -> None:
    """A directory removed during the PR gets the same treatment as a file."""
    body = f'[plans]({url(HEAD_REF, "docs/plans", kind="tree")})'
    result = freeze(body)
    assert result.body == body
    assert result.skipped == ('docs/plans',)


def test_a_file_link_naming_a_directory_is_normalized() -> None:
    """A blob URL for a directory becomes a tree URL rather than being skipped.

    GitHub redirects the blob form to the tree form in the browser, so the link
    works while the branch lives and dies on merge -- the one shape an author
    cannot catch by clicking it. Skipping it guaranteed the rot instead.
    """
    result = freeze(f'[docs]({url(HEAD_REF, "docs")})')
    assert result.body == f'[docs]({url(HEAD_SHA, "docs", kind="tree")})'
    assert result.rewritten == ('docs',)
    assert result.skipped == ()


def test_a_directory_link_naming_a_file_is_normalized() -> None:
    """And the mirror image: a tree URL for a file becomes a blob URL."""
    result = freeze(f'[readme]({url(HEAD_REF, "README.md", kind="tree")})')
    assert result.body == f'[readme]({url(HEAD_SHA, "README.md")})'
    assert result.rewritten == ('README.md',)


def test_a_normalization_is_reported_apart_from_a_plain_freeze() -> None:
    """Changing a link's kind is a louder edit than pinning its ref, so it is counted.

    Both counts describe the same rewrite: the path is in ``rewritten`` because
    its ref moved, and in ``normalized`` because its kind did too. An operator
    who sees a `blob` become a `tree` can then account for it from the log.
    """
    result = freeze(f'[docs]({url(HEAD_REF, "docs")})')
    assert result.rewritten == ('docs',)
    assert result.normalized == ('docs',)


def test_pinning_a_ref_alone_is_not_reported_as_a_normalization() -> None:
    """The common case stays quiet: a correct link's kind never changes."""
    result = freeze(f'[README.md]({url(HEAD_REF, "README.md")})')
    assert result.rewritten == ('README.md',)
    assert result.normalized == ()


def test_a_normalized_link_survives_a_second_pass() -> None:
    """Normalizing changes the kind as well as the ref, so idempotence is retested."""
    once = freeze(f'[docs]({url(HEAD_REF, "docs")})')
    twice = freeze(once.body)
    assert twice.body == once.body
    assert not twice.changed


# -- properties --


def test_the_transform_is_idempotent() -> None:
    """Freezing an already-frozen body changes nothing."""
    once = freeze(f'[README.md]({url(HEAD_REF, "README.md")})')
    twice = freeze(once.body)
    assert twice.body == once.body
    assert not twice.changed


def test_a_body_with_nothing_to_freeze_is_unchanged() -> None:
    """A body with no head-branch link reports no change at all."""
    body = '## Summary\n\nNo links here.\n'
    result = freeze(body)
    assert result.body == body
    assert not result.changed
    assert result.rewritten == ()


# -- command line --


def cli_argv(
    tmp_path: Path, body: str, *, head_sha: str = HEAD_SHA
) -> tuple[Path, list[str]]:
    """Write the CLI's input files and return the body file and argument list."""
    body_file = tmp_path / 'body.md'
    body_file.write_text(body)
    files_file = tmp_path / 'files.txt'
    files_file.write_text('\n'.join(sorted(FILES)) + '\n')
    directories_file = tmp_path / 'directories.txt'
    directories_file.write_text('\n'.join(sorted(DIRECTORIES)) + '\n')
    return body_file, [
        '--body-file',
        str(body_file),
        '--head-repository',
        REPO,
        '--base-repository',
        REPO,
        '--head-ref',
        HEAD_REF,
        '--head-sha',
        head_sha,
        '--files-from',
        str(files_file),
        '--directories-from',
        str(directories_file),
        '--write',
        '--json',
    ]


def test_the_cli_rewrites_the_body_file_and_reports_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With --write the body file is replaced and the JSON summary says so."""
    link = f'[README.md]({url(HEAD_REF, "README.md")})\n'
    body_file, argv = cli_argv(tmp_path, link)

    code = main(argv)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['changed'] is True
    assert payload['rewritten'] == ['README.md']
    assert payload['normalized'] == []
    assert body_file.read_text() == f'[README.md]({url(HEAD_SHA, "README.md")})\n'


def test_the_cli_reports_which_links_were_normalized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The count reaches the workflow through the payload, as a list of paths."""
    body_file, argv = cli_argv(tmp_path, f'[docs]({url(HEAD_REF, "docs")})\n')

    code = main(argv)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['normalized'] == ['docs']
    assert body_file.read_text() == f'[docs]({url(HEAD_SHA, "docs", kind="tree")})\n'


def test_the_cli_leaves_the_body_file_untouched_when_nothing_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unchanged body is reported as unchanged, so no edit call follows."""
    original = f'[README.md]({url("main", "README.md")})\n'
    body_file, argv = cli_argv(tmp_path, original)

    code = main(argv)

    assert code == 0
    assert json.loads(capsys.readouterr().out)['changed'] is False
    assert body_file.read_text() == original


def test_the_cli_rejects_a_head_sha_that_is_not_a_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ref in place of the head SHA is a caller bug, not something to guess at."""
    link = f'[README.md]({url(HEAD_REF, "README.md")})\n'
    _, argv = cli_argv(tmp_path, link, head_sha='main')

    code = main(argv)

    assert code == 1
    assert json.loads(capsys.readouterr().out)['errors']
