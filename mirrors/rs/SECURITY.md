# Security policy

Report a vulnerability upstream, in [markdown-prose-hooks](https://github.com/michen00/markdown-prose-hooks), through its private advisory form: <https://github.com/michen00/markdown-prose-hooks/security/advisories/new>. Please do not open a public issue for a security report.

Upstream is where a fix has to land. Every file here is written by `scripts/generate_mirrors.py` in that repository and pushed by its release flow, which replaces this whole tree on every release, so a fix committed here is a fix the next release deletes. That is why this page is a pointer rather than a form of its own.

The rest of the policy is upstream and covers these hooks too -- what the tool can reach, how a release is verified, and what to pin: <https://github.com/michen00/markdown-prose-hooks/blob/main/SECURITY.md>.

Two things make a report about these Rust hooks faster to act on: which of the two ids you ran, and the `rev:` you had pinned.
