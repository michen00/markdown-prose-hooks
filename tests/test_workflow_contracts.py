"""Assert the wiring of every workflow this repository serves.

`test_corpus.py` specifies the transform and `test_cli_corpus.py` specifies the
program. Neither reads `.github/workflows`, so the properties that make the
fork-safe pair safe were carried by comments and by SECURITY.md and checked by
review alone. A workflow that cannot be run from here can still have its wiring
asserted, and that is what this file does.

Two kinds of assertion live here. The repository-wide ones hold for every
workflow and are parameterized over the directory, so a workflow added later is
covered when it arrives rather than when somebody remembers. The per-workflow
contracts name one file each and pin the trigger and the permissions that
file's own header argues for.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / '.github' / 'workflows'

# Both suffixes, so a `.yaml` added later is covered rather than silently out
# of scope. Actions reads either.
_WORKFLOW_NAMES = tuple(
    sorted(
        path.name
        for pattern in ('*.yml', '*.yaml')
        for path in _WORKFLOWS.glob(pattern)
    )
)


class _Loader(yaml.SafeLoader):
    """A loader whose booleans are YAML 1.2's, which leaves ``on:`` a string."""


# PyYAML implements YAML 1.1, which reads `on`, `yes` and their negatives as
# booleans, so under a plain `safe_load` a workflow's trigger arrives under the
# key `True` and a file written with a literal `true:` is indistinguishable
# from one written with `on:`. Actions runs only the second, so the two have to
# stay apart here or a workflow Actions never triggers passes every assertion
# below -- which is the failure this file exists to prevent rather than commit.
# Narrowing the resolver to YAML 1.2's two spellings is what keeps them apart.
_Loader.yaml_implicit_resolvers = {
    character: [
        (tag, pattern) for tag, pattern in resolvers if tag != 'tag:yaml.org,2002:bool'
    ]
    for character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    'tag:yaml.org,2002:bool',
    re.compile('^(?:true|True|TRUE|false|False|FALSE)$'),
    list('tTfF'),
)

# The expression contexts an outside author controls. `github.event` carries a
# pull request's title, body and branch name, and `github.head_ref` is that
# branch name on its own. Interpolated into a `run:` block either is a shell
# injection, because a workflow expression is substituted before the shell
# parses the script. A matrix entry and a step output are not: this repository
# wrote both.
_UNTRUSTED = re.compile(r'github\.(event|head_ref)\b')

# `github['event']` reads the same value as `github.event`, and an expression
# may be written either way. The bracket form is rewritten to the dotted one
# before the pattern above is applied, so one pattern answers for both
# spellings rather than two of them drifting apart. Both quote characters are
# read here, unlike in the literal below: naming an access Actions would
# reject costs a workflow nobody can run, and missing one costs the check.
_BRACKET = re.compile(r"""\[\s*(['"])(?P<name>[^'"]+)\1\s*\]""")

# A quoted string is data rather than a context read: `${{ 'github.event' }}`
# names no context, whatever the letters inside it spell. Single quotes are
# the only delimiter an expression takes, which actionlint reports as "only
# single quotes are available for string delimiter", so a double-quoted run
# of text is not a literal and emptying one could only hide an access. A
# doubled quote inside a literal needs no case of its own: it keeps the
# quote count even, so the pairs this matches tile the literal exactly.
_LITERAL = re.compile(r"'[^']*'")

# An expression runs to its closing braces, and a brace inside a literal is
# not one of them: `${{ '}' && github.event.x }}` is a single expression, and
# a pattern that stops at the first brace reads it as no expression at all and
# scans nothing. The literal alternative below is what carries a brace past
# the terminator. An unterminated literal matches nothing here, which
# actionlint rejects before this suite sees it.
_EXPRESSION = re.compile(r"\$\{\{(?:'[^']*'|[^'}]|\}(?!\}))*\}\}")


def _load(path: Path) -> dict[str, Any]:
    """Return the parsed workflow at ``path``."""
    # `yaml.load` with a loader of our own reads as the unsafe call it is not,
    # so the loader is driven directly -- which is all that function does.
    loader = _Loader(path.read_text(encoding='utf-8'))
    try:
        parsed = loader.get_single_data()
    finally:
        loader.dispose()
    assert isinstance(parsed, dict), f'{path.name} does not parse to a mapping'
    return parsed


def _context_reads(expression: str) -> str:
    """Return ``expression`` with only the contexts it reads left standing.

    Bracket access is spelled with dots first and the quoted strings emptied
    second, because a subscript is itself quoted: emptying first would take
    the `'event'` out of ``github['event']`` and the access away with it.
    """
    dotted = _BRACKET.sub(lambda match: f'.{match["name"]}', expression)
    return _LITERAL.sub("''", dotted)


def _run_scripts(node: object) -> Iterator[str]:
    """Yield every ``run:`` script anywhere in a parsed workflow."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'run' and isinstance(value, str):
                yield value
            yield from _run_scripts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _run_scripts(value)


def test_the_workflow_directory_is_not_empty() -> None:
    """Some workflow was found, so the parameterized tests below run at all."""
    # Without this, a moved directory leaves every test below with no cases and
    # a green result, which reads as a suite that passed.
    assert _WORKFLOW_NAMES, f'no workflows found under {_WORKFLOWS}'


@pytest.mark.parametrize('name', _WORKFLOW_NAMES)
def test_workflow_parses_as_a_mapping(name: str) -> None:
    """Every workflow file is YAML this suite can read."""
    assert _load(_WORKFLOWS / name)


@pytest.mark.parametrize('name', _WORKFLOW_NAMES)
def test_workflow_declares_a_trigger(name: str) -> None:
    """Every workflow states the ``on:`` key that Actions reads as its trigger."""
    assert _load(_WORKFLOWS / name).get('on') is not None, (
        f'{name} declares no `on:`, which is the key Actions reads; a '
        'trigger spelled `true:` parses to a boolean and is not one'
    )


@pytest.mark.parametrize('name', _WORKFLOW_NAMES)
def test_no_untrusted_expression_reaches_a_shell(name: str) -> None:
    """No expression an outside author controls is interpolated into ``run:``."""
    offenders = sorted(
        {
            expression
            for script in _run_scripts(_load(_WORKFLOWS / name))
            for expression in _EXPRESSION.findall(script)
            if _UNTRUSTED.search(_context_reads(expression))
        }
    )
    assert not offenders, (
        f'{name} interpolates {offenders} into a shell script; pass the value '
        'through `env:` and quote the variable, so the shell reads data rather '
        'than a substituted expression'
    )


@dataclass(frozen=True)
class Contract:
    """The wiring one workflow promises, asserted rather than commented."""

    filename: str
    trigger: str
    workflow_permissions: dict[str, str]
    job: str
    job_permissions: dict[str, str] | None
    checks_out: bool

    def __str__(self) -> str:
        """Return the filename, used as the parametrize id."""
        return self.filename


_CONTRACTS = (
    # The read-only half. It runs with what a fork gets anyway, and it does
    # check out the head, because a patch is only useful if it applies to the
    # branch the contributor has.
    Contract(
        filename='unwrap-propose.yml',
        trigger='workflow_call',
        workflow_permissions={'contents': 'read'},
        job='propose',
        job_permissions={'contents': 'read'},
        checks_out=True,
    ),
    # The writable half, and the reason this table exists. SECURITY.md promises
    # a consumer that it checks nothing out, which is the property
    # `pull_request_target` gives up, and `checks_out=False` is that promise
    # made checkable.
    Contract(
        filename='unwrap-comment.yml',
        trigger='workflow_call',
        workflow_permissions={},
        job='comment',
        job_permissions={'actions': 'read', 'pull-requests': 'write'},
        checks_out=False,
    ),
    # The reporting half of the body surface. It reads a body out of the event
    # payload, so it checks nothing out, and it declares no scope of its own:
    # a scope on a called job is a precondition of the run rather than a
    # request, and the check-only mode is documented to need none.
    Contract(
        filename='unwrap-pr-body-check.yml',
        trigger='workflow_call',
        workflow_permissions={},
        job='report',
        job_permissions=None,
        checks_out=False,
    ),
)


@pytest.mark.parametrize('contract', _CONTRACTS, ids=str)
def test_contract_trigger(contract: Contract) -> None:
    """Each contracted workflow declares exactly the trigger it was written for."""
    trigger = _load(_WORKFLOWS / contract.filename).get('on')
    assert isinstance(trigger, dict), f'{contract.filename} lists its triggers'
    assert list(trigger) == [contract.trigger]


@pytest.mark.parametrize('contract', _CONTRACTS, ids=str)
def test_contract_jobs(contract: Contract) -> None:
    """Each contracted workflow runs the one job its contract describes."""
    # The two tests below name a single job apiece. A second job would carry
    # its own permissions and its own steps past both of them, so the set is
    # pinned here rather than left to whoever reads the file next.
    document = _load(_WORKFLOWS / contract.filename)
    assert list(document['jobs']) == [contract.job]


@pytest.mark.parametrize('contract', _CONTRACTS, ids=str)
def test_contract_permissions(contract: Contract) -> None:
    """Each contracted workflow grants exactly the scopes its header argues for."""
    # Equality rather than containment, on both levels. A scope this table does
    # not name is the finding, and a subset check would let one through.
    document = _load(_WORKFLOWS / contract.filename)
    assert document.get('permissions') == contract.workflow_permissions
    job = document['jobs'][contract.job]
    assert job.get('permissions') == contract.job_permissions


@pytest.mark.parametrize('contract', _CONTRACTS, ids=str)
def test_contract_checkout(contract: Contract) -> None:
    """A workflow promising to check nothing out runs no checkout step."""
    job = _load(_WORKFLOWS / contract.filename)['jobs'][contract.job]
    # A job calling a reusable workflow has no steps of its own, so the list
    # below would come out empty and the promise would read as kept while
    # whatever it delegated to checked out whatever it liked.
    assert 'uses' not in job, (
        f'{contract.filename} hands {contract.job} to another workflow, '
        'whose steps this contract cannot see'
    )
    used = [step['uses'] for step in job['steps'] if 'uses' in step]
    checks_out = any(action.startswith('actions/checkout') for action in used)
    assert checks_out is contract.checks_out
