# Scoped MVP closure

The MVP is an end-to-end, evidence-carrying path for small scientific kernels in
VAMC's documented Fortran subset. Every stage is independently usable:

1. `analyze` creates a bounded semantic inventory and call graph without execution.
2. `migrate` emits readable serial Python, source maps, candidates, retained
   source, and explicit fallback metadata.
3. `verify` checks artifact integrity or compares the serial baseline and each
   candidate with a containerized F2PY oracle for caller-supplied cases.
4. `benchmark` times only candidates verified for the exact migration, cases,
   numerical policy record, and digest-pinned image; serial remains eligible to win.
5. `build-fallback` compiles retained Fortran only in the sandbox and produces a
   separate, hash-recorded platform-specific extension for explicit binding.
6. `report` joins hash-bound evidence into deterministic JSON and self-contained,
   escaped HTML.

## What closure does not mean

- Differential testing proves agreement only for the recorded test domain.
- The seed corpus is a regression floor, not broad language-coverage evidence.
- VAMC does not invent valid scientific inputs. Users must supply domain cases;
  Hypothesis protects VAMC internals, while automatic per-project property-case
  synthesis remains future work.
- Unsupported and ambiguous semantics stay behind explicit fallback or fail.
- Native steps require a working Docker daemon and a reviewed digest-pinned image.
- Fallback binaries are not hardware-neutral; build one per target platform and ABI.
- Benchmark selection is local evidence, not a portable speed guarantee.
- There is no LLM correctness authority, telemetry, hosted service, GPU, MPI,
  native Windows, or arbitrary mixed-language build support.

The repository is suitable for public collaboration and controlled evaluation.
It is not yet a published stable package or a claim of production readiness.
