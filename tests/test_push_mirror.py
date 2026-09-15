"""Tests for the mirror push.

``scripts/push_mirror.py`` writes to the two repositories a consumer pins
``rev:`` at, and a ruleset freezes every ``v*.*.*`` tag there, so a wrong write
is superseded rather than corrected. Its module docstring names the properties
that make it safe to run unattended: it replaces rather than merges, appends
rather than rewrites, refuses to advance past a tag it cannot move, and treats
a refused write as a failure rather than as a quiet success. Each test below
pins one of them.

Every request is served by a scripted transport rather than by the network.
Routes are keyed on method and full URL, so a test states the endpoints it
expects and an unrouted call fails instead of returning something plausible.
"""

import email.message
import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from scripts.push_mirror import blob_id, local_state, main, remote_state, tag_exists

REPOSITORY = 'michen00/markdown-prose-hooks-py'
BRANCH = 'main'
TAG = 'v1.2.3'
HEADLINE = 'Generate the mirror'
AUTH = 'not-a-real-credential'
HEAD = 'a' * 40
NEW_HEAD = 'b' * 40
TAGGED_AT = 'c' * 40

API = 'https://api.github.com'
REF_URL = f'{API}/repos/{REPOSITORY}/git/ref/heads/{BRANCH}'
TREE_URL = f'{API}/repos/{REPOSITORY}/git/trees/{HEAD}?recursive=1'
TAG_URL = f'{API}/repos/{REPOSITORY}/git/ref/tags/{TAG}'
REFS_URL = f'{API}/repos/{REPOSITORY}/git/refs'
GRAPHQL_URL = f'{API}/graphql'


# -- the scripted transport --


@dataclass(frozen=True)
class Call:
    """One request the script made."""

    method: str
    url: str
    body: dict[str, Any] | None


class Transport:
    """A scripted stand-in for ``urlopen`` that records what was sent."""

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        """Serve ``routes``, keyed on method and full URL."""
        self.routes = routes
        self.calls: list[Call] = []

    def __call__(self, request: urllib.request.Request) -> io.BytesIO:
        """Record one request, then serve or raise whatever its route holds.

        The response is a ``BytesIO`` because that is already what the caller
        needs: a context manager that reads back bytes.
        """
        data = request.data
        body = json.loads(data) if isinstance(data, bytes) else None
        method = request.get_method()
        self.calls.append(Call(method, request.full_url, body))
        if (method, request.full_url) not in self.routes:
            message = f'unrouted {method} {request.full_url}'
            raise AssertionError(message)
        route = self.routes[method, request.full_url]
        if isinstance(route, urllib.error.HTTPError):
            raise route
        return io.BytesIO(json.dumps(route).encode())

    def reached(self, method: str, url: str) -> bool:
        """Report whether one endpoint was called."""
        return any(call.method == method and call.url == url for call in self.calls)

    def sent_to(self, method: str, url: str) -> dict[str, Any]:
        """Return the body of the one call made to one endpoint."""
        bodies = [
            call.body
            for call in self.calls
            if call.method == method and call.url == url
        ]
        assert len(bodies) == 1, f'{method} {url} was called {len(bodies)} times'
        assert bodies[0] is not None
        return bodies[0]


def http_error(code: int, detail: str = 'refused') -> urllib.error.HTTPError:
    """Return an error whose body reads back as ``detail``, as the API's would."""
    return urllib.error.HTTPError(
        'https://api.github.com/somewhere',
        code,
        'error',
        email.message.Message(),
        io.BytesIO(detail.encode()),
    )


def routes(
    *,
    blobs: dict[str, str],
    tagged: bool = False,
    signed: bool = True,
) -> dict[tuple[str, str], object]:
    """Return a whole route table: a branch holding ``blobs``, and its tag."""
    return {
        ('GET', REF_URL): {'object': {'sha': HEAD}},
        ('GET', TREE_URL): {
            'truncated': False,
            'tree': [
                {'path': path, 'sha': sha, 'type': 'blob'}
                for path, sha in blobs.items()
            ],
        },
        ('GET', TAG_URL): (
            {'object': {'sha': TAGGED_AT}} if tagged else http_error(404)
        ),
        ('POST', GRAPHQL_URL): {
            'data': {
                'createCommitOnBranch': {
                    'commit': {'oid': NEW_HEAD, 'signature': {'isValid': signed}}
                }
            }
        },
        ('POST', REFS_URL): {'ref': f'refs/tags/{TAG}'},
    }


def write_tree(root: Path, files: dict[str, bytes]) -> Path:
    """Write ``files`` under ``root``, creating parents, and return ``root``."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def run(
    transport: Transport,
    tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_past_tag: bool = False,
) -> int:
    """Run ``main`` against a scripted transport and a real directory."""
    monkeypatch.setenv('GITHUB_TOKEN', AUTH)
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    argv = [
        '--repository',
        REPOSITORY,
        '--tree',
        str(tree),
        '--tag',
        TAG,
        '--headline',
        HEADLINE,
    ]
    if allow_past_tag:
        argv.append('--allow-past-tag')
    return main(argv)


# -- the object id, which decides what counts as changed --


@pytest.mark.parametrize(
    ('content', 'object_id'),
    [
        (b'', 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'),
        (b'hello\n', 'ce013625030ba8dba906f756967f9e9ca394464a'),
        (b'x', 'c1b0730e0133447badcfd47fd144e254807b06e1'),
    ],
)
def test_blob_id_is_the_id_git_would_give(content: bytes, object_id: str) -> None:
    """The hash matches ``git hash-object``, which is what a tree listing holds."""
    assert blob_id(content) == object_id


def test_blob_id_separates_contents_that_share_a_prefix() -> None:
    """The length header means a shorter file is not a prefix of a longer one."""
    assert blob_id(b'ab') != blob_id(b'abc')


# -- reading the generated tree --


def test_local_state_reads_every_file_as_bytes(tmp_path: Path) -> None:
    """A file at the root is keyed by its name and carries its exact bytes."""
    write_tree(tmp_path, {'README.md': b'# mirror\r\n'})
    assert local_state(tmp_path) == {'README.md': b'# mirror\r\n'}


def test_local_state_descends_into_subdirectories(tmp_path: Path) -> None:
    """A nested file is keyed by its path relative to the tree root."""
    write_tree(tmp_path, {'docs/guide.md': b'text'})
    state = local_state(tmp_path)
    assert [Path(key) for key in state] == [Path('docs/guide.md')]


def test_local_state_holds_no_entry_for_a_directory(tmp_path: Path) -> None:
    """Only files are listed, so an empty directory contributes nothing."""
    (tmp_path / 'empty').mkdir()
    assert local_state(tmp_path) == {}


# -- reading the mirror --


def test_remote_state_returns_the_head_and_only_its_blobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tree entry is not a file, so it is left out of the blob map."""
    transport = Transport(
        {
            ('GET', REF_URL): {'object': {'sha': HEAD}},
            ('GET', TREE_URL): {
                'truncated': False,
                'tree': [
                    {'path': 'README.md', 'sha': '1' * 40, 'type': 'blob'},
                    {'path': 'docs', 'sha': '2' * 40, 'type': 'tree'},
                ],
            },
        }
    )
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    assert remote_state(REPOSITORY, BRANCH, AUTH) == (HEAD, {'README.md': '1' * 40})


def test_a_truncated_tree_listing_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short read would read as files already gone, so it exits instead."""
    transport = Transport(
        {
            ('GET', REF_URL): {'object': {'sha': HEAD}},
            ('GET', TREE_URL): {'truncated': True, 'tree': []},
        }
    )
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    with pytest.raises(SystemExit, match='truncated'):
        remote_state(REPOSITORY, BRANCH, AUTH)


def test_a_failed_read_exits_rather_than_reporting_an_empty_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable branch is not an empty one; the status and detail are kept."""
    transport = Transport({('GET', REF_URL): http_error(500, 'upstream is down')})
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    with pytest.raises(SystemExit, match='500: upstream is down'):
        remote_state(REPOSITORY, BRANCH, AUTH)


@pytest.mark.parametrize(
    ('route', 'present'),
    [({'object': {'sha': TAGGED_AT}}, True), (http_error(404), False)],
)
def test_tag_exists_answers_from_the_ref(
    route: object,
    present: bool,  # noqa: FBT001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tag ref that resolves means the version is already spoken for."""
    transport = Transport({('GET', TAG_URL): route})
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    assert tag_exists(REPOSITORY, TAG, AUTH) is present


def test_only_a_404_reads_as_an_absent_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence is one status code. A refusal is not an answer about the tag."""
    transport = Transport({('GET', TAG_URL): http_error(403, 'token expired')})
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    with pytest.raises(SystemExit, match='403: token expired'):
        tag_exists(REPOSITORY, TAG, AUTH)


# -- what the run decides to write --


def test_a_missing_credential_exits_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is read or written without a token to authenticate it."""
    transport = Transport({})
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    with pytest.raises(SystemExit, match='GITHUB_TOKEN is unset'):
        main(
            [
                '--repository',
                REPOSITORY,
                '--tree',
                str(tmp_path),
                '--tag',
                TAG,
                '--headline',
                HEADLINE,
            ]
        )
    assert transport.calls == []


def test_an_unchanged_tree_commits_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mirror that already matches the generator is left where it is."""
    content = b'# mirror\n'
    write_tree(tmp_path, {'README.md': content})
    transport = Transport(routes(blobs={'README.md': blob_id(content)}))
    assert run(transport, tmp_path, monkeypatch) == 0
    assert not transport.reached('POST', GRAPHQL_URL)


def test_an_unchanged_file_is_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the file whose bytes moved is sent, which is what the ids are for."""
    same, moved = b'unchanged\n', b'rewritten\n'
    write_tree(tmp_path, {'README.md': same, 'hooks.yaml': moved})
    transport = Transport(
        routes(blobs={'README.md': blob_id(same), 'hooks.yaml': blob_id(b'before\n')})
    )
    assert run(transport, tmp_path, monkeypatch) == 0
    additions = transport.sent_to('POST', GRAPHQL_URL)['variables']['input'][
        'fileChanges'
    ]['additions']
    assert [addition['path'] for addition in additions] == ['hooks.yaml']


def test_a_file_the_generator_stopped_emitting_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror is a view of this tree, not an accumulation of every tree."""
    content = b'# mirror\n'
    write_tree(tmp_path, {'README.md': content})
    transport = Transport(
        routes(blobs={'README.md': blob_id(content), 'stale.md': '9' * 40})
    )
    assert run(transport, tmp_path, monkeypatch) == 0
    changes = transport.sent_to('POST', GRAPHQL_URL)['variables']['input'][
        'fileChanges'
    ]
    assert changes['deletions'] == [{'path': 'stale.md'}]


def test_the_write_is_conditional_on_the_head_it_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``expectedHeadOid`` is what stops two runs interleaving."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}))
    assert run(transport, tmp_path, monkeypatch) == 0
    variables = transport.sent_to('POST', GRAPHQL_URL)['variables']
    assert variables['input']['expectedHeadOid'] == HEAD


def test_a_refused_write_is_a_failure_rather_than_a_quiet_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GraphQL reports a refusal in a 200 body, which must not read as a commit."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    table = routes(blobs={})
    table['POST', GRAPHQL_URL] = {'errors': [{'message': 'stale expectedHeadOid'}]}
    transport = Transport(table)
    with pytest.raises(SystemExit, match='GraphQL refused the call'):
        run(transport, tmp_path, monkeypatch)
    assert not transport.reached('POST', REFS_URL)


def test_a_frozen_tag_refuses_to_move_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generator change under a published version is a bump, not a push."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}, tagged=True))
    assert run(transport, tmp_path, monkeypatch) == 1
    assert not transport.reached('POST', GRAPHQL_URL)
    assert not transport.reached('POST', REFS_URL)


def test_allow_past_tag_commits_without_moving_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person saying so lands a readme fix; what a pinned ``rev:`` sees holds."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}, tagged=True))
    assert run(transport, tmp_path, monkeypatch, allow_past_tag=True) == 0
    assert transport.reached('POST', GRAPHQL_URL)
    assert not transport.reached('POST', REFS_URL)


def test_the_tag_is_created_at_the_commit_this_run_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new head, not the one read at the start, is what the version names."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}))
    assert run(transport, tmp_path, monkeypatch) == 0
    assert transport.sent_to('POST', REFS_URL) == {
        'ref': f'refs/tags/{TAG}',
        'sha': NEW_HEAD,
    }


def test_an_unchanged_mirror_is_still_tagged_at_its_current_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release whose tree already matches still needs its version tag."""
    content = b'# mirror\n'
    write_tree(tmp_path, {'README.md': content})
    transport = Transport(routes(blobs={'README.md': blob_id(content)}))
    assert run(transport, tmp_path, monkeypatch) == 0
    assert transport.sent_to('POST', REFS_URL)['sha'] == HEAD


def test_an_unsigned_commit_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Signing is why this replaced a git push, so losing it cannot be silent."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}, signed=False))
    assert run(transport, tmp_path, monkeypatch) == 0
    assert '::warning::' in capsys.readouterr().out


def test_a_signed_commit_warns_about_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The warning above is a finding, not something every run prints."""
    write_tree(tmp_path, {'README.md': b'new\n'})
    transport = Transport(routes(blobs={}))
    assert run(transport, tmp_path, monkeypatch) == 0
    assert '::warning::' not in capsys.readouterr().out
