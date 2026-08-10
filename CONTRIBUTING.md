# Contributing

VAMC prioritizes correctness and security over coverage.

1. Create a focused branch.
2. Add or update tests for every behavior change.
3. Run `ruff check .`, `ruff format --check .`, `mypy`, and `pytest`.
4. Document new supported Fortran constructs and their failure behavior.
5. Turn every correctness or security bug into a regression test.

Do not add an execution path that bypasses the sandbox boundary, let generated
code select numerical tolerances, or mark unresolved parallelism safe.
