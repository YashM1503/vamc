# Contributing to VAMC

VAMC welcomes corrections, new Fortran fixtures, compiler support, verification
work, security hardening, documentation, and performance backends. Contributors
normally fork the public repository, create a branch, and open a pull request;
`main` is protected and is not edited directly.

Correctness and security outrank translation coverage and speed. A conservative
fallback is an acceptable result. A silent semantic change is not.

## Start here

For a small fix, open a focused pull request. Discuss new schemas, trust-boundary
changes, major dependencies, and architecture changes in an issue first. Search
existing issues before creating another one and never report vulnerabilities in
a public issue; follow `SECURITY.md` instead.

Useful contribution paths include:

- adding a compact source and case file to the public corpus;
- improving diagnostics or documentation;
- supporting one previously rejected PSyIR construct;
- adding a transformation with an explicit analysis precondition;
- strengthening malformed-input, resource-limit, or sandbox tests;
- improving deterministic reports without adding remote content.

See `docs/extending-vamc.md` for the component-specific workflow.

## Development setup

Use a currently supported Python version (3.11 through 3.14):

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,security,optimize]'
```

The default analysis and static-verification tests do not need Docker or a
Fortran compiler. Native differential verification, benchmarking, and fallback
builds require Docker plus a digest-pinned sandbox image.

## Make a reviewable change

1. Create a branch from the current `main`.
2. Add the smallest failing regression test or corpus fixture first.
3. Implement the change without widening support claims.
4. Update user-facing docs, schemas, and `CHANGELOG.md` when behavior changes.
5. Run the checks below and describe the evidence in the pull request.

Keep commits focused. Do not commit virtual environments, caches, private source,
generated migrations, compiler products, tokens, credentials, or benchmark
claims from uncontrolled machines.

## Required evidence

Before opening a pull request, run:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov=vamc --cov-report=term-missing --cov-fail-under=85
bandit -q -r src -ll -ii
python -m build
check-wheel-contents dist/*.whl
twine check dist/*
python -m pip check
```

Network access is needed for `pip-audit --skip-editable`; CI also runs that
dependency audit. Native changes must include fake-boundary unit tests so normal
CI never executes contributor-supplied Fortran. Maintainers run live sandbox
validation separately without repository credentials.

## Correctness and security rules

- Unknown syntax, calls, aliasing, effects, and dependencies fail closed.
- New supported constructs need positive, boundary, and rejection tests.
- Every correctness or security fix needs a regression reproducer.
- Generated and original code never execute on the host through VAMC.
- Images used for execution are SHA-256 digest pinned; the network stays disabled.
- Performance results may rank only the exact candidates, migration, cases, and
  image recorded by successful candidate verification.
- Generated code cannot select tolerances, suppress failures, or approve itself.
- HTML must escape source-controlled text, remain self-contained, and preserve
  the restrictive Content Security Policy.
- Schema changes require a version change, compatibility decision, tests, and
  documentation.

## Pull-request review

Complete the pull-request template, including numerical and security impact.
Maintainers review compiler behavior, trust boundaries, evidence quality,
portability, and documentation—not only whether tests pass. All required checks
and review conversations must be resolved before merge.

AI-assisted contributions are welcome, but disclose substantial generated code
in the pull request and review it line by line. The contributor remains
responsible for provenance, licensing, correctness, and security.

By contributing, you agree that your work is licensed under Apache-2.0 and that
you have the right to submit it. Follow `CODE_OF_CONDUCT.md`.
