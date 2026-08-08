.DEFAULT_GOAL := help

.PHONY: help develop lint format tidy test coverage check floor build hook-test

# Measures the widest target before printing any of them, rather than padding to a
# constant: a name longer than every other would otherwise push its own description
# out of line with the rest. `%-*s` takes the width from the argument, which POSIX
# requires of awk and the awks on macOS and the runners all implement.
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{n[NR]=$$1;h[NR]=$$2;if(length($$1)>w)w=length($$1)}\
			END{for(i=1;i<=NR;i++)printf "  \033[36m%-*s\033[0m %s\n",w,n[i],h[i]}'

develop: ## Install dependencies and git hooks
	uv sync
	uv run pre-commit install --install-hooks
	uv run pre-commit install --hook-type commit-msg
	@git config blame.ignoreRevsFile .git-blame-ignore-revs

lint: ## Lint with ruff
	uv run ruff check .

format: ## Format with ruff
	uv run ruff format .

tidy: ## Auto-fix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .

test: ## Run the test suite
	uv run python -m pytest

coverage: ## Run the suite with a coverage report
	uv run python -m pytest --cov

# The floor in pyproject.toml is a promise made to every repository that installs
# this hook, and the only way to keep it honest is to run the suite there. The
# development interpreter is newer and would not notice the day something 3.11+
# lands in the tool.
floor: ## Run the suite on the oldest supported Python
	uv run --python 3.10 --with-editable . --with pytest python -m pytest -q

build: ## Build the wheel and sdist
	uv build

# Exercises the hook the way a consumer gets it — resolved from this checkout by
# the pre-commit framework — rather than through the console script alone, which
# would not catch a broken `.pre-commit-hooks.yaml`.
#
# `--files` and not `--all-files`, for the reason CI's `hook` job carries: try-repo
# builds its config from `.pre-commit-hooks.yaml`, so the `exclude:` in
# `.pre-commit-config.yaml` is never in scope. This target runs the *writing* hook,
# so the omission did not merely go red the way CI did — it rewrote every corpus
# fixture into its own expected output, turning the conformance suite green against
# nothing, on a developer's machine, with no diff in CI to show for it.
hook-test: ## Run the hook against this repo through pre-commit
	uv run pre-commit try-repo . unwrap-markdown-prose --all-files

check: tidy test floor ## Tidy, test, and verify the version floor
