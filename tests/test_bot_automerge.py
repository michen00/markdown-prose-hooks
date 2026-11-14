"""Run bot auto-merge's provenance step the way Actions runs it.

The step decides whether every commit on a bot's pull request came from GitHub, every
commit that is not a merge from the bot, every merge either from nothing but a clean
merge of two parents or from a repository admin, and every commit that anyone but the
bot or an admin pushed from nothing but a clean merge of two parents. Nothing below it
arms auto-merge unless it says so, and arming names the head it vouched for. GitHub
signs a merge a person resolves in its web conflict editor as well, which can carry any
content, so these cases build real repositories and let the step's own `git fetch` and
`git merge-tree` decide: an origin holding the branch at `refs/pull/7/head`, and a clone
of its `main` for the step to run in, as the checkout before it leaves the runner. The
`gh` the step calls reports the branch's tip as the head, and lists the branch's real
commits in the shape its `--jq` filter produces: the origin, the kind, the author's
login, the SHA and the parent SHAs. It lists the push history each test gives, newest
first, answers the permission lookup from `_ADMIN`, `_FLAKY` and write, and records
each lookup.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# The step runs on ubuntu-latest. On a Windows runner `bash` resolves to WSL's
# launcher, which tests the launcher rather than the step.
pytestmark = pytest.mark.skipif(
    sys.platform == 'win32', reason='bash on Windows runners is the WSL launcher'
)

_WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/bot-automerge.yml'

# Who the fake says each merge author is: `_ADMIN` is an admin, `_FLAKY`'s lookup
# fails, and anyone else has write. `<none>` stands for an author GitHub cannot name;
# the fixtures write it as `no-account`, since git strips `<` and `>` from a name.
_ADMIN = 'michen00'
_NON_ADMIN = 'contributor'
_FLAKY = 'flaky-lookup'

# An App's login, as the push history records a catch-up it pushed. The fake gives it
# write.
_APP = 'catch-up-app[bot]'

_ZERO = '0' * 40

# Any call besides the five reads exits 2, so a test cannot pass by way of a
# request the fake was never meant to answer.
_GH = f"""\
#!/usr/bin/env bash
case "$*" in
  *" repos/owner/repository/pulls/7 --jq .head.sha") printf '%s\\n' "$FAKE_HEAD" ;;
  *" repos/owner/repository/pulls/7 --jq .commits") printf '%s\\n' "$FAKE_COUNT" ;;
  *" repos/owner/repository/pulls/7/commits "*) printf '%s\\n' "$FAKE_ROWS" ;;
  *" repos/owner/repository/activity "*" ref=refs/heads/bump "*)
    printf '%s' "$FAKE_PUSHES" ;;
  *" repos/owner/repository/collaborators/"*"/permission "*)
    login=${{2#*/collaborators/}}; login=${{login%/permission}}
    echo "$login" >>"$LOOKUP_LOG"
    case $login in
      {_ADMIN}) echo admin ;;
      {_FLAKY}) echo "gh: Server Error (HTTP 502)" >&2; exit 1 ;;
      *) echo write ;;
    esac ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 2 ;;
esac
"""

# Records how long the step asked to wait, and returns at once.
_SLEEP = '#!/usr/bin/env bash\necho "$1" >>"$SLEEP_LOG"\n'

_HELD = "is neither a clean merge of two parents nor an admin's; holding."


def _isolated_env() -> dict[str, str]:
    """Return the environment without GIT_* variables or user and system git config.

    A hook runner's GIT_* variables would point git at this repository instead.
    """
    env = {
        key: value for key, value in os.environ.items() if not key.startswith('GIT_')
    }
    return {**env, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


def _git(repo: Path, *args: str, author: str = 'dependabot[bot]') -> str:
    """Run git in ``repo`` as ``author``, with GitHub as the committer."""
    done = subprocess.run(  # noqa: S603
        ['git', *args],  # noqa: S607
        cwd=repo,
        env={
            **_isolated_env(),
            'GIT_AUTHOR_NAME': author,
            'GIT_AUTHOR_EMAIL': f'{author}@example.invalid',
            'GIT_COMMITTER_NAME': 'GitHub',
            'GIT_COMMITTER_EMAIL': 'noreply@github.com',
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _write(repo: Path, name: str, text: str) -> None:
    """Write one line to a file in ``repo``."""
    (repo / name).write_text(f'{text}\n', encoding='utf-8')


def _dependabot_branch(tmp_path: Path, bot: str = 'dependabot[bot]') -> Path:
    """Return a repository on a Dependabot-style branch that main has moved on from.

    ``bot`` authors the branch's commit. The branch changes a.txt and main changes
    b.txt, so merging main is clean.
    """
    repo = tmp_path / 'dev'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    for name in ('a', 'b', 'c'):
        _write(repo, f'{name}.txt', name)
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'chore: start', author=_ADMIN)
    _git(repo, 'switch', '-qc', 'bump')
    _write(repo, 'a.txt', 'a, bumped')
    _git(repo, 'commit', '-qam', 'build: bump a', author=bot)
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change b', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    return repo


def _tip(repo: Path) -> str:
    """Return the branch's tip."""
    return _git(repo, 'rev-parse', 'HEAD')


def _created(after: str, pusher: str = 'dependabot[bot]') -> str:
    """Return the push-history record of ``pusher`` creating the branch at ``after``."""
    return f'branch_creation|{pusher}|{_ZERO}|{after}'


def _pushed(pusher: str, before: str, after: str, change: str = 'push') -> str:
    """Return the push-history record of ``pusher`` moving the branch to ``after``."""
    return f'{change}|{pusher}|{before}|{after}'


def _edited_merge(repo: Path, author: str) -> None:
    """Merge main cleanly as ``author``, then amend an extra edit into the merge."""
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=author)
    _write(repo, 'c.txt', f'c, edited in the merge by {author}')
    _git(repo, 'commit', '-q', '--amend', '--no-edit', '--all', author=author)


def _resolved_merge(repo: Path, author: str) -> None:
    """Merge a conflicting main as ``author``, resolved by hand with an extra edit."""
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'a.txt', 'a, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change a', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, 'merge', '-q', '--no-edit', 'main', author=author)
    _write(repo, 'a.txt', 'whatever the resolver typed')
    _write(repo, 'c.txt', 'and an edit elsewhere')
    _git(repo, 'add', 'a.txt', 'c.txt')
    _git(repo, 'commit', '-q', '--no-edit', author=author)


def _run(  # noqa: PLR0913 -- one keyword per answer the fake gives
    tmp_path: Path,
    repo: Path,
    count: str | None = None,
    *,
    head: str | None = None,
    event_head: str | None = None,
    pushes: list[str] | None = None,
    author: str = 'dependabot[bot]',
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    """Run the provenance step on ``repo``'s branch as pull request 7, by ``author``.

    The fake reports the commit count as ``count`` when one is given, and as the
    number of rows otherwise, and the head as ``head`` when one is given, and as the
    branch's tip otherwise. The event brings ``event_head``, by default the head the
    fake reports. The fake lists ``pushes`` as the branch's push history, newest first,
    by default Dependabot creating the branch at that head. Returns the finished step,
    the outputs it wrote to ``GITHUB_OUTPUT``, and the logins it looked up.
    """
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding='utf-8'))
    (step,) = [
        step
        for step in workflow['jobs']['bot-automerge']['steps']
        if step.get('id') == 'provenance'
    ]
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'clone', '-q', '--mirror', str(repo), str(origin))
    _git(origin, 'update-ref', 'refs/pull/7/head', _tip(repo))
    # GitHub serves a commit by its SHA after a force push has left it unreachable.
    _git(origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    reported = _tip(repo) if head is None else head
    runner = tmp_path / 'runner'
    _git(tmp_path, 'clone', '-q', '--branch', 'main', str(origin), str(runner))
    rows = []
    for sha in _git(repo, 'rev-list', '--reverse', 'main..HEAD').split():
        _, *parents = _git(repo, 'rev-list', '--parents', '-n1', sha).split()
        kind = 'merge' if len(parents) >= 2 else 'plain'
        login = _git(repo, 'log', '-1', '--format=%an', sha)
        login = '<none>' if login == 'no-account' else login
        rows.append(f'github|{kind}|{login}|{sha}|{" ".join(parents)}')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, text in (('gh', _GH), ('sleep', _SLEEP)):
        (bin_dir / name).write_text(text, encoding='utf-8')
        (bin_dir / name).chmod(0o755)
    script = tmp_path / 'step.sh'
    script.write_text(str(step['run']), encoding='utf-8')
    output = tmp_path / 'output'
    output.write_text('', encoding='utf-8')
    lookups = tmp_path / 'lookups'
    lookups.write_text('', encoding='utf-8')
    # The script is this tree's own workflow text, run the way a step with no
    # `shell:` key is, with bash coming off PATH as it does on the runner.
    done = subprocess.run(  # noqa: S603
        ['bash', '-e', str(script)],  # noqa: S607
        cwd=runner,
        capture_output=True,
        text=True,
        check=False,
        env={
            **_isolated_env(),
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GH_TOKEN': 'unused',
            'GH_REPO': 'owner/repository',
            'PR_NUMBER': '7',
            'AUTHOR': author,
            'EVENT_HEAD': reported if event_head is None else event_head,
            'HEAD_REF': 'bump',
            'FAKE_HEAD': reported,
            'FAKE_COUNT': str(len(rows)) if count is None else count,
            'FAKE_ROWS': '\n'.join(rows),
            'FAKE_PUSHES': ''.join(
                f'{push}\n' for push in pushes or [_created(reported)]
            ),
            'LOOKUP_LOG': str(lookups),
            'SLEEP_LOG': str(tmp_path / 'sleeps'),
        },
    )
    outputs = {
        key: value
        for key, _, value in (
            line.partition('=')
            for line in output.read_text(encoding='utf-8').splitlines()
        )
    }
    return done, outputs, lookups.read_text(encoding='utf-8').split()


def _trusted(tmp_path: Path, repo: Path) -> tuple[str, str, list[str]]:
    """Run the provenance step, which must succeed, on ``repo``'s branch.

    Returns what it set ``trusted`` to, its log, and the logins it looked up.
    """
    done, outputs, looked_up = _run(tmp_path, repo)
    assert done.returncode == 0, done.stderr
    return outputs['trusted'], done.stdout, looked_up


@pytest.mark.parametrize(
    'merger',
    ['github-actions[bot]', _NON_ADMIN, _ADMIN],
    ids=['catch-up', 'update-branch-by-a-non-admin', 'update-branch-by-an-admin'],
)
def test_a_clean_merge_passes(tmp_path: Path, merger: str) -> None:
    """A clean merge of two branches passes, whoever authored it, with no lookup.

    pr-catchup.yml merges as github-actions[bot] or as the App, and Update branch as
    the person who clicked it. GitHub makes either only when the merge is clean.
    """
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=merger)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == []


def test_an_admins_resolved_merge_with_extra_edits_passes(tmp_path: Path) -> None:
    """An admin's merge passes even when it resolves a conflict and edits more."""
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _ADMIN)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


def test_an_admin_is_looked_up_once_for_several_merges(tmp_path: Path) -> None:
    """Two edited merges by one admin both pass on a single permission lookup."""
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, _ADMIN)
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main again')
    _git(repo, 'commit', '-qam', 'feat: change b again', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    _edited_merge(repo, _ADMIN)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


@pytest.mark.parametrize(
    ('merger', 'lookups'),
    [(_NON_ADMIN, [_NON_ADMIN]), (_FLAKY, [_FLAKY]), ('no-account', [])],
    ids=['non-admin', 'failed-lookup', 'no-account'],
)
def test_an_edited_merge_by_anyone_but_an_admin_holds(
    tmp_path: Path, merger: str, lookups: list[str]
) -> None:
    """An extra edit in a merge holds it unless an admin made it.

    A failed lookup, or an author GitHub cannot name, counts as not an admin, and the
    latter is never looked up.
    """
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, merger)
    trusted, log, looked_up = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log
    assert looked_up == lookups


def test_a_conflict_a_non_admin_resolved_by_hand_holds(tmp_path: Path) -> None:
    """A merge whose conflict a non-admin resolved holds, whatever they typed."""
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _NON_ADMIN)
    trusted, log, _ = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


def test_an_octopus_merge_by_a_non_admin_holds(tmp_path: Path) -> None:
    """A clean merge of three branches has three parents, so it is not mechanical."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'switch', '-qc', 'side', 'main~1')
    _write(repo, 'c.txt', 'c, changed on side')
    _git(repo, 'commit', '-qam', 'build: change c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', 'side', author=_NON_ADMIN)
    trusted, log, _ = _trusted(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


@pytest.mark.parametrize('count', ['null', '3abc', ''])
def test_a_commit_count_that_is_not_an_integer_holds(
    tmp_path: Path, count: str
) -> None:
    """A count that is not an integer fails the step, leaving ``trusted`` unset.

    Unguarded, the `-gt` and `-ne` tests error inside `if`, read as false, and the step
    falls through to trusting the pull request.
    """
    repo = _dependabot_branch(tmp_path)
    done, outputs, _ = _run(tmp_path, repo, count=count)
    assert done.returncode != 0
    assert outputs == {}
    assert "could not read the PR's commit count; holding." in done.stdout


def test_a_trusted_verdict_names_the_head_it_inspected(tmp_path: Path) -> None:
    """A trusted run outputs its head commit, which approving and arming then name."""
    repo = _dependabot_branch(tmp_path)
    done, outputs, _ = _run(tmp_path, repo)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'true', 'head': _tip(repo)}


def test_a_head_that_moved_during_the_check_holds(tmp_path: Path) -> None:
    """A head the API reports that is not the commit inspected holds, naming no head."""
    repo = _dependabot_branch(tmp_path)
    moved = _git(repo, 'rev-parse', 'main')
    done, outputs, _ = _run(tmp_path, repo, head=moved, event_head=moved)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert 'the head moved while it was being inspected; holding.' in done.stdout


def test_a_head_this_event_did_not_bring_holds(tmp_path: Path) -> None:
    """A run vouches only for its own event's head, never for a later push's."""
    repo = _dependabot_branch(tmp_path)
    done, outputs, _ = _run(tmp_path, repo, event_head=_git(repo, 'rev-parse', 'main'))
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert 'the head is no longer the one this event brought; holding.' in done.stdout


@pytest.mark.parametrize('pusher', [_NON_ADMIN, _APP])
def test_a_plain_commit_pushed_by_anyone_but_the_author_or_an_admin_holds(
    tmp_path: Path, pusher: str
) -> None:
    """A commit authored as the bot passes the per-commit rules; its pusher does not.

    GitHub signs a commit an App or a token creates through its API, with any author,
    so only the push, which GitHub attributes itself, shows who added it.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, changed by someone posing as Dependabot')
    _git(repo, 'commit', '-qam', 'build: bump c')
    pushes = [_pushed(pusher, created, _tip(repo)), _created(created)]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert 'which is not a clean merge of two parents; holding.' in done.stdout


@pytest.mark.parametrize('bot', ['dependabot[bot]', 'pre-commit-ci[bot]'])
def test_a_plain_commit_the_author_pushed_passes(tmp_path: Path, bot: str) -> None:
    """The pull request's author may push plain commits, whichever bot opened it."""
    repo = _dependabot_branch(tmp_path, bot=bot)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, bumped')
    _git(repo, 'commit', '-qam', 'build: bump c', author=bot)
    pushes = [_pushed(bot, created, _tip(repo)), _created(created, pusher=bot)]
    done, outputs, looked_up = _run(tmp_path, repo, pushes=pushes, author=bot)
    assert done.returncode == 0, done.stderr
    assert outputs['trusted'] == 'true', done.stdout
    assert looked_up == []


def test_a_clean_merge_pushed_by_an_app_passes(tmp_path: Path) -> None:
    """A catch-up push is a clean merge of main, so an App pushing one passes.

    Main's own commits come in with the merge; they are not the pusher's, so only the
    merge is held to the rule.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo)), _created(created)]
    done, outputs, looked_up = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs['trusted'] == 'true', done.stdout
    assert looked_up == [_APP]


def test_a_plain_commit_hidden_behind_a_clean_merge_holds(tmp_path: Path) -> None:
    """A plain commit brought in through a merge's second parent is still checked."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'switch', '-qc', 'smuggled', 'main')
    _write(repo, 'c.txt', 'c, smuggled in')
    _git(repo, 'commit', '-qam', 'build: bump c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'smuggled', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo)), _created(created)]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert 'which is not a clean merge of two parents; holding.' in done.stdout


def test_a_held_push_stays_held_after_a_clean_push(tmp_path: Path) -> None:
    """A clean catch-up push does not vouch for a plain commit an earlier push added."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, changed by someone posing as Dependabot')
    _git(repo, 'commit', '-qam', 'build: bump c')
    smuggled = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [
        _pushed(_APP, smuggled, _tip(repo)),
        _pushed(_APP, created, smuggled),
        _created(created),
    ]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert f'{_APP} pushed {smuggled}, which is not a clean merge' in done.stdout


@pytest.mark.parametrize(
    ('pusher', 'trusted'), [(_NON_ADMIN, 'false'), (_ADMIN, 'true')]
)
def test_a_merge_authored_as_an_admin_passes_only_when_an_admin_pushed_it(
    tmp_path: Path, pusher: str, trusted: str
) -> None:
    """An author login comes from an email, so the pusher decides a resolved merge."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _resolved_merge(repo, _ADMIN)
    pushes = [_pushed(pusher, created, _tip(repo)), _created(created)]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs['trusted'] == trusted, done.stdout


def test_a_change_other_than_a_push_holds(tmp_path: Path) -> None:
    """Only a push or a branch creation can be checked commit by commit."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo), change='pr_merge'), _created(created)]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert f'{_APP} changed the branch by pr_merge; holding.' in done.stdout


def test_only_pushes_since_the_branch_was_last_created_count(tmp_path: Path) -> None:
    """Pushes to an earlier branch of the same name are never read.

    Their commits are made up here, so reading them would fail the step.
    """
    repo = _dependabot_branch(tmp_path)
    pushes = [
        _created(_tip(repo)),
        _pushed(_NON_ADMIN, 'e' * 40, 'f' * 40),
        _created('e' * 40),
    ]
    done, outputs, looked_up = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs['trusted'] == 'true', done.stdout
    assert looked_up == []


def test_a_push_history_that_does_not_reach_the_head_holds(tmp_path: Path) -> None:
    """A history whose newest push is not the head is read again, then holds."""
    repo = _dependabot_branch(tmp_path)
    pushes = [_created(_git(repo, 'rev-parse', 'main'))]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert "the branch's push history does not reach its head; holding." in done.stdout
    assert (tmp_path / 'sleeps').read_text(encoding='utf-8').split() == ['5', '5']


def test_a_push_history_that_does_not_reach_the_creation_holds(
    tmp_path: Path,
) -> None:
    """A history with no branch creation may be missing the pushes that matter."""
    repo = _dependabot_branch(tmp_path)
    pushes = [_pushed('dependabot[bot]', 'e' * 40, _tip(repo))]
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert "the branch's push history does not reach its creation;" in done.stdout


def _rewritten_branch(tmp_path: Path, pusher: str) -> tuple[Path, list[str]]:
    """Return a Dependabot branch ``pusher`` rewrote after a push, and its history."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, before the rewrite')
    _git(repo, 'commit', '-qam', 'build: bump c')
    replaced = _tip(repo)
    # Kept by a ref, as GitHub keeps a commit a force push replaced.
    _git(repo, 'update-ref', 'refs/keep/replaced', replaced)
    _git(repo, 'reset', '-q', '--hard', 'HEAD~1')
    _write(repo, 'c.txt', 'c, after the rewrite')
    _git(repo, 'commit', '-qam', 'build: bump c again')
    return repo, [
        _pushed(pusher, replaced, _tip(repo), change='force_push'),
        _pushed('dependabot[bot]', created, replaced),
        _created(created),
    ]


def test_a_rewrite_pushed_by_anyone_but_the_author_or_an_admin_holds(
    tmp_path: Path,
) -> None:
    """A force push by such a pusher holds when it adds a plain commit."""
    repo, pushes = _rewritten_branch(tmp_path, _NON_ADMIN)
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs == {'trusted': 'false'}
    assert (
        f'{_NON_ADMIN} pushed {_tip(repo)}, which is not a clean merge' in done.stdout
    )


@pytest.mark.parametrize('pusher', ['dependabot[bot]', _ADMIN])
def test_a_rewrite_pushed_by_the_author_or_an_admin_passes(
    tmp_path: Path, pusher: str
) -> None:
    """Dependabot rebases its own branches, so its force pushes pass, as admins' do."""
    repo, pushes = _rewritten_branch(tmp_path, pusher)
    done, outputs, _ = _run(tmp_path, repo, pushes=pushes)
    assert done.returncode == 0, done.stderr
    assert outputs['trusted'] == 'true', done.stdout


def test_approving_and_arming_name_the_verified_head() -> None:
    """The approval names the commit the provenance step inspected, and so does arming.

    GitHub otherwise approves and arms whatever the head is when the request lands.
    """
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding='utf-8'))
    (arm,) = [
        step
        for step in workflow['jobs']['bot-automerge']['steps']
        if step.get('name') == 'Re-check the kill switch, then approve and arm'
    ]
    script = ' '.join(arm['run'].replace('\\\n', ' ').split())
    assert arm['env']['VERIFIED_HEAD'] == '${{ steps.provenance.outputs.head }}'
    assert 'gh pr review' not in script
    assert (
        'gh api -X POST "repos/${GH_REPO}/pulls/${PR_NUMBER}/reviews" '
        '-f event=APPROVE -f commit_id="$VERIFIED_HEAD"'
    ) in script
    assert (
        'gh pr merge --auto --squash --match-head-commit "$VERIFIED_HEAD" "$PR_NUMBER"'
    ) in script
