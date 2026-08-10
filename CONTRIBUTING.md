# Contributing

VAMC prioritizes correctness and security over feature count. It is pre-alpha;
please discuss large architectural changes in an issue before implementation.

## Development setup

Use Python 3.11 or newer:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,security]'
```

Before opening a pull request, run:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov=vamc --cov-report=term-missing --cov-fail-under=90
bandit -q -r src -ll -ii
python -m build
check-wheel-contents dist/*.whl
twine check dist/*
```

## Change requirements

- Add regression tests for every correctness or security bug.
- Document each newly supported Fortran construct and its failure behavior.
- Keep parsing fail-closed: unknown syntax must not become evidence of safety.
- Never add source execution that bypasses the sandbox boundary.
- Never let generated code choose numerical tolerances or allow performance to
  override verification.
- Keep changes focused; generated artifacts and environment files do not belong
  in commits.

Pull requests require passing CI, resolved review conversations, and an update
to `CHANGELOG.md` for user-visible behavior. By contributing, you agree that
your work is licensed under Apache-2.0 and that you have the right to submit it.

Follow `CODE_OF_CONDUCT.md`. Report vulnerabilities through `SECURITY.md`, not
in a public issue.
