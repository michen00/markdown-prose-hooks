"""Conservatively remove manual line breaks from Markdown prose."""

from __future__ import annotations

__all__ = (
    'FileReport',
    'UnwrapResult',
    'main',
    'match_blockquote',
    'match_list_marker',
    'match_opening_fence',
    'match_opening_html_block',
    'unwrap_markdown_prose',
)

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from re import Match
from re import compile as re_compile
from typing import Final, Literal

Matcher = Callable[[str], Match[str] | None]

_MATCH_FENCE: Final[Matcher] = re_compile(
    r'^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})'
).match
# `[0-9]` and not `\d`, in every pattern here that counts. CommonMark defines an
# ordered list marker as "a sequence of 1-9 arabic digits (0-9)", so no renderer
# reads `١. x` as a list, and matching one only declined to unwrap prose that
# renders as prose. `\d` was also not stable across the interpreters this hook
# supports -- 650 code points on 3.10's Unicode 13.0 against 680 on 3.13's 15.1 --
# so the tool did not agree with itself, and a second implementation would have
# had to pin a Unicode version to agree with either.
_MATCH_LIST: Final[Matcher] = re_compile(r'^(?:[-+*]|[0-9]+[.)])\s+').match
_MATCH_LIST_MARKER: Final[Matcher] = re_compile(
    r'^(?P<indent> {0,3})(?P<marker>[-+*]|[0-9]+[.)])(?P<sp> +)',
).match
# Single-letter alphabetic enumerators (`a.`, `b)`) are not CommonMark ordered
# markers (those require digits), so the list patterns above skip them. They are
# still load-bearing visual sub-enumerations — folding `a.`/`b.`/`c.` lines into
# a parent item's prose mangles them — so they count as structural, not prose.
_MATCH_ALPHA_LIST: Final[Matcher] = re_compile(r'^[a-zA-Z][.)]\s').match
_MATCH_BLOCKQUOTE: Final[Matcher] = re_compile(r'^(?P<indent> {0,3})>(?P<sp> ?)').match
# Peels the whole marker stack rather than one level, for the line-shape scan that
# asks what a line *is* regardless of what quotes it; matched rather than
# substituted, it also answers whether a line is quoted at all. The container
# logic uses `_MATCH_BLOCKQUOTE` above instead, because it takes one level per pass.
_BLOCKQUOTE_PREFIX_PATTERN: Final = re_compile(r'^(?: {0,3}> ?)+')
_MATCH_BLOCKQUOTE_PREFIX: Final[Matcher] = _BLOCKQUOTE_PREFIX_PATTERN.match
_SUB_BLOCKQUOTE_PREFIX = _BLOCKQUOTE_PREFIX_PATTERN.sub
_MATCH_SETEXT: Final[Matcher] = re_compile(r'^(?:=+|-+)\s*$').match
_MATCH_THEMATIC: Final[Matcher] = re_compile(r'^(?:[-*_]\s*){3,}$').match
_MATCH_LINK_REFERENCE: Final[Matcher] = re_compile(r'^\[[^\]]+\]:').match
# A badge block is a list that happens not to use list markers: every line is
# nothing but links, so joining the run turns "add one badge" into a whole-line
# diff, which is the opposite of what unwrapping is for. The fragments below
# spell one link or image token — `[text](url)`, `![alt](src)`,
# `[![alt](src)][ref]` — each admitting a single level of nesting, so a linked
# image reads as one token and a destination may carry a parenthesised tail
# such as `/wiki/Ruby_(rock)`.
_LINK_TARGET: Final = r'\((?:[^()]|\([^()]*\))*\)'
_LINK_TEXT: Final = r'\[(?:[^\[\]]|\[[^\[\]]*\])*\]'
_LINK_TOKEN: Final = rf'!?{_LINK_TEXT}(?:{_LINK_TARGET}|\[[^\[\]]*\])'
_MATCH_LINK_ONLY_LINE: Final[Matcher] = re_compile(
    rf'^\s*{_LINK_TOKEN}(?:\s+{_LINK_TOKEN})*\s*$',
).match
# Two, because one link-only line is more often a wrap point inside a paragraph
# than a block of its own, and one standing between blank lines is already
# emitted verbatim as a single-line paragraph. Only a run needs protecting.
_LINK_BLOCK_FLOOR: Final = 2
# A pipe inside an inline code span is literal text, not table syntax, so the
# table guards below blank code spans out before looking for one. Per CommonMark
# a span opens on a backtick run and closes on a run of the same length, so the
# body admits shorter runs — ``a | b` c`` is one span, not two. An unterminated
# run matches nothing and masks nothing, which leaves that ambiguous case
# structural. A real table's own delimiters sit outside backticks and survive
# masking, so the guards keep protecting tables.
_SUB_CODE_SPAN = re_compile(r'(`+)(?:(?!\1).)*\1').sub
_MATCH_HTML_TAG_NAME: Final[Matcher] = re_compile(r'^<([a-zA-Z][a-zA-Z0-9-]*)').match
_MATCH_GFM_ALERT: Final[Matcher] = re_compile(r'^\[![A-Z][A-Z0-9_-]*\][+-]?$').match
_RAW_HTML_TAGS: Final = frozenset({'pre', 'script', 'style', 'textarea'})
# Visual-layout-preserving patterns. GFM renders softbreaks inside a
# paragraph as <br>, so the author's choice to leave certain lines on
# their own is load-bearing. A paragraph where every line matches one
# of the label shapes below emits each line raw rather than joining.
_MATCH_WHOLE_LINE_BOLD: Final[Matcher] = re_compile(r'^\s*\*\*[^*]+\*\*\s*$').match
# Bold-label key/value row with the colon inside the bold (**Label:** value)
# or just outside it (**Label**: value); both are load-bearing label rows.
# The label text is required (`[^*]+`), so a bare `**:**` is not a label.
_MATCH_BOLD_COLON_PREFIX: Final[Matcher] = re_compile(
    r'^\*\*[^*]+(?::\*\*|\*\*:)'
).match
_MATCH_SPEAKER_PREFIX: Final[Matcher] = re_compile(
    r'^[A-Z][a-zA-Z0-9_.-]*(?: [A-Z][a-zA-Z0-9_.-]*){0,3}:\s',
).match
_MATCH_BARE_SPEAKER_HEADING: Final[Matcher] = re_compile(
    r'^[A-Z][a-zA-Z0-9_. -]{0,39}:$'
).match
# Speaker-turn label carrying an inline timestamp on its own line, e.g.
# `MC 0:15` directly above the utterance line. Unlike the bare heading these
# do not end in a colon and sit above a non-blank line, so they need their own
# shape to keep transcript source evidence out of the unwrap path. `[0-9]` for
# the reason given at `_MATCH_LIST`, and here the pattern was already internally
# inconsistent: its speaker half is `[A-Z]`, which is ASCII by construction.
_MATCH_TIMESTAMPED_SPEAKER_HEADING: Final[Matcher] = re_compile(
    r'^[A-Z][a-zA-Z0-9_.-]{0,19} [0-9]{1,2}:[0-9]{2}$',
).match
_MATCH_BRACKETED_LINE: Final[Matcher] = re_compile(r'^\[[^\[\]]*\]\.?\s*$').match
_TRANSCRIPT_HEADING_FLOOR: Final = 2
# Genuine transcripts are dense with speaker turns; a prose document with a few
# incidental `Capitalized:` intro lines is not. Require a minimum
# heading-to-content ratio so a long design doc is never skipped wholesale over
# a couple of colon-terminated standalone lines (observed: real transcripts run
# 0.12-0.49, a prose doc with two stray colon intros ~0.004).
_TRANSCRIPT_HEADING_RATIO: Final = 0.05
# Read from the working directory rather than from the tool's install root,
# because the working directory is the repository in every channel that matters:
# `pre-commit` runs a hook there, the composite action runs there, and a person
# runs the CLI there.
_IGNORE_FILE: Final = '.unwrapignore'
# Candidate separators are normalized on Windows and nowhere else, so a pattern
# stays one spelling across platforms while a path written the local way still
# matches. A backslash in a *pattern* is an escape everywhere, never a
# separator, which is why this governs only the candidate side.
_WINDOWS: Final = sys.platform == 'win32'


@dataclass(frozen=True, slots=True)
class UnwrapResult:
    """Result of applying the Markdown prose unwrap pass."""

    content: str
    paragraphs_unwrapped: int
    line_breaks_removed: int


@dataclass(frozen=True, slots=True)
class FileReport:
    """Per-file report emitted by the command-line interface."""

    path: str
    changed: bool
    paragraphs_unwrapped: int
    line_breaks_removed: int


@dataclass(slots=True)
class _Paragraph:
    """In-progress paragraph buffer for top-level, blockquote, or list-item prose."""

    # Spelled out rather than left as `str`, because these three values are the
    # whole domain and a typo in one of the constructor calls below is otherwise
    # silent: the container branch that reads it never fires, and the symptom is
    # a paragraph that quietly stops unwrapping. A checker rejects the typo at
    # the call site. It does not catch a typo on the *comparison* side, which
    # needs `reportUnnecessaryComparison`; that is off here, so the guard is
    # one-directional and worth knowing as such.
    kind: Literal['top', 'blockquote', 'list_item']
    first_line: str
    first_prefix: str
    first_content: str
    last_eol: str
    content_col: int = 0
    # Each entry is (raw_line, post_prefix_content). The raw is needed when
    # flush() detects a label-row layout and emits each line verbatim
    # instead of joining their content.
    extras: list[tuple[str, str]] = field(default_factory=list)


def unwrap_markdown_prose(text: str) -> UnwrapResult:
    """Return Markdown with soft wraps in paragraph contexts joined."""
    link_block_lines = _link_block_indexes(lines := _split_lines(text, keepends=True))
    output: list[str] = []
    append_to_output = output.append
    paragraph: _Paragraph | None = None
    paragraphs_unwrapped = 0
    line_breaks_removed = 0
    in_front_matter = _starts_front_matter(lines)
    in_fence = False
    fence_char = ''
    fence_len = 0
    html_literal_terminator = ''
    in_html_block = False
    html_block_tag = ''
    in_bq_fence = False
    bq_fence_char = ''
    bq_fence_len = 0
    bq_html_literal_terminator = ''
    in_bq_html_block = False
    bq_html_block_tag = ''

    def flush() -> None:
        """Emit the buffered paragraph, joining multi-line buffers into one line."""
        nonlocal paragraph, paragraphs_unwrapped, line_breaks_removed
        if paragraph is None:
            return
        if not paragraph.extras:
            append_to_output(paragraph.first_line)
            paragraph = None
            return
        # Preserve label-row layout: when the paragraph opens with one of the
        # label shapes (bold-colon like **Remove:**, speaker prefix like
        # `Alex:`, bracketed annotation like `[All agreed.]`), the author is
        # using GFM softbreak-as-<br> rendering for visual rows. Each label
        # line opens a row of its own; a line carrying no label is the
        # soft-wrapped tail of the row above and joins it. Requiring *every*
        # line to be a label instead collapsed the whole block as soon as one
        # value wrapped, which is the common shape for the last field.
        if _is_label_line(paragraph.first_content):
            rows: list[list[tuple[str, str]]] = [
                [(paragraph.first_line, paragraph.first_content)],
            ]
            append_to_rows = rows.append
            for raw, content in paragraph.extras:
                if _is_label_line(content):
                    append_to_rows([(raw, content)])
                else:
                    rows[-1].append((raw, content))
            joined_any = False
            for row in rows:
                if len(row) == 1:
                    append_to_output(row[0][0])
                    continue
                # Join onto the head's raw line so its prefix — blockquote
                # marker, list indent — carries over without rebuilding it,
                # which keeps every container shape working the same way.
                joined = _split_eol(row[0][0])[0].rstrip()
                for _, content in row[1:]:
                    if tail := content.strip():
                        joined = f'{joined} {tail}'
                append_to_output(joined + _split_eol(row[-1][0])[1])
                line_breaks_removed += len(row) - 1
                joined_any = True
            if joined_any:
                paragraphs_unwrapped += 1
            paragraph = None
            return
        joined = paragraph.first_content.strip()
        for _, content in paragraph.extras:
            if content_stripped := content.strip():
                joined = f'{joined} {content_stripped}'
        append_to_output(paragraph.first_prefix + joined + paragraph.last_eol)
        paragraphs_unwrapped += 1
        line_breaks_removed += len(paragraph.extras)
        paragraph = None

    def emit_pass_through(raw: str, body: str) -> None:
        """Emit ``raw`` unchanged and arm any HTML literal/block state it opens."""
        nonlocal html_literal_terminator, in_html_block, html_block_tag
        append_to_output(raw)
        if (terminator := _match_opening_html_literal_terminator(body)) is not None:
            html_literal_terminator = terminator
            return
        if (tag := match_opening_html_block(body)) is not None:
            in_html_block = True
            html_block_tag = tag

    for index, line in enumerate(lines):
        body, eol = _split_eol(line)

        if index == 0 and in_front_matter:
            flush()
            append_to_output(line)
            continue
        if in_front_matter:
            flush()
            append_to_output(line)
            if body in {'---', '...'}:
                in_front_matter = False
            continue
        if html_literal_terminator:
            flush()
            append_to_output(line)
            if html_literal_terminator in body:
                html_literal_terminator = ''
            continue
        if in_html_block:
            flush()
            append_to_output(line)
            if f'</{html_block_tag}>' in body.lower() or (
                html_block_tag not in _RAW_HTML_TAGS and not body.strip()
            ):
                in_html_block = False
                html_block_tag = ''
            continue
        if in_fence:
            flush()
            append_to_output(line)
            if _is_closing_fence(body, fence_char, fence_len):
                in_fence = False
                fence_char = ''
                fence_len = 0
            continue
        if in_bq_fence or bq_html_literal_terminator or in_bq_html_block:
            # Container-scoped fence / HTML state armed by an opener inside a
            # blockquote (`> `````, `> <!--`, or `> <tag>`). While armed, every
            # blockquote body line passes through raw instead of being buffered,
            # so multi-line code and HTML bodies survive intact. A line without
            # the blockquote prefix means the blockquote ended without a closer
            # — drop state and reprocess.
            if (bq_state := match_blockquote(body)) is not None:
                _, rest = bq_state
                append_to_output(line)
                if bq_html_literal_terminator:
                    if bq_html_literal_terminator in rest:
                        bq_html_literal_terminator = ''
                elif in_bq_fence and _is_closing_fence(
                    rest,
                    bq_fence_char,
                    bq_fence_len,
                ):
                    in_bq_fence = False
                    bq_fence_char = ''
                    bq_fence_len = 0
                elif in_bq_html_block and (
                    f'</{bq_html_block_tag}>' in rest.lower()
                    or (bq_html_block_tag not in _RAW_HTML_TAGS and not rest.strip())
                ):
                    in_bq_html_block = False
                    bq_html_block_tag = ''
                continue
            in_bq_fence = False
            bq_fence_char = ''
            bq_fence_len = 0
            bq_html_literal_terminator = ''
            in_bq_html_block = False
            bq_html_block_tag = ''

        if not body.strip():
            flush()
            append_to_output(line)
            continue

        # A line inside a run of link-only lines is structure, not prose, so it
        # neither joins its neighbors nor absorbs the prose either side of it.
        # The guards above run first, which keeps a badge-shaped line inside a
        # fence, front matter, or an HTML block on its existing path.
        if index in link_block_lines:
            flush()
            append_to_output(line)
            continue

        if (opening_fence := match_opening_fence(body)) is not None:
            flush()
            fence_char, fence_len = opening_fence
            in_fence = True
            append_to_output(line)
            continue

        # Hard-break-terminated lines and whole-line-bold "labels" both
        # carry visual-layout intent that joining would destroy. Emit raw.
        if _has_hard_break(body) or _is_whole_line_bold(body):
            flush()
            emit_pass_through(line, body)
            continue

        if (bq := match_blockquote(body)) is not None:
            prefix, rest = bq
            if _is_container_structural_break(rest):
                flush()
                append_to_output(line)
                # Arm container-scoped state when the structural break opens a
                # fence or HTML block. Without it, the next `> ...` body lines
                # would be folded back into a new blockquote paragraph and
                # joined.
                if (
                    terminator := _match_opening_html_literal_terminator(rest)
                ) is not None:
                    bq_html_literal_terminator = terminator
                elif (opening := match_opening_fence(rest)) is not None:
                    in_bq_fence = True
                    bq_fence_char, bq_fence_len = opening
                elif (tag := match_opening_html_block(rest)) is not None:
                    in_bq_html_block = True
                    bq_html_block_tag = tag
                continue
            if (
                paragraph is not None
                and paragraph.kind == 'blockquote'
                and _MATCH_SPEAKER_PREFIX(rest) is None
            ):
                paragraph.extras.append((line, rest))
                paragraph.last_eol = eol
            else:
                flush()
                paragraph = _Paragraph(
                    kind='blockquote',
                    first_line=line,
                    first_prefix=prefix,
                    first_content=rest,
                    last_eol=eol,
                )
            continue

        if (lst := match_list_marker(body)) is not None:
            prefix, content_col, rest = lst
            flush()
            if _is_container_structural_break(rest):
                append_to_output(line)
                continue
            paragraph = _Paragraph(
                kind='list_item',
                first_line=line,
                first_prefix=prefix,
                first_content=rest,
                last_eol=eol,
                content_col=content_col,
            )
            continue

        if _is_prose_line(body):
            if paragraph is None or _MATCH_SPEAKER_PREFIX(body) is not None:
                flush()
                paragraph = _Paragraph(
                    kind='top',
                    first_line=line,
                    first_prefix='',
                    first_content=body,
                    last_eol=eol,
                )
            else:
                paragraph.extras.append((line, body))
                paragraph.last_eol = eol
            continue

        if paragraph is not None and paragraph.kind == 'list_item':
            leading_spaces = len(body) - len(body.lstrip(' '))
            if leading_spaces >= paragraph.content_col:
                inner = body[leading_spaces:]
                if not _is_container_structural_break(inner):
                    paragraph.extras.append((line, inner))
                    paragraph.last_eol = eol
                    continue

        flush()
        emit_pass_through(line, body)

    flush()
    return UnwrapResult(
        content=''.join(output),
        paragraphs_unwrapped=paragraphs_unwrapped,
        line_breaks_removed=line_breaks_removed,
    )


def _starts_front_matter(lines: list[str]) -> bool:
    """Return ``True`` when ``lines`` opens with closeable YAML front matter."""
    # A bare `---` at the start of a file is ambiguous: it can be either YAML
    # front-matter open or a Markdown thematic break. Only treat it as front
    # matter when a closing `---`/`...` is reachable anywhere later in the
    # file (a bounded scan would corrupt legitimate long YAML headers); when
    # no closer exists the main loop is free to unwrap the rest of the
    # document.
    if not lines or _split_eol(lines[0])[0].removeprefix('\ufeff') != '---':
        return False
    return any(_split_eol(line)[0] in {'---', '...'} for line in lines[1:])


def match_opening_fence(body: str) -> tuple[str, int] | None:
    """Return ``(fence_char, fence_len)`` if ``body`` opens a fenced code block."""
    if (match := _MATCH_FENCE(body)) is None:
        return None
    fence = match.group('fence')
    return fence[0], len(fence)


def match_opening_html_block(body: str) -> str | None:
    """Return the tag name if ``body`` opens a multi-line HTML block."""
    # Rejects comments / PIs / doctypes / closing tags / self-closing forms,
    # and tags that already close on the same line (e.g. `<div>x</div>`).
    stripped = body.strip()
    if not stripped.startswith('<'):
        return None
    if stripped.startswith(('<!--', '-->', '<?', '<![', '<!', '</')):
        return None
    if stripped.endswith('/>'):
        return None
    if (match := _MATCH_HTML_TAG_NAME(stripped)) is None:
        return None
    name = match.group(1).lower()
    if f'</{name}>' in stripped.lower():
        return None
    return name


def _match_opening_html_literal_terminator(body: str) -> str | None:
    """Return the terminator for a multi-line CommonMark HTML literal block."""
    stripped = body.lstrip()
    for opener, terminator in (
        ('<!--', '-->'),
        ('<?', '?>'),
        ('<![CDATA[', ']]>'),
    ):
        if stripped.startswith(opener) and terminator not in stripped[len(opener) :]:
            return terminator
    if (
        len(stripped) > 2
        and stripped.startswith('<!')
        and stripped[2].isascii()
        and stripped[2].isupper()
        and '>' not in stripped[3:]
    ):
        return '>'
    return None


def _is_closing_fence(body: str, fence_char: str, fence_len: int) -> bool:
    """Return ``True`` if ``body`` closes a fence of the given char and length."""
    stripped = body.lstrip(' ')
    if len(body) - len(stripped) > 3:
        return False
    closing = fence_char * fence_len
    if not stripped.startswith(closing):
        return False
    return {*stripped[len(closing) :].strip()} <= {fence_char}


def match_blockquote(body: str) -> tuple[str, str] | None:
    """Return ``(prefix, rest)`` if ``body`` opens with a blockquote marker."""
    if (match := _MATCH_BLOCKQUOTE(body)) is None:
        return None
    return body[: match.end()], body[match.end() :]


def match_list_marker(body: str) -> tuple[str, int, str] | None:
    """Return ``(prefix, content_col, rest)`` if ``body`` opens with a list marker."""
    if (match := _MATCH_LIST_MARKER(body)) is None:
        return None
    return body[: match.end()], match.end(), body[match.end() :]


def _masked_code_spans(body: str) -> str:
    """Return ``body`` with every inline code span blanked out to spaces."""
    # Same length out as in, so a caller may still reason about columns.
    return _SUB_CODE_SPAN(lambda match: ' ' * len(match.group()), body)


def _is_container_structural_break(content: str) -> bool:
    """Return ``True`` for container content that should not unwrap as prose."""
    # Headings, nested lists, tables, HTML, admonitions, nested blockquotes,
    # link references, setext/thematic break markers, whole-line-bold labels,
    # and fenced code openers (``` / ~~~) — anything that carries its own
    # block-level grammar or layout intent inside a blockquote or list item.
    # Fence detection matters for list items where the marker pushes content
    # past column 3, so the main loop's `_MATCH_FENCE` (0–3 indent only)
    # misses an indented code fence opener and would otherwise let the body
    # collapse into the list paragraph.
    return (
        True
        if (
            not (stripped := content.strip())
            or content.startswith(('    ', '\t'))
            or stripped.startswith(
                ('#', '<', '>', ':', '!!!', '???', '{%', '{{', '%}', '}}'),
            )
            or _MATCH_GFM_ALERT(stripped) is not None
            or '|' in _masked_code_spans(stripped)
            or _MATCH_LIST(stripped) is not None
            or _MATCH_ALPHA_LIST(stripped) is not None
            or _MATCH_SETEXT(stripped) is not None
            or _MATCH_THEMATIC(stripped) is not None
            or _MATCH_FENCE(stripped) is not None
            or _is_whole_line_bold(stripped)
        )
        else _MATCH_LINK_REFERENCE(stripped) is not None
    )


def _is_whole_line_bold(body: str) -> bool:
    """Return ``True`` when ``body`` is entirely one bold token (e.g. ``**Title**``)."""
    return _MATCH_WHOLE_LINE_BOLD(body) is not None


def _is_label_line(content: str) -> bool:
    """Return ``True`` when ``content`` matches a visual-layout label shape."""
    # Bold-colon prefix: `**Remove:** content`, `**On X**: "quote"`.
    # Speaker prefix:    `Alex: "utterance"`, `Jordan: "Mhm."`.
    # Bracketed line:    `[All agreed.]`, `[stage direction]`.
    # Whole-line bold:   `**1. Title**` (rare here; handled in main loop too).
    stripped = content.lstrip()
    return not (
        _MATCH_BOLD_COLON_PREFIX(stripped) is None
        and _MATCH_SPEAKER_PREFIX(stripped) is None
        and _MATCH_BRACKETED_LINE(stripped) is None
        and _MATCH_WHOLE_LINE_BOLD(stripped) is None
    )


def _is_prose_line(body: str) -> bool:
    """Return ``True`` when ``body`` is a top-level prose line eligible for unwrap."""
    return (
        False
        if (
            not (stripped := body.strip())
            or body != body.lstrip()
            or _has_hard_break(body)
            or stripped.startswith(
                ('#', '<', '>', ':', '!!!', '???', '{%', '{{', '%}', '}}', '-->'),
            )
            or '|' in _masked_code_spans(stripped)
            or _MATCH_LIST(stripped) is not None
            or _MATCH_ALPHA_LIST(stripped) is not None
            or _MATCH_SETEXT(stripped) is not None
            or _MATCH_THEMATIC(stripped) is not None
        )
        else _MATCH_LINK_REFERENCE(stripped) is None
    )


def _is_link_only_line(body: str) -> bool:
    """Return ``True`` when ``body`` holds links and images and nothing else.

    Any blockquote markers come off first, so a quoted badge block is recognized
    the same way a bare one is; leaving them on made ``> [![A](a.svg)][ref]``
    prose, and a quoted run then joined into one line. Every level comes off,
    because a deeper marker still leaves a line that is nothing but links, and a
    line quoted deeper than its neighbors must not split the run they share. A
    line carrying no marker at all answers ``True`` as well, since it may be a
    lazy continuation of a quoted paragraph, which CommonMark renders inside the
    quote. Whether such a line shares a run with a quoted neighbor turns on
    which of the two comes first, so that belongs to ``_link_block_indexes``
    rather than to a test that is shown one line and no order.

    What the markers leave behind is read the way the container logic reads it:
    four spaces or a tab past the marker is indented code, so a lone link inside
    it is not a badge and answers ``False``. That test applies only once a marker
    has come off, because the same indentation with no marker in front of it may
    be a list item's content column, which the list branch consumes as content
    rather than as code — and the whole point of a badge run is to hold together
    a block indented under an item.
    """
    if (rest := _SUB_BLOCKQUOTE_PREFIX('', body)) != body and rest.startswith(
        ('    ', '\t'),
    ):
        return False
    return _MATCH_LINK_ONLY_LINE(rest) is not None


def _link_block_indexes(lines: list[str]) -> frozenset[int]:
    """Return the indexes of every line sitting inside a run of link-only lines."""
    # A run is what makes a badge block structural, and the main loop sees one
    # line at a time, so the runs are measured up front. The trailing sentinel
    # closes a run that reaches the end of the file.
    indexes: set[int] = set()
    update_indexes = indexes.update
    run_start = 0
    run_quoted = False

    def close_run(end: int) -> None:
        """Record the run ending just below ``end`` when it clears the floor."""
        if end - run_start >= _LINK_BLOCK_FLOOR:
            update_indexes(range(run_start, end))

    for index, line in enumerate([*lines, '']):
        body = _split_eol(line)[0]
        if not _is_link_only_line(body):
            close_run(index)
            run_start = index + 1
            continue
        # A marker-less line reads as a lazy continuation of the quoted
        # paragraph above it, which is why a run may lose its markers partway
        # through. It cannot gain them: a quoted line arriving on top of an
        # unquoted run is a blockquote interrupting a paragraph, and the lines
        # above it are outside the quote, so the run ends and a new one opens
        # with the quoted line.
        quoted = _MATCH_BLOCKQUOTE_PREFIX(body) is not None
        if index == run_start:
            run_quoted = quoted
        elif quoted and not run_quoted:
            close_run(index)
            run_start = index
            run_quoted = True
    return frozenset(indexes)


def _has_hard_break(body: str) -> bool:
    """Return ``True`` if ``body`` ends with a Markdown hard-break marker."""
    return body.endswith(('\\', '  '))


def _split_eol(line: str) -> tuple[str, str]:
    r"""Return ``(body, eol)``; ``eol`` is ``\\r\\n``, ``\\n``, ``\\r``, or ``''``."""
    if line.endswith('\r\n'):
        return line[:-2], '\r\n'
    if line.endswith('\n'):
        return line[:-1], '\n'
    if line.endswith('\r'):
        return line[:-1], '\r'
    return line, ''


def _split_lines(text: str, *, keepends: bool = False) -> list[str]:
    r"""Split ``text`` on ``\r\n``, ``\n`` and ``\r``, and on nothing else.

    Deliberately not ``str.splitlines``, which recognizes ten boundaries. The
    seven extra ones — ``\v``, ``\f``, ``U+001C``-``U+001E``, ``U+0085``,
    ``U+2028``, ``U+2029`` — do not merely over-unwrap here, they lose data:
    a paragraph carrying one is read as two soft-wrapped lines and joined, and
    because the join calls ``strip()`` and Python counts every one of the seven
    as whitespace, the separator is deleted rather than preserved between the
    halves. Declining to unwrap is a judgment call; deleting a character the
    author wrote is not.

    No Markdown renderer treats any of the seven as a line break, so nothing is
    given up. The narrow set is also the stable one: which code points
    ``splitlines`` accepts is a property of the interpreter, and pinning
    behavior to that makes a second implementation chase a moving target in a
    language whose standard library draws the line somewhere else entirely.

    ``corpus/cases/a-vertical-tab-is-not-a-line-boundary`` and its ``U+2028``
    twin pin both halves of this.
    """
    lines: list[str] = []
    append_to_lines = lines.append
    start = index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == '\r':
            end = index + 2 if text[index + 1 : index + 2] == '\n' else index + 1
        elif character == '\n':
            end = index + 1
        else:
            index += 1
            continue
        append_to_lines(text[start:end] if keepends else text[start:index])
        index = start = end
    if start < length:
        append_to_lines(text[start:])
    return lines


class _DoubleStar:
    """Sentinel for a `**` segment, which is the only one crossing separators."""

    __slots__ = ()

    def __repr__(self) -> str:
        """Return the pattern text this stands for."""
        return '**'


_DOUBLE_STAR: Final = _DoubleStar()
_Segment = _DoubleStar | str


@dataclass(frozen=True, slots=True)
class _IgnorePattern:
    """One parsed line of a `.unwrapignore` file or one ``--exclude`` glob."""

    negated: bool
    dir_only: bool
    anchored: bool
    segments: tuple[_Segment, ...]


def _collapse_segment(segment: str) -> _Segment:
    """Return one path segment as `**`, or with its star runs collapsed.

    A segment made of nothing but stars is `**` however many were typed, which
    keeps `***` from being a third thing nobody can predict. Stars adjacent to
    other characters cannot cross a separator whatever their number, so a run
    inside a segment collapses to one — `a**b` and `a*b` are the same pattern,
    and writing them differently must not make them behave differently.
    """
    if set(segment) == {'*'}:
        return _DOUBLE_STAR if len(segment) > 1 else '*'
    collapsed: list[str] = []
    for character in segment:
        if character != '*' or not collapsed or collapsed[-1] != '*':
            collapsed.append(character)
    return ''.join(collapsed)


def _parse_ignore_pattern(line: str) -> _IgnorePattern | None:
    """Return the pattern ``line`` describes, or ``None`` if it describes none."""
    # Trailing whitespace goes, because it is almost always an editing accident
    # and a pattern that silently depends on an invisible character is a bad
    # trade. `\ ` keeps a genuinely intended one, and `\#` / `\!` keep a leading
    # character that would otherwise be a comment marker or a negation.
    while line.endswith((' ', '\t')) and not line.endswith('\\ '):
        line = line[:-1]
    if not line or line.startswith('#'):
        return None
    negated = line.startswith('!')
    if negated:
        line = line[1:]
    line = line.replace('\\#', '#').replace('\\!', '!').replace('\\ ', ' ')
    dir_only = line.endswith('/')
    if dir_only:
        line = line[:-1]
    anchored = line.startswith('/')
    if anchored:
        line = line[1:]
    segments = tuple(
        _collapse_segment(segment)
        for segment in line.split('/')
        if segment not in {'', '.'}
    )
    if not segments:
        return None
    return _IgnorePattern(
        negated=negated,
        dir_only=dir_only,
        anchored=anchored,
        segments=segments,
    )


def _match_glob_segment(pattern: str, text: str) -> bool:
    """Return whether one path component matches one glob segment."""
    # The classic single-saved-star backtracking walk. The wildcard branch is
    # tested BEFORE the literal branch, and that order is load-bearing rather
    # than stylistic: with the literal branch first, a text character that
    # happens to be `*` matches the pattern's `*` as a literal, no backtrack
    # point is recorded, and `*x.md` stops matching a file genuinely named
    # `*ax.md`. A star is a legal filename character everywhere this runs
    # except Windows, which is why the vector is a unit test rather than a
    # corpus fixture — the fixture could not survive a Windows checkout.
    star_pattern: int | None = None
    star_text = 0
    p = t = 0
    while t < len(text):
        if p < len(pattern) and pattern[p] == '*':
            star_pattern = p
            star_text = t
            p += 1
        elif p < len(pattern) and pattern[p] in {'?', text[t]}:
            p += 1
            t += 1
        elif star_pattern is not None:
            star_text += 1
            t = star_text
            p = star_pattern + 1
        else:
            return False
    return all(character == '*' for character in pattern[p:])


def _match_segments(
    segments: tuple[_Segment, ...], components: tuple[str, ...]
) -> bool:
    """Return whether ``segments`` matches ``components`` exactly and entirely."""
    if not segments:
        return not components
    head, tail = segments[0], segments[1:]
    if isinstance(head, _DoubleStar):
        # Zero or more components, stated once and applied everywhere rather
        # than one rule for a leading `**`, another for a trailing one, and a
        # third in the middle. The zero case is the one a naive implementation
        # misses: `a/**/b.md` has to match `a/b.md`.
        return any(
            _match_segments(tail, components[index:])
            for index in range(len(components) + 1)
        )
    return bool(
        components
        and _match_glob_segment(head, components[0])
        and _match_segments(tail, components[1:]),
    )


def _pattern_matches(pattern: _IgnorePattern, components: tuple[str, ...]) -> bool:
    """Return whether ``pattern`` selects the candidate split into ``components``."""
    # Only a leading slash anchors. Gitignore also anchors any pattern holding a
    # non-trailing slash, which is two rules for one question; this subset keeps
    # one, because full gitignore fidelity across two hand-written
    # implementations is a parity liability rather than a feature.
    starts = (0,) if pattern.anchored else tuple(range(len(components)))
    for start in starts:
        rest = components[start:]
        if not pattern.dir_only:
            if _match_segments(pattern.segments, rest):
                return True
            continue
        # A trailing slash restricts to directories, and the tool is handed
        # files, so it matches when a *proper* prefix does — `fixtures/` covers
        # `fixtures/wrapped.md` and not a file named `fixtures`.
        if any(
            _match_segments(pattern.segments, rest[:length])
            for length in range(1, len(rest))
        ):
            return True
    return False


def _split_components(raw: str) -> tuple[str, ...]:
    """Split a candidate path into components, resolving ``.`` and ``..``."""
    # Never routed through `Path` first: `Path('a/../b.md').as_posix()` keeps
    # the `..`, so a pattern spelled like the resolved path would not match it.
    components: list[str] = []
    for component in raw.replace('\\', '/').split('/') if _WINDOWS else raw.split('/'):
        if component in {'', '.'}:
            continue
        if component == '..':
            if components:
                components.pop()
            continue
        components.append(component)
    return tuple(components)


@dataclass(frozen=True, slots=True)
class _IgnoreRules:
    """Every pattern in force, in the order that decides a tie."""

    patterns: tuple[_IgnorePattern, ...]

    def excludes(self, raw_path: str) -> bool:
        """Return whether ``raw_path`` is out of scope."""
        # Last match wins, so a broad pattern can be narrowed by a later
        # negation. Without it a pattern could only ever be widened, and the
        # file would have to be written in an order nobody expects.
        components = _split_components(raw_path)
        excluded = False
        for pattern in self.patterns:
            if _pattern_matches(pattern, components):
                excluded = not pattern.negated
        return excluded


def _build_ignore_rules(
    args: argparse.Namespace,
) -> tuple[_IgnoreRules, list[str]]:
    """Return the rules in force and any error reading an explicit ignore file."""
    errors: list[str] = []
    lines: list[str] = []
    # A missing default is silent because nobody asked for it. A missing
    # `--ignore-file` was named on the command line, and honoring the default
    # instead would format every file the caller meant to protect.
    source = args.ignore_file if args.ignore_file is not None else Path(_IGNORE_FILE)
    if args.ignore_file is not None or source.is_file():
        try:
            with source.open(encoding='utf-8', newline='') as handle:
                lines = _split_lines(handle.read())
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(
                f'{source.as_posix()}: cannot read --ignore-file '
                f'({_describe_error(exc)})',
            )
    patterns = [
        pattern
        for line in [*lines, *args.exclude]
        if (pattern := _parse_ignore_pattern(line)) is not None
    ]
    return _IgnoreRules(patterns=tuple(patterns)), errors


def _describe_error(exc: OSError | UnicodeDecodeError) -> str:
    """Return the tool's own name for a read failure.

    Error strings travel in the ``--json`` payload on stdout, and stdout is the
    half of the parity boundary that must match byte for byte. Quoting the
    runtime makes that impossible: Python renders ``[Errno 2] No such file or
    directory: 'x'`` where Rust renders ``No such file or directory (os error
    2)``, and neither survives a change of platform or locale — the same errno
    carries different prose on Linux, macOS and Windows.

    So the tool says what happened in words it owns. The vocabulary is
    deliberately neither language's: ``PermissionError`` would privilege Python
    and force Rust to spell out a class name it does not have, and
    ``PermissionDenied`` would do the reverse. A phrase maps cleanly from
    Python's exception classes and from Rust's ``io::ErrorKind`` alike.

    Anything unrecognized answers ``unreadable`` rather than leaking a message,
    because an open-ended tail is an open-ended parity risk.

    The condition is resolved before the class, because for one case the class
    is itself platform-dependent: opening a directory raises
    ``IsADirectoryError`` (EISDIR) on POSIX and ``PermissionError`` (EACCES) on
    Windows. Keying on the class alone therefore let the platform back into the
    payload one level above the message this function exists to suppress, and
    the CLI tier caught it — ``is a directory`` on the runners that agree with
    the fixture, ``permission denied`` on Windows, for the identical act.
    """
    filename = getattr(exc, 'filename', None)
    try:
        if filename is not None and Path(filename).is_dir():
            return 'is a directory'
    except OSError:
        # Asking the condition can fail for precisely the paths this function
        # exists to describe: `Path.is_dir` re-raises anything outside its own
        # ignore list, so a name too long for the filesystem crashed here while
        # being described. A stat that cannot answer is not a directory answer,
        # so fall through to the class and let an unrecognized one say
        # `unreadable` — which is what the vocabulary's open end is for.
        pass
    return {
        FileNotFoundError: 'not found',
        IsADirectoryError: 'is a directory',
        NotADirectoryError: 'not a directory',
        PermissionError: 'permission denied',
        UnicodeDecodeError: 'not valid UTF-8',
    }.get(type(exc), 'unreadable')


def _collect_input_paths(
    args: argparse.Namespace,
) -> tuple[list[str], list[str]]:
    """Resolve target paths from positional args and an optional ``--files-from``."""
    # Raw strings rather than `Path`, because these are matched against ignore
    # patterns before anything opens them and `Path` normalizes on the way in:
    # `Path('a/../b.md').as_posix()` keeps the `..`, so a pattern spelled like
    # the resolved path would silently fail to match.
    paths = list(args.paths)
    errors: list[str] = []
    if args.files_from is not None:
        try:
            contents = args.files_from.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(
                f'{args.files_from.as_posix()}: cannot read --files-from '
                f'({_describe_error(exc)})',
            )
        else:
            # The same three boundaries the transform uses. A list entry holding a
            # vertical tab is one path with an odd character in it, not two paths.
            paths.extend(line for line in _split_lines(contents) if line.strip())
    return paths, errors


def _process_file(path: Path, *, write: bool) -> FileReport:
    """Read ``path``, apply the unwrap, optionally rewrite, and return a report."""
    # `newline=''` disables Python's universal-newlines translation on both
    # read and write so the file's original `\r\n` / `\r` / `\n` style is
    # passed through to `splitlines(keepends=True)` and back. The default
    # mode normalizes CRLF to LF on read, which would silently rewrite the
    # entire file with LF endings on the first unwrap that lands.
    # `Path.open` rather than `Path.read_text`, which only grew `newline` in
    # 3.13. This module also ships as a standalone pre-commit hook, which
    # cannot impose an interpreter on the repositories that install it.
    with path.open(encoding='utf-8', newline='') as handle:
        original = handle.read()
    if _is_transcript_like_markdown(original):
        return FileReport(
            path=path.as_posix(),
            changed=False,
            paragraphs_unwrapped=0,
            line_breaks_removed=0,
        )
    result = unwrap_markdown_prose(original)
    changed = result.content != original
    if write and changed:
        with path.open('w', encoding='utf-8', newline='') as handle:
            handle.write(result.content)
    return FileReport(
        path=path.as_posix(),
        changed=changed,
        paragraphs_unwrapped=result.paragraphs_unwrapped,
        line_breaks_removed=result.line_breaks_removed,
    )


def _is_transcript_like_markdown(text: str) -> bool:
    """Return whether ``text`` uses repeated speaker-heading turns."""
    lines = _split_lines(text)
    headings = 0
    non_blank = 0
    for index, line in enumerate(lines):
        body = line.strip()
        if body:
            non_blank += 1
        next_body = lines[index + 1].strip() if index + 1 < len(lines) else ''
        if _MATCH_BARE_SPEAKER_HEADING(body) is not None:
            # A bare heading (`MC:`) stands alone above a blank line.
            if next_body:
                continue
        elif _MATCH_TIMESTAMPED_SPEAKER_HEADING(body) is not None:
            # A timestamped heading (`MC 0:15`) sits directly above its utterance.
            if not next_body:
                continue
        else:
            continue
        headings += 1
    if headings < _TRANSCRIPT_HEADING_FLOOR or not non_blank:
        return False
    # Density gate: a couple of colon-terminated intro lines in a long prose
    # document must not classify the whole file as a transcript and skip it.
    return headings / non_blank >= _TRANSCRIPT_HEADING_RATIO


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Detect or remove manual line breaks in Markdown prose.',
    )
    parser.add_argument('paths', nargs='*', help='Markdown files to inspect.')
    parser.add_argument(
        '--files-from',
        type=Path,
        help='Read additional newline-delimited Markdown paths from this file.',
    )
    parser.add_argument(
        '--write',
        action='store_true',
        help='Rewrite files in place instead of only reporting changes.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Emit a machine-readable summary.',
    )
    parser.add_argument(
        '--fail-on-change',
        action='store_true',
        help='Exit non-zero when any file changed or would change.',
    )
    parser.add_argument(
        '--ignore-file',
        type=Path,
        metavar='PATH',
        help=f'Read ignore patterns from PATH instead of ./{_IGNORE_FILE}.',
    )
    parser.add_argument(
        '--exclude',
        action='append',
        default=[],
        metavar='GLOB',
        help='Skip paths matching GLOB. Repeatable; applied after the ignore file.',
    )
    return parser


def _pin_stream_newlines() -> None:
    """Stop the platform deciding what a newline is on stdout and stderr.

    Text streams translate ``\\n`` on write, so on Windows every report line
    and the whole ``--json`` payload leave as CRLF. That makes this program's
    output the one thing in the repository whose line endings the platform
    chooses, in a tool that exists to take that choice away — and it breaks the
    CLI corpus, whose ``stdout.txt`` fixtures are byte-exact precisely so a
    second implementation has something exact to match. A Rust port emitting
    ``\\n`` there would be judged against a Python run emitting ``\\r\\n``.

    Guarded rather than assumed: ``reconfigure`` arrives with ``TextIOWrapper``,
    and a replaced stream — ``pytest``'s capture, a redirect in a caller
    embedding ``main`` — need not provide it. Nothing here is worth failing a
    run over, and a stream that cannot be reconfigured is one whose newlines
    are not ours to pin anyway.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(newline='\n')


def main(argv: list[str] | None = None) -> Literal[0, 1]:
    """Run the Markdown prose unwrap command."""
    _pin_stream_newlines()
    args = _build_parser().parse_args(argv)
    reports: list[FileReport] = []
    raw_paths, errors = _collect_input_paths(args)
    rules, ignore_errors = _build_ignore_rules(args)
    errors.extend(ignore_errors)
    append_to_reports = reports.append
    append_to_errors = errors.append
    for raw in raw_paths:
        # Filtered here rather than inside any one discovery path, so exclusion
        # means the same thing whether the name arrived as an argument, through
        # `--files-from`, or from a walk. An excluded file leaves no report and
        # no error and so cannot trip `--fail-on-change`: exclusion is a
        # statement about scope, and a file that was never in scope has nothing
        # to fail about.
        if rules.excludes(raw):
            continue
        path = Path(raw)
        try:
            if path.is_symlink() or not path.exists() or not path.is_file():
                continue
        except OSError:
            # A path the tool cannot stat cannot be shown to be a regular file,
            # so it is out of scope the way a missing one is. Not merely
            # defensive: `Path.is_symlink` re-raises anything outside its own
            # ignore list of ENOENT, ENOTDIR, EBADF and ELOOP, so a name too
            # long for the filesystem left through a traceback with empty
            # stdout — abandoning every path after it, which is the exact
            # failure the errors list exists to prevent one level down.
            # Reporting it instead was the alternative and was declined,
            # because nothing here can tell an over-long name from a name that
            # simply does not exist, and the second is already silent.
            continue
        try:
            append_to_reports(_process_file(path, write=args.write))
        except (OSError, UnicodeDecodeError) as exc:
            # Reported rather than raised. Only `UnicodeDecodeError` was caught
            # here, so a file the process could not open — mode 000, a dangling
            # mount, a name too long for the filesystem — left through a
            # traceback, abandoning every other path in the same run. A
            # formatter given twenty files must not decline to format nineteen
            # of them because the first was unreadable.
            append_to_errors(f'{path.as_posix()}: cannot read ({_describe_error(exc)})')

    payload = {
        'changed': any(report.changed for report in reports),
        'files': [asdict(report) for report in reports],
        'errors': errors,
    }
    write_to_stdout = sys.stdout.write
    if args.json:
        write_to_stdout(json.dumps(payload, indent=2, sort_keys=True))
        write_to_stdout('\n')
    else:
        for report in reports:
            if report.changed:
                write_to_stdout(
                    f'{report.path}: removed {report.line_breaks_removed} '
                    'manual line break(s)\n',
                )
        write_to_stderr = sys.stderr.write
        for error in errors:
            write_to_stderr(f'{error}\n')
    # `pre-commit` notices a hook rewriting a file and fails the run itself, so
    # the framework path needs no help. A GitHub Action has no such wrapper:
    # without this, a workflow step that reformatted every file still reports
    # success, which is the one outcome a check must never produce.
    if args.fail_on_change and payload['changed']:
        return 1
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
