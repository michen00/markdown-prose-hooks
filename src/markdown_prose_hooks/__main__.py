"""Entry point for ``python -m markdown_prose_hooks``.

The console script is how consumers reach the tool, and it stays the supported
spelling. This exists because the conformance harness needs to invoke *an*
implementation by path without knowing how its environment was built: a console
script lives wherever the installer put it, while ``-m`` resolves through
``sys.executable`` and works the same in a uv venv, a pre-commit environment, or
a plain ``pip install --user``.

``-m markdown_prose_hooks.unwrap`` would do the same job and emits a
``RuntimeWarning``, because ``__init__`` imports from ``unwrap`` and so leaves it
in ``sys.modules`` before ``runpy`` executes it. Nothing misbehaves as a result,
but a warning on stderr for every harness invocation is noise that has to be
explained every time it is read.
"""

from markdown_prose_hooks.unwrap import main

raise SystemExit(main())
