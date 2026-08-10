# VAMC

**Verified Adaptive Modernization Compiler**

Build a bounded, non-executing inventory of legacy scientific Fortran.

VAMC is a pre-alpha, evidence-first modernization project. Today it provides a
conservative lexical inventory. Translation, differential verification, and
parallelization are roadmap goals and are not implemented yet.

> LLMs can propose. Evidence decides.

## Current status

VAMC is pre-alpha. A bootstrap slice of the **Understand** milestone is implemented:

- bounded, non-executing discovery of Fortran 77/90/95 source files;
- fixed- and free-form statement normalization;
- routine, argument, symbol, call, observed-effect, and loop-shape inventory;
- deliberately conservative lexical loop hints that never authorize parallelism;
- deterministic, machine-readable lexical digests with explicit provenance;
- a typed Python API and `vamc analyze` CLI.

The scanner is not a complete Fortran parser. Its `LEXICALLY_SCANNED` status and
`UNKNOWN` effect values explicitly avoid claiming semantic completeness. Unknown
calls, unsupported statements, and malformed scopes require fallback. No code is
generated, executed, parallelized, or labeled verified.

## Requirements and portability

- Python 3.11 through 3.14;
- macOS or Linux on any CPU architecture supported by Python;
- Windows through WSL (native Windows is not currently supported);
- no runtime Python packages beyond the standard library;
- no GPU, Fortran compiler, container runtime, database, cloud account, or network
  connection for the current `analyze` command.

Future translation and verification stages will add optional native Fortran,
NumPy, Numba, and sandbox dependencies. They are not part of the current release.

## Quick start

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

vamc analyze examples/daxpy
vamc analyze examples/daxpy --json
vamc analyze examples/daxpy --output modernization-report.json
```

Python API:

```python
from vamc import Project

analysis = Project.from_path("examples/daxpy").analyze()
print(analysis.to_dict())
```

## Trust model

- Source and generated code are untrusted inputs.
- Analysis does not compile, import, or execute source code.
- Unknown parallelism stays serial.
- Performance can never override correctness.
- “Verified” will always name the exercised contract, test domain, and
  numerical policy; differential testing is not formal proof.

See [the security model](https://github.com/YashM1503/vamc/blob/main/docs/security-model.md),
[verification semantics](https://github.com/YashM1503/vamc/blob/main/docs/verification-semantics.md),
and [architecture](https://github.com/YashM1503/vamc/blob/main/docs/architecture.md).

## Roadmap

1. Understand — bounded lexical digest now; authoritative parsing remains in progress
2. Translate — readable serial Python
3. Verify — native Fortran oracle plus differential testing
4. Parallelize — dependency-aware NumPy/Numba candidates
5. Optimize — benchmark verified candidates only
6. Repository — multi-file projects with hybrid fallback and full reports

The north-star metric is zero known unsafe loops marked safe on the benchmark
corpus.

## Contributing

Read [CONTRIBUTING.md](https://github.com/YashM1503/vamc/blob/main/CONTRIBUTING.md).
Security reports should follow
[SECURITY.md](https://github.com/YashM1503/vamc/blob/main/SECURITY.md), not a public issue.
Maintainers should use the
[public release checklist](https://github.com/YashM1503/vamc/blob/main/docs/release-checklist.md).

## License

Apache-2.0. See [LICENSE](https://github.com/YashM1503/vamc/blob/main/LICENSE).
