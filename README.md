# VAMC

**Verified Adaptive Modernization Compiler**

Analyze legacy scientific Fortran, generate fail-closed serial Python, and prepare
verification-gated NumPy/Numba candidates.

VAMC is an alpha, evidence-first modernization project. It combines a
PSyclone/fparser2 semantic frontend with deterministic serial-Python migration,
source maps, explicit hybrid fallback dispatch, static artifact verification, a
container-only F2PY differential harness, verification-gated NumPy/Numba
candidates, reproducible benchmark ranking, and self-contained reports.

> Proposals are provisional. Evidence decides.

## Current status

The scoped MVP includes:

- bounded, non-executing discovery of Fortran 77/90/95 source files;
- fixed- and free-form statement normalization;
- routine, argument, symbol, call, observed-effect, and loop-shape inventory;
- authoritative PSyIR symbols, call graphs, and fail-closed dependency analysis;
- deterministic serial Python, source maps, and an explicit fallback registry;
- candidate-specific acceptance/rejection against the same native oracle cases;
- verified-only NumPy, Numba JIT, and `prange` benchmarking and selection;
- hash/syntax verification and domain-scoped numerical comparison;
- Docker-only F2PY oracle execution with no automatic host fallback;
- explicit native fallback binding plus a container-only, hash-recorded bridge build;
- deterministic JSON and escaped, CSP-restricted HTML reports;
- typed APIs and complete analyze, migrate, verify, benchmark, fallback-build,
  and report CLI stages;
- a public seed corpus with bounded differential cases.

Unsupported syntax, effects, calls, scalar output mutation, and ambiguous routines
require fallback. Generated code is not labeled verified until a supplied test
domain passes against the native oracle.

## Requirements and portability

- Python 3.11 through 3.14;
- macOS or Linux on CPU architectures supported by Python and PSyclone;
- Windows through WSL (native Windows is not currently supported);
- PSyclone 3.x (which includes fparser2) for semantic analysis;
- no GPU, Fortran compiler, container runtime, database, cloud account, or network
  connection for the current `analyze` command.

NumPy/Numba are optional (`vamc[optimize]`). Native verification, benchmarking,
and fallback compilation additionally require Docker, a digest-pinned sandbox
image, and a Fortran toolchain inside that image. A compiled fallback extension
is specific to the operating system, architecture, Python ABI, NumPy ABI, and
libc used to build it; rebuild it for each deployment target. Analysis and
generated serial Python are hardware-independent within the stated Python
support range, but numerical behavior and benchmark winners can vary by machine.

## Quick start

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

vamc analyze examples/daxpy
vamc analyze examples/daxpy --json
vamc analyze examples/daxpy --output analysis.json
vamc migrate examples/daxpy --output modern --optimize --parallel auto
vamc verify modern --output verification-static.json

# Native stages require your own reviewed, digest-pinned sandbox image.
vamc verify modern --cases examples/daxpy/cases.json \
  --sandbox-image 'registry.example/vamc@sha256:<64-hex-digest>' \
  --output verification.json
vamc benchmark modern --cases examples/daxpy/cases.json \
  --verification verification.json \
  --sandbox-image 'registry.example/vamc@sha256:<same-digest>' \
  --output benchmark.json
vamc report modern --verification verification.json --benchmark benchmark.json
```

Python API:

```python
import json
from pathlib import Path

from vamc import Project, build_report
from vamc.benchmark import benchmark_migration_directory
from vamc.verify import verify_native_directory

project = Project.from_path("examples/daxpy")
analysis = project.analyze()
migration = project.migrate(optimize=True, parallel="auto")
modern = migration.write("modern")
IMAGE = "registry.example/vamc@sha256:<64-hex-digest>"
verification = verify_native_directory(modern, "examples/daxpy/cases.json", image=IMAGE)
Path("verification.json").write_text(json.dumps(verification.to_dict()))
benchmark = benchmark_migration_directory(
    modern, "examples/daxpy/cases.json", "verification.json", image=IMAGE
)
Path("benchmark.json").write_text(json.dumps(benchmark.to_dict()))
report = build_report(
    modern, verification_path="verification.json", benchmark_path="benchmark.json"
)
```

## Trust model

- Source and generated code are untrusted inputs.
- Analysis does not compile, import, or execute source code.
- Unknown parallelism stays serial.
- Performance can never override correctness.
- “Verified” will always name the exercised contract, test domain, and
  numerical policy; differential testing is not formal proof.

See [the security model](docs/security-model.md),
[verification semantics](docs/verification-semantics.md),
[architecture](docs/architecture.md), and the [CLI reference](docs/cli.md).

## MVP boundary

The six demonstrable stages—understand, translate, verify, parallelize, optimize,
and report/package with explicit fallback—are implemented for the documented
Fortran subset. This is not support for arbitrary Fortran, formal verification,
or a production package release. Automatic property-input synthesis, a large
real-world corpus, signed evidence, GPU/MPI backends, and native Windows remain
post-MVP work. See [the precise MVP boundary](docs/mvp-scope.md).

The north-star metric is zero known unsafe loops marked safe on the benchmark
corpus.

## Documentation

The [documentation index](docs/README.md) links every public usage, architecture,
security, extension, contribution, support, and release guide shipped with VAMC.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Security reports should follow
[SECURITY.md](SECURITY.md), not a public issue. Maintainers should use the
[public release checklist](docs/release-checklist.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
