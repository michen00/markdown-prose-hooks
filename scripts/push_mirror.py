#!/usr/bin/env python3
"""Land one generated mirror on its repository as a signed commit.

The mirrors used to be pushed with git, from a clone, under an installation
token. That works and produces unsigned commits: git signs with a key on the
machine, a runner has none, and a token authenticates the push rather than the
object. Every generated commit on both mirrors read `verified: false`, which
made `required_signatures` on a mirror's default branch unaddable -- the rule
would have refused the only thing that ever writes there.

GitHub signs a commit it creates itself. The GraphQL `createCommitOnBranch`
mutation is the one that takes a whole file set rather than a path at a time,
so the mirror still lands as one commit, and it comes back verified with
GitHub's own key. That is what this script is for, and it is why no clone
happens here: every input it needs is a read from the API.

Three properties the git version had are kept deliberately.

It replaces rather than merges. A file the generator stopped emitting is
deleted, which is what makes a mirror a view of this tree instead of an
accumulation of every tree it has ever been.

It appends rather than rewriting. `expectedHeadOid` makes the write conditional
on the branch not having moved, so two runs cannot interleave, and there is no
force path at all -- a consumer pins `rev:`, and replacing the history strands
every pin that is not a tag.

It refuses to advance past a version tag it cannot move. A ruleset freezes
`v*.*.*` on each mirror, so a tag already there names one tree permanently. A
release arriving at such a version means the generator changed under a
published number, and the remedy is a version rather than a force. A person
saying so with `--allow-past-tag` is a different case: a readme fix reaches the
page somebody reads without spending a version, and what a pinned `rev:`
resolves to does not move either way.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

_API = 'https://api.github.com'
_GRAPHQL = f'{_API}/graphql'

_COMMIT_MUTATION = """
mutation ($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit {
      oid
      signature { isValid }
    }
  }
}
"""


def _request(
    url: str,
    token: str,
    *,
    method: str,
    body: dict[str, Any] | None,
    absent_ok: bool = False,
) -> dict[str, Any]:
    """Call the API and return the decoded body, refusing to fail quietly.

    ``absent_ok`` turns a 404 into an empty mapping rather than an exit, for the
    one question here whose answer is legitimately "no such ref". It is a
    parameter rather than a caller inspecting the error, because reading a
    status code back out of a message is a check that passes until somebody
    rewords the message.
    """
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    request.add_header('Authorization', f'Bearer {token}')
    request.add_header('Accept', 'application/vnd.github+json')
    request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            payload = response.read()
    except urllib.error.HTTPError as error:
        if absent_ok and error.code == 404:  # noqa: PLR2004
            return {}
        detail = error.read().decode(errors='replace')
        message = f'{method} {url} failed with {error.code}: {detail}'
        raise SystemExit(message) from error
    # `json.loads` is typed as returning Any, and every caller here reads a
    # documented API shape rather than an arbitrary document, so the cast
    # states what the endpoint promises instead of spreading Any outward.
    return cast('dict[str, Any]', json.loads(payload)) if payload else {}


def _graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Run one GraphQL call, treating a 200 carrying errors as a failure.

    GraphQL reports a refused mutation in the body rather than in the status
    line, so the transport check above sees nothing wrong. Without this, a
    rejected write -- a ruleset, a stale head, a revoked token -- would read as
    a successful run that silently committed nothing.
    """
    body = _request(
        _GRAPHQL, token, method='POST', body={'query': query, 'variables': variables}
    )
    if body.get('errors'):
        message = f'GraphQL refused the call: {json.dumps(body["errors"])}'
        raise SystemExit(message)
    return cast('dict[str, Any]', body['data'])


def blob_id(content: bytes) -> str:
    """Return the git object id for ``content``, to compare against a tree.

    Computed rather than fetched. The tree listing gives a blob id per path for
    free, so hashing the generated file locally answers "did this change?"
    without downloading anything the mirror already holds.
    """
    header = f'blob {len(content)}\0'.encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


def remote_state(
    repository: str, branch: str, token: str
) -> tuple[str, dict[str, str]]:
    """Return the branch head and every blob it holds, as ``path -> blob id``."""
    ref = _request(
        f'{_API}/repos/{repository}/git/ref/heads/{branch}',
        token,
        method='GET',
        body=None,
    )
    head = ref['object']['sha']
    tree = _request(
        f'{_API}/repos/{repository}/git/trees/{head}?recursive=1',
        token,
        method='GET',
        body=None,
    )
    # A truncated listing would under-report what the mirror holds, and the
    # deletions below are computed from exactly this set: a path missing from a
    # short read would look like a file already gone rather than one to remove.
    # These trees are a handful of files, so this is a guard rather than a case.
    if tree.get('truncated'):
        message = f'{repository}: the tree listing was truncated'
        raise SystemExit(message)
    blobs = {
        entry['path']: entry['sha'] for entry in tree['tree'] if entry['type'] == 'blob'
    }
    return head, blobs


def local_state(tree: Path) -> dict[str, bytes]:
    """Return every file under ``tree``, as ``path relative to it -> bytes``."""
    return {
        str(path.relative_to(tree)): path.read_bytes()
        for path in sorted(tree.rglob('*'))
        if path.is_file()
    }


def tag_exists(repository: str, tag: str, token: str) -> bool:
    """Report whether ``tag`` is already on the mirror."""
    return (
        _request(
            f'{_API}/repos/{repository}/git/ref/tags/{tag}',
            token,
            method='GET',
            body=None,
            absent_ok=True,
        )
        != {}
    )


def main(argv: list[str] | None = None) -> int:
    """Land one mirror, and tag it when the tag is not already spoken for."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, help='owner/name of the mirror')
    parser.add_argument('--tree', required=True, type=Path, help='generated tree')
    parser.add_argument('--branch', default='main')
    parser.add_argument('--tag', required=True, help='version tag to create')
    parser.add_argument('--headline', required=True, help='commit subject')
    parser.add_argument('--body', default='', help='commit body')
    parser.add_argument(
        '--allow-past-tag',
        action='store_true',
        help='let the branch move even though its version tag is already frozen',
    )
    arguments = parser.parse_args(argv)

    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        message = 'GITHUB_TOKEN is unset'
        raise SystemExit(message)

    repository = arguments.repository
    head, remote = remote_state(repository, arguments.branch, token)
    local = local_state(arguments.tree)

    additions = [
        {'path': path, 'contents': base64.b64encode(content).decode()}
        for path, content in local.items()
        if remote.get(path) != blob_id(content)
    ]
    deletions = [{'path': path} for path in sorted(remote) if path not in local]
    frozen = tag_exists(repository, arguments.tag, token)

    if not additions and not deletions:
        print(f'::notice::{repository} is already what the generator produces')
    elif frozen and not arguments.allow_past_tag:
        print(
            f'::error::{repository} already carries {arguments.tag}; bump the version'
        )
        return 1
    else:
        data = _graphql(
            token,
            _COMMIT_MUTATION,
            {
                'input': {
                    'branch': {
                        'repositoryNameWithOwner': repository,
                        'branchName': arguments.branch,
                    },
                    'message': {
                        'headline': arguments.headline,
                        'body': arguments.body,
                    },
                    'expectedHeadOid': head,
                    'fileChanges': {'additions': additions, 'deletions': deletions},
                }
            },
        )
        commit = data['createCommitOnBranch']['commit']
        head = commit['oid']
        # Stated rather than assumed. Signing is the whole reason this script
        # replaced a git push, so a run that landed an unsigned commit has to
        # say so rather than report the same success as one that did not.
        if not (commit.get('signature') or {}).get('isValid'):
            print(f'::warning::{repository} {head[:7]} came back unsigned')
        print(
            f'::notice::{repository} committed {head[:7]}'
            f' ({len(additions)} written, {len(deletions)} deleted)'
        )

    if frozen:
        print(
            f'::notice::{repository} already carries {arguments.tag}, which cannot move'
        )
    else:
        _request(
            f'{_API}/repos/{repository}/git/refs',
            token,
            method='POST',
            body={'ref': f'refs/tags/{arguments.tag}', 'sha': head},
        )
        print(f'::notice::{repository} tagged {arguments.tag} at {head[:7]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
