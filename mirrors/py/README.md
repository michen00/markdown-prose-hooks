# markdown-prose-hooks-py

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/michen00/markdown-prose-hooks-py)

The two `pre-commit` hook ids for the Python implementation of [markdown-prose-hooks](https://github.com/michen00/markdown-prose-hooks), and nothing else.

Nothing here is authored. This tree is a reduced view of that repository, carrying only what building and running these two ids requires, so that a consumer downloads one implementation rather than two implementations plus the corpus that specifies them and the notebook that measures them. It is replaced wholesale rather than merged, so an edit made here is an edit that gets overwritten — send it upstream, as [CONTRIBUTING.md](CONTRIBUTING.md) says at more length. A version tag is the exception to all of that motion: a ruleset makes `v*.*.*` here immutable, so the tree `v@VERSION@` names is the tree it will always name, while `main` moves on every release.

## Use

```yaml
repos:
  - repo: https://github.com/michen00/markdown-prose-hooks-py
    rev: v@VERSION@ # frozen once published; `pre-commit autoupdate` moves it
    hooks:
      - id: unwrap-markdown-prose-py
```

`unwrap-markdown-prose-py` joins manual soft-wrap line breaks in Markdown prose, leaving code fences, tables, lists, front matter, hard breaks, and label rows untouched. `unwrap-markdown-prose-py-check` reports the same files and rewrites nothing, for repositories that want the signal rather than the edit.

Exclusions belong to the tool rather than to the framework: `.unwrapignore` and `--exclude` reach every way of invoking it, while `pre-commit`'s own `exclude:` key reaches only this one.

## What lives upstream

The conformance corpus that specifies the behavior, the Rust implementation that answers to the same corpus, the differential fuzzer that compares them, the benchmarks, and the design documents. So does installing the tool outside `pre-commit`: it is published as `markdown-prose-hooks` on PyPI and on crates.io, under that name rather than this repository's, which is deliberately unpublished.

## License

MIT, in [LICENSE](LICENSE).
