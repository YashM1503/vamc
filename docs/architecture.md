# Architecture

VAMC is an evidence-carrying, fail-closed modernization pipeline:

```text
bounded source snapshot
  -> lexical normalization and risk hints
  -> PSyclone/fparser2 authoritative parse
  -> stable semantic digest and project call graph
  -> PSyIR dependency analysis
  -> serial Python plus explicit fallback registry
  -> unaccepted NumPy/Numba candidates
  -> static artifact verification
  -> container-only F2PY oracle and differential cases
  -> verified-candidate benchmarking (next milestone)
  -> JSON/HTML report and selected hybrid package (next milestone)
```

Analysis and generation operate on the same bounded, root-anchored in-memory
source snapshot. VAMC does not reopen a discovered source through a less secure
path during migration.

## Components

- `frontends/fortran.py` provides bounded normalization and conservative risk
  hints.
- `frontends/psyir.py` adapts PSyclone/PSyIR into VAMC's stable typed records.
  Parser objects never leak into the public schema.
- `analysis/inventory.py` performs secure discovery, builds the call graph, and
  resolves unique project-local calls.
- `backends/python.py` emits deterministic serial Python and source maps for the
  explicitly supported PSyIR subset.
- `backends/optimized.py` generates NumPy and Numba candidates. Every candidate
  starts as `REQUIRES_VERIFICATION`; generation is not acceptance.
- `migration.py` creates an immutable in-memory result and atomically writes a
  new reviewable package without overwriting an existing directory.
- `verify/static.py` checks artifact hashes and Python syntax without imports or
  execution.
- `runtime/sandbox.py` is the only native execution boundary.
- `verify/native.py` compiles the captured original with F2PY and compares
  bounded cases inside hardened Docker containers.
- `models.py` owns the versioned evidence vocabulary; `project.py` and `cli.py`
  are the public Python and command-line boundaries.

## Generated package

`vamc migrate` writes:

```text
modern/
├── .vamc-generated
├── analysis.json
├── fallback-registry.json
├── modernization.json
├── README_MODERNIZATION.md
├── legacy/                       # exact bounded source snapshot
├── pyproject.toml
└── src/vamc_modernized/
    ├── __init__.py
    ├── _runtime.py
    ├── <source-module>.py         # readable serial baseline
    └── _candidates/              # never selected before verification
```

## Trust and acceptance

Parsing, translation, candidate generation, verification, selection, and
benchmarking are separate states. A successfully parsed or generated routine is
not called verified. A faster candidate may only be ranked after its recorded
test domain passes under the selected numerical policy.

Current limitation: the native harness verifies exported serial routines.
Candidate-specific native acceptance, benchmark ranking, the compiled fallback
bridge, and HTML reporting remain open milestones.
