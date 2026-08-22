#!/usr/bin/env python3
"""Check that each mirror is still the repository its version tags were recorded on.

What a consumer pins is a tag on a mirror, and `pre-commit` resolves it by
cloning the repository and checking that ref out. A ruleset freezes `v*.*.*` on
each mirror against update and deletion with no bypass, so for as long as the
repository exists a version tag names one tree permanently.

That guarantee is a property of a repository that exists. Deleting one takes its
rulesets with it, and a new repository under the same name is free to issue the
same tag names against a different tree, which a pin then resolves without
complaint. Nothing else here would notice: `make mirror-diff` reads the default
branch rather than a tag, and no job reads the live mirrors at all.

The numeric repository id is what closes that. GitHub keeps it across a rename
and across a transfer, and mints a new one only when a repository is created, so
it is the one value that moves in the case this guards and in no other.

It is deliberately narrow. A mirror whose default branch stopped matching the
generator is a different failure, and `mirror-diff` is what answers it -- by
hand, because that comparison disagrees by design between a change to a template
and the release that ships it, so a scheduled version of it would spend ordinary
working time red and be read as noise.

It runs on every push rather than on a schedule, for the reason smoke.yml
records about its own cron: GitHub disables a schedule after 60 days without
repository activity, so a scheduled canary can stop reporting without saying so.
"""

import json
import os
import sys
import urllib.error
import urllib.request

_API = 'https://api.github.com'

# Read with `gh api repos/<owner>/<name> -q .id` on 2026-08-22. A mismatch is not
# a value to update: it says the repository serving that name is not the one
# these tags were published from.
_EXPECTED = {
    'michen00/markdown-prose-hooks-py': 1341506472,
    'michen00/markdown-prose-hooks-rs': 1341507274,
}


def repository_id(repository: str) -> int | None:
    """Report the id the API gives for ``repository``, or None if there is none."""
    request = urllib.request.Request(
        f'{_API}/repos/{repository}',
        headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    # Public metadata needs no credential, but an unauthenticated read shares a
    # per-address hourly limit with every other job on the runner's network.
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        request.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(request) as response:
            return int(json.load(response)['id'])
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def main() -> int:
    """Compare every mirror against the id recorded for it."""
    status = 0
    for repository, expected in _EXPECTED.items():
        found = repository_id(repository)
        if found == expected:
            print(f'::notice::{repository} is still repository {expected}')
            continue
        status = 1
        if found is None:
            print(
                f'::error::{repository} does not resolve;'
                f' repository {expected} served its tags'
            )
        else:
            print(
                f'::error::{repository} is repository {found}, not the'
                f' {expected} its tags were published from'
            )
    return status


if __name__ == '__main__':
    sys.exit(main())
