.DEFAULT_GOAL := help

.PHONY: help develop lint format tidy test coverage check floor build hook-test \
	rust-lint rust-test rust-tidy parity

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
# `--all-files` is safe here only because the tool reads `.unwrapignore` itself.
# try-repo builds its config from `.pre-commit-hooks.yaml`, so the `exclude:` in
# `.pre-commit-config.yaml` is never in scope, and this target runs the *writing*
# hook: before the ignore rules existed, the omission did not merely go red the
# way CI did — it rewrote every corpus fixture into its own expected output,
# turning the conformance suite green against nothing, on a developer's machine,
# with no diff in CI to show for it.
hook-test: ## Run the hook against this repo through pre-commit
	uv run pre-commit try-repo . unwrap-markdown-prose-py --all-files

rust-lint: ## Lint the Rust with fmt and clippy
	cargo fmt --check
	cargo clippy --all-targets -- -D warnings

rust-test: ## Run the Rust suite
	cargo test

parity: ## Run the CLI tier against both implementations
	cargo build --release
	REQUIRE_RUST_BINARY=1 uv run python -m pytest tests/test_cli_corpus.py -q

rust-tidy: ## Auto-format the Rust
	cargo fmt

# The Rust suite was held out while its corpus tests were red by construction --
# a `check` that is red for six tasks is one nobody reads. Both implementations
# now answer both tiers, so it is folded in, along with the CLI tier that runs
# each binary in turn. `parity` builds in release mode and is the slowest target
# here; it earns that by being the only one that compares the two.
check: tidy test floor rust-lint rust-test parity ## Tidy, test, and check both implementations
