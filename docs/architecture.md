# Architecture

VAMC follows a staged, evidence-carrying pipeline:

```text
Fortran source
  -> discovery and normalization
  -> PSyclone / PSyIR frontend (next milestone)
  -> bounded lexical digest (current bootstrap)
  -> serial Python, NumPy, and Numba candidates
  -> isolated native oracle and candidate runtime
  -> differential and property verification
  -> verified-candidate benchmarking
  -> modern package plus JSON/HTML provenance
```

The current implementation covers the first discovery and inventory stage. It
never executes analyzed source. Its lexical classifications are hints with
fail-closed parallel statuses; they are not transformation authorizations.

## Boundaries

- `frontends/` converts source text to frontend records.
- `analysis/` discovers projects and assembles deterministic digests.
- `models.py` defines the versioned report vocabulary.
- `project.py` is the public API boundary.
- `cli.py` is a thin adapter over the public API.

Future compiler, runtime, verification, and report packages must consume the
same evidence model instead of bypassing it.
