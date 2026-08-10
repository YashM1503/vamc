# VAMC

**Verified Adaptive Modernization Compiler**

Analyze legacy scientific Fortran, generate fail-closed serial Python, and prepare
verification-gated NumPy/Numba candidates.

VAMC is a pre-alpha, evidence-first modernization project. It now combines a
PSyclone/fparser2 semantic frontend with deterministic serial-Python migration,
source maps, hybrid fallback records, static artifact verification, a
container-only F2PY differential harness, and unaccepted NumPy/Numba candidates.

> LLMs can propose. Evidence decides.

## Current status

VAMC is pre-alpha. The current build includes:

- bounded, non-executing discovery of Fortran 77/90/95 source files;
- fixed- and free-form statement normalization;
- routine, argument, symbol, call, observed-effect, and loop-shape inventory;
- authoritative PSyIR symbols, call graphs, and fail-closed dependency analysis;
- deterministic serial Python, source maps, and an explicit fallback registry;
- NumPy, Numba JIT, and `prange` candidates that remain unaccepted until verified;
- hash/syntax verification and domain-scoped numerical comparison;
- Docker-only F2PY oracle execution with no automatic host fallback;
- typed APIs plus `vamc analyze`, `vamc migrate`, and `vamc verify`.

Unsupported syntax, effects, calls, scalar output mutation, and ambiguous routines
require fallback. Generated code is not labeled verified until a supplied test
domain passes against the native oracle.

## Requirements and portability

- Python 3.11 through 3.14;
- macOS or Linux on any CPU architecture supported by Python;
- Windows through WSL (native Windows is not currently supported);
- PSyclone 3.x (which includes fparser2) for semantic analysis;
- no GPU, Fortran compiler, container runtime, database, cloud account, or network
  connection for the current `analyze` command.

NumPy/Numba are optional (`vamc[optimize]`). Native verification additionally
requires Docker, a digest-pinned sandbox image, and a compiler inside that image.

## Quick start

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

vamc analyze examples/daxpy
vamc analyze examples/daxpy --json
vamc analyze examples/daxpy --output modernization-report.json
vamc migrate examples/daxpy --output modern --parallel auto
vamc verify modern
```

Python API:

```python
from vamc import Project

project = Project.from_path("examples/daxpy")
analysis = project.analyze()
migration = project.migrate(optimize=True, parallel="auto")
migration.write("modern")
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

1. Understand — authoritative semantic inventory and call graph implemented
2. Translate — readable serial Python and source maps implemented for the supported subset
3. Verify — static checks and container-only differential harness implemented
4. Parallelize — fail-closed NumPy/Numba candidate generation implemented
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
