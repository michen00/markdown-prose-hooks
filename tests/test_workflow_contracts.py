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

# YAML 1.1 reads a bare `on` as a boolean and PyYAML implements YAML 1.1, so a
# workflow's trigger arrives under the key `True`. Left to a plain `.get('on')`
# the lookup returns None, and every assertion built on it passes while testing
# nothing -- which is the failure this file exists to prevent rather than
# commit.
_TRIGGER_KEYS: tuple[str | bool, ...] = (True, 'on')

# The expression contexts an outside author controls. `github.event` carries a
# pull request's title, body and branch name, and `github.head_ref` is that
# branch name on its own. Interpolated into a `run:` block either is a shell
# injection, because a workflow expression is substituted before the shell
# parses the script. A matrix entry and a step output are not: this repository
# wrote both.
_UNTRUSTED = re.compile(r'github\.(event|head_ref)\b')

_EXPRESSION = re.compile(r'\$\{\{[^}]*\}\}')


def _load(path: Path) -> dict[str | bool, Any]:
    """Return the parsed workflow at ``path``."""
    parsed = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(parsed, dict), f'{path.name} does not parse to a mapping'
    return parsed


def _trigger(document: dict[str | bool, Any]) -> object:
    """Return a workflow's ``on:`` value, under whichever key YAML gave it."""
    for key in _TRIGGER_KEYS:
        if key in document:
            return document[key]
    return None


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
    """Every workflow states an ``on:``, found under the key YAML parsed it to."""
    document = _load(_WORKFLOWS / name)
    assert _trigger(document) is not None, (
        f'{name} declares no trigger this suite can find; if PyYAML stopped '
        'folding `on` to a boolean, _TRIGGER_KEYS is what to fix'
    )


@pytest.mark.parametrize('name', _WORKFLOW_NAMES)
def test_no_untrusted_expression_reaches_a_shell(name: str) -> None:
    """No expression an outside author controls is interpolated into ``run:``."""
    offenders = sorted(
        {
            expression
            for script in _run_scripts(_load(_WORKFLOWS / name))
            for expression in _EXPRESSION.findall(script)
            if _UNTRUSTED.search(expression)
        }
    )
    assert not offenders, (
        f'{name} interpolates {offenders} into a shell script; pass the value '
        'through `env:` and quote the variable, so the shell reads data rather '
        'than a substituted expression'
    )
