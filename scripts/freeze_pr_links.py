#!/usr/bin/env python3
"""Freeze a merged PR's head-branch links to the head commit SHA.

A PR links live files on the head branch, which is the right reference
while the PR is open and a dead one the moment the branch is deleted on merge.
This rewrites exactly those links — the repository's own, on the known head
branch, for a path that still resolves at the head SHA — and leaves every other
reference alone, because a SHA or tag already in the text is the author saying
"this file as it was at this moment".
"""

from __future__ import annotations

__all__ = (
    'FreezeResult',
    'freeze_pr_links',
    'main',
)

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from re import compile as re_compile
from re import escape as re_escape
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote

if TYPE_CHECKING:
    from collections.abc import Container

_FENCE_RE: Final = re_compile(r'^ {0,3}(?P<fence>`{3,}|~{3,})')
_REPOSITORY_RE: Final = re_compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
# Git's forbidden set, inverted, rather than a hand-listed alphabet: control
# characters, space, DEL, and ~ ^ : ? * [ \\. The narrower list this replaced
# rejected 21 printable characters git accepts, and every non-ASCII name.
_REF_RE: Final = re_compile(r'^[^\x00-\x20\x7f~^:?*\[\\]+$')
_COMMIT_SHA_RE: Final = re_compile(r'^[0-9a-f]{40}$')
# A URL ends at the first character that Markdown or prose uses to close it:
# a quote, bracket, angle bracket, backtick, or space. Parentheses are counted
# in `_url_end` rather than listed here, because a Markdown destination may
# hold a balanced pair.
_URL_TERMINATORS: Final = frozenset(' \t\r\n"\'[]{}<>`|\\')
# Sentence punctuation trailing a bare URL belongs to the prose, not the path.
_TRAILING_PUNCTUATION: Final = '.,;:!?'


@dataclass(frozen=True, slots=True)
class FreezeResult:
    """Outcome of freezing one body or comment."""

    body: str
    rewritten: tuple[str, ...]
    skipped: tuple[str, ...]
    # A subset of rewritten, not a fourth outcome: these links had their kind
    # corrected as well as their ref pinned. Counted apart because an author
    # expects the ref to move and would question the kind changing.
    normalized: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether any link was rewritten, and so whether the text needs saving."""
        return bool(self.rewritten)


@dataclass(slots=True)
class _Tally:
    """What one pass over one body or comment recorded, accumulated line by line."""

    rewritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    normalized: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Rules:
    """What a line rewrite needs to recognize a link and pin it."""

    pattern: Pattern[str]
    repository: str
    head_sha: str
    files_at_head: Container[str]
    directories_at_head: Container[str]

    def pinned_prefix(self, kind: str) -> str:
        """Return the durable URL prefix that replaces a matched one."""
        # On a fork PR this changes the owner as well as the ref, which reads
        # as a mistake until you know the mechanism: merging leaves the head
        # commit reachable from the base repository through refs/pull/<n>/head,
        # and GitHub serves it under that repository's URL from then on. The
        # fork is the side that cannot be relied on — once it is deleted, a
        # link into it 404s whether it names the branch or the commit, and
        # nobody can repair it afterwards. So the base repository is not just
        # the more convenient target, it is the only one that survives.
        return f'https://github.com/{self.repository}/{kind}/{self.head_sha}/'

    def kind_at_head(self, path: str) -> str | None:
        """Return the URL kind ``path`` resolves as at the head SHA, or None.

        This asks what the path *is* rather than whether it matches what the URL
        claimed, which is what lets a mismatched link be corrected instead of
        abandoned. A path in neither list is genuinely gone and gets no kind.
        """
        if path in self.files_at_head:
            return 'blob'
        if path in self.directories_at_head:
            return 'tree'
        return None


def freeze_pr_links(  # noqa: PLR0913 -- keyword-only, so the call site names every one
    body: str,
    *,
    head_repository: str,
    base_repository: str,
    head_ref: str,
    head_sha: str,
    files_at_head: Container[str],
    directories_at_head: Container[str],
) -> FreezeResult:
    """Return ``body`` with the head branch's links pinned to the head SHA.

    Links are matched in ``head_repository``, which is the fork on a
    fork-backed pull request, and pinned into ``base_repository``, which is
    where the merged commit stays reachable after the fork's branch, or the
    fork itself, goes away. The two are the same repository on a branch PR.

    Both ``blob`` (file) and ``tree`` (directory) URLs rot when the branch is
    deleted, so both are frozen, and each is pinned to the kind its path
    actually resolves as at the head SHA — correcting the two forms against
    each other rather than abandoning a link whose kind was wrong. A path in
    neither list is genuinely gone and is left exactly as it was rather than
    pinned to a link that 404s. The caller must pass the branch name because a
    ref may contain slashes, which makes the boundary between ref and path
    ambiguous otherwise. Coordinates are validated by the caller.
    """
    pattern = _link_pattern(head_repository, head_ref)
    if head_ref == head_sha or pattern.search(body) is None:
        return FreezeResult(body=body, rewritten=(), skipped=())

    rules = _Rules(
        pattern=pattern,
        repository=base_repository,
        head_sha=head_sha,
        files_at_head=files_at_head,
        directories_at_head=directories_at_head,
    )
    tally = _Tally()
    output: list[str] = []
    append_to_output = output.append
    fence_char = ''
    fence_len = 0
    in_fence = False

    for line in body.splitlines(keepends=True):
        text = line.rstrip('\r\n')
        if in_fence:
            append_to_output(line)
            if _closes_fence(text, fence_char, fence_len):
                in_fence = False
                fence_char = ''
                fence_len = 0
            continue
        if (opening := _opens_fence(text)) is not None:
            # A body or comment can quote a head-branch URL to show the
            # link rather than to use it, and freezing a sample rewrites the
            # thing it was showing. The guard reads a line at a time, so it
            # covers a top-level fence and a span that opens and closes on one
            # line. A fence indented four spaces, an indented block, a `<pre>`
            # element and a span broken across lines are frozen like prose,
            # and the tests pin each of those. Widening it costs more than it
            # saves: skipping indented lines would skip a list item's own
            # prose and leave the link it carries to 404.
            fence_char, fence_len = opening
            in_fence = True
            append_to_output(line)
            continue
        append_to_output(_freeze_line(line, rules, tally))

    return FreezeResult(
        body=''.join(output),
        rewritten=tuple(tally.rewritten),
        skipped=tuple(tally.skipped),
        normalized=tuple(tally.normalized),
    )


def _link_pattern(repository: str, head_ref: str) -> Pattern[str]:
    """Return the matcher for one repository's head-branch file and tree URLs.

    Owner and repository are case-insensitive in a GitHub URL, so a link that
    spells them differently addresses the same repository and is recognized. A
    Git ref is case-sensitive, so the branch component must match exactly or it
    names a different branch.
    """
    return re_compile(
        r'(?i:https://github\.com/'
        + re_escape(repository)
        + r')/(?P<kind>blob|tree)/'
        + re_escape(head_ref)
        + r'/',
    )


def _freeze_line(line: str, rules: _Rules, tally: _Tally) -> str:
    """Rewrite every eligible link on one line, recording what was and was not."""
    pieces: list[str] = []
    index = 0
    code_spans = _code_span_ranges(line)
    while (match := rules.pattern.search(line, index)) is not None:
        start = match.start()
        pieces.append(line[index:start])
        end = _url_end(line, match.end())
        tail = line[match.end() : end]
        path = _path_of(tail)
        resolved_kind = rules.kind_at_head(path) if path else None
        if any(span_start <= start < span_end for span_start, span_end in code_spans):
            pieces.append(line[start:end])
        elif resolved_kind is not None:
            # The kind comes from what the path resolves as, not from what the
            # URL said, so a blob URL naming a directory is corrected to tree
            # rather than skipped. Authors write that form because GitHub
            # redirects it to tree/ in the browser: it resolves for as long as
            # the branch exists, then 404s on merge, which makes it the one
            # broken shape clicking the link cannot reveal. The path and any
            # anchor ride along untouched; only the ref and the kind change.
            pieces.append(rules.pinned_prefix(resolved_kind))
            pieces.append(tail)
            tally.rewritten.append(path)
            if resolved_kind != match.group('kind'):
                tally.normalized.append(path)
        else:
            pieces.append(line[start:end])
            if path:
                tally.skipped.append(path)
        index = end
    if not pieces:
        return line
    pieces.append(line[index:])
    return ''.join(pieces)


def _code_span_ranges(text: str) -> list[tuple[int, int]]:
    """Return the half-open spans of inline code on one line.

    A span closes on a backtick run of the same length, per CommonMark, so an
    unpaired run opens nothing and the text after it stays live.
    """
    runs: list[tuple[int, int]] = []
    index = 0
    while (index := text.find('`', index)) != -1:
        start = index
        while index < len(text) and text[index] == '`':
            index += 1
        runs.append((start, index - start))

    spans: list[tuple[int, int]] = []
    opener = 0
    while opener < len(runs):
        open_start, open_len = runs[opener]
        closer = next(
            (
                index
                for index in range(opener + 1, len(runs))
                if runs[index][1] == open_len
            ),
            None,
        )
        if closer is None:
            opener += 1
            continue
        close_start, close_len = runs[closer]
        spans.append((open_start, close_start + close_len))
        opener = closer + 1
    return spans


def _url_end(text: str, start: int) -> int:
    """Return the index one past the URL that begins at ``start``.

    A Markdown destination may hold balanced parentheses, so a closing paren
    ends the URL only when every opening paren inside it has been closed.
    Ending at the first paren instead truncates a path such as ``docs/a(b).md``
    to ``docs/a``, and that prefix is then verified in the real path's place:
    the link is left on the deleted branch, or pinned to the wrong path when
    the prefix happens to resolve.
    """
    depth = 0
    for offset in range(start, len(text)):
        character = text[offset]
        if character == '(':
            depth += 1
        elif character == ')':
            if depth == 0:
                return offset
            depth -= 1
        elif character in _URL_TERMINATORS:
            return offset
    return len(text)


def _path_of(tail: str) -> str:
    """Return the repository path a URL tail names, without anchor or query."""
    path = tail.split('#', 1)[0].split('?', 1)[0].rstrip(_TRAILING_PUNCTUATION)
    # A directory URL copied from the browser may carry a trailing slash, which
    # the tree listing does not; the slash still rides along in the rewrite.
    return unquote(path.rstrip('/'))


def _opens_fence(text: str) -> tuple[str, int] | None:
    """Return ``(fence_char, fence_len)`` if ``text`` opens a fenced code block."""
    if (match := _FENCE_RE.match(text)) is None:
        return None
    fence = match.group('fence')
    return fence[0], len(fence)


def _closes_fence(text: str, fence_char: str, fence_len: int) -> bool:
    """Return whether ``text`` closes a fence of the given character and length."""
    stripped = text.lstrip(' ')
    if len(text) - len(stripped) > 3:
        return False
    closing = fence_char * fence_len
    if not stripped.startswith(closing):
        return False
    return {*stripped[len(closing) :].strip()} <= {fence_char}


def _validate(args: argparse.Namespace) -> list[str]:
    """Return one message per malformed pull request coordinate."""
    errors: list[str] = []
    for flag, value in (
        ('--head-repository', args.head_repository),
        ('--base-repository', args.base_repository),
    ):
        if _REPOSITORY_RE.match(value) is None:
            errors.append(f'{flag}: expected owner/name, got {value!r}')
    # The reason is not injection. `freeze-pr-links.yml` writes this value into
    # `$GITHUB_OUTPUT` as `head_ref=<value>`, so a newline in it would append a
    # second `key=value` line and could forge `head_sha`. Git forbids control
    # characters in a ref, which is what makes that unreachable, and this guard
    # is where that assumption is written down.
    if _REF_RE.match(args.head_ref) is None:
        errors.append(f'--head-ref: not a valid git ref {args.head_ref!r}')
    elif _COMMIT_SHA_RE.match(args.head_ref) is not None:
        errors.append('--head-ref: a commit SHA is not a branch name')
    if _COMMIT_SHA_RE.match(args.head_sha) is None:
        errors.append(
            f'--head-sha: expected a 40-character commit SHA, got {args.head_sha!r}',
        )
    return errors


def _read_paths(path: Path) -> frozenset[str]:
    """Return the set of repository paths listed one per line in ``path``."""
    contents = path.read_text(encoding='utf-8')
    return frozenset(line for line in contents.splitlines() if line)


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Pin a merged PR's head-branch links to the head SHA.",
    )
    parser.add_argument(
        '--body-file',
        type=Path,
        required=True,
        help='The PR body or comment to read, and to rewrite under --write.',
    )
    parser.add_argument(
        '--head-repository',
        required=True,
        help='The owner/name whose head-branch links may be frozen.',
    )
    parser.add_argument(
        '--base-repository',
        required=True,
        help='The owner/name the frozen links point into, where the merge landed.',
    )
    parser.add_argument(
        '--head-ref',
        required=True,
        help="The pull request's head branch name.",
    )
    parser.add_argument(
        '--head-sha',
        required=True,
        help='The 40-character head commit SHA to pin links to.',
    )
    parser.add_argument(
        '--files-from',
        type=Path,
        required=True,
        help='Newline-delimited file paths that exist at the head SHA.',
    )
    parser.add_argument(
        '--directories-from',
        type=Path,
        required=True,
        help='Newline-delimited directory paths that exist at the head SHA.',
    )
    parser.add_argument(
        '--write',
        action='store_true',
        help='Rewrite the body file in place instead of only reporting.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Emit a machine-readable summary.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the PR link freeze over one body or comment file."""
    args = _build_parser().parse_args(argv)
    errors = _validate(args)
    result = FreezeResult(body='', rewritten=(), skipped=())
    if not errors:
        try:
            # `newline=''` disables universal-newline translation on both read
            # and write: GitHub serves bodies with CRLF, and normalizing them
            # would rewrite every line of the text instead of the links.
            # `Path.read_text` gained a `newline` parameter only in 3.13, and
            # the floor here is 3.10, so `Path.open` carries the same keyword
            # `TextIOWrapper` has always accepted.
            with args.body_file.open(encoding='utf-8', newline='') as handle:
                body = handle.read()
            files_at_head = _read_paths(args.files_from)
            directories_at_head = _read_paths(args.directories_from)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f'cannot read input ({exc})')
        else:
            result = freeze_pr_links(
                body,
                head_repository=args.head_repository,
                base_repository=args.base_repository,
                head_ref=args.head_ref,
                head_sha=args.head_sha,
                files_at_head=files_at_head,
                directories_at_head=directories_at_head,
            )
            if args.write and result.changed:
                with args.body_file.open('w', encoding='utf-8', newline='') as handle:
                    handle.write(result.body)

    payload = {
        'changed': result.changed,
        'errors': errors,
        'normalized': [*result.normalized],
        'rewritten': [*result.rewritten],
        'skipped': [*result.skipped],
    }
    write_to_stdout = sys.stdout.write
    if args.json:
        write_to_stdout(json.dumps(payload, indent=2, sort_keys=True))
        write_to_stdout('\n')
    else:
        for path in result.rewritten:
            write_to_stdout(f'{path}: pinned to {args.head_sha}\n')
        write_to_stderr = sys.stderr.write
        for error in errors:
            write_to_stderr(f'{error}\n')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
