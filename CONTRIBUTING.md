# Contributing

## Setup

```bash
make develop
```

That installs dependencies with [uv](https://docs.astral.sh/uv/) and wires the git hooks, including the commit-message gate.

## The loop

```bash
make check
```

`check` tidies, runs the suite, and re-runs it on the oldest supported interpreter. Individual targets are listed by `make help`.

## What this project optimizes for

Declining to act. A formatter that unwraps a paragraph it should have left alone destroys information the author put there on purpose, and the damage is silent — a passing run and a clean report. Every structural guard exists because joining across it lost something. New behavior is welcome; new joining is expensive, and the burden is on the change to show what it will not eat.

Practice test-driven development for real logic: write the failing test, watch it fail, then implement. The suite is the specification of the conservative boundary, so a change to what gets joined is a change to the tests first.

## The version floor

`pyproject.toml` declares `requires-python = ">=3.10"`, and that is a promise to every repository that installs this hook rather than a preference. The development interpreter is newer, so it will not notice the day a 3.11-only construct lands. `make floor` runs the whole suite on 3.10 and CI runs the matrix; treat a failure there as a bug in the change, not in the floor.

The one place this has already bitten: `Path.read_text(newline=...)` exists only on 3.13, and the tool spells it `Path.open(...)` instead. Line-ending handling cannot be dropped — this tool decides what a line break is, and normalizing `\r\n` to `\n` on read would rewrite every line of a CRLF file on the first run that touched it.

## Both entry points

The hook and the action share the CLI and nothing else. A green test suite says nothing about whether `.pre-commit-hooks.yaml` resolves or the composite action runs, so CI exercises all three paths. Run the framework path locally with `make hook-test`.

## Commits and pull requests

Conventional Commit messages; imperative, lowercase subjects of 50 characters or fewer. Commit atomically — one concern per commit. Pull request titles become the squash subject, so write them the same way.
