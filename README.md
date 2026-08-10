# VAMC

**Verified Adaptive Modernization Compiler**

Turn legacy scientific Fortran into readable, tested, parallel Python.

VAMC is an evidence-first modernization toolchain. It is being built to analyze
program structure and dependencies, generate modern implementation candidates,
execute those candidates against the original program, reject transformations
that fail verification, and benchmark only the survivors.

> LLMs can propose. Evidence decides.

## Current status

VAMC is pre-alpha. The first demoable milestone, **Understand**, is implemented:

- bounded, non-executing discovery of Fortran 77/90/95 source files;
- fixed- and free-form statement normalization;
- routine, argument, symbol, call, side-effect, and loop inventory;
- deliberately conservative map, reduction, recurrence, and side-effect labels;
- deterministic, machine-readable semantic digests;
- a typed Python API and `vamc analyze` CLI.

The current scanner is an inventory bootstrap, not a complete Fortran parser.
PSyclone/PSyIR integration is the next frontend milestone. No generated code is
currently labeled verified.

## Quick start

```bash
python -m venv .venv
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

See [the security model](docs/security-model.md), [verification semantics](docs/verification-semantics.md),
and [architecture](docs/architecture.md).

## Roadmap

1. Understand — semantic digest and program inventory (in progress)
2. Translate — readable serial Python
3. Verify — native Fortran oracle plus differential testing
4. Parallelize — dependency-aware NumPy/Numba candidates
5. Optimize — benchmark verified candidates only
6. Repository — multi-file projects with hybrid fallback and full reports

The north-star metric is zero known unsafe loops marked safe on the benchmark
corpus.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Security reports should follow
[SECURITY.md](SECURITY.md), not a public issue.

## License

Apache-2.0. See [LICENSE](LICENSE).
