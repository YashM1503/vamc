# Changelog

All notable changes will be documented here.

## Unreleased

### Added

- Initial package, CLI, typed public API, and engineering foundation.
- Bounded Fortran source discovery and fixed/free-form normalization.
- Deterministic routine, symbol, call, side-effect, and loop inventory.
- Conservative loop-pattern classification and fallback markers.
- Unit, integration, and security regression tests.
- Structured diagnostics, lexical-only support status, and tri-state effect evidence.
- Aggregate byte, line, statement, nesting, and no-clobber report safeguards.
- Security scanning, artifact validation, property tests, and public community files.
- PSyclone/fparser2 authoritative parsing with typed symbols, source spans, parser status,
  bounded PSyIR nodes, and deterministic project call resolution.
- Fail-closed PSyIR dependency analysis for maps, reductions, stencils, recurrences,
  scatter risks, and effectful loops.
- Deterministic serial-Python migration with Fortran index normalization, exact source
  snapshots, source maps, atomic output, and an explicit fallback registry.
- Hash- and syntax-based static verification that never imports generated code.
- Explicit strict and scientific numerical policies with structural, NaN, infinity,
  absolute-error, and relative-error accounting.
- Docker-only F2PY oracle verification with digest-pinned images, disabled networking,
  read-only filesystems, dropped capabilities, non-root execution, and resource limits.
- Verification-gated NumPy, Numba serial, and Numba `prange` candidates.
- `vamc migrate` and `vamc verify` CLI workflows plus `Project.migrate()` and
  `MigrationResult.verify()` Python APIs.
- Candidate-specific differential acceptance with migration and normalized-case
  evidence hashes.
- Authoritative source-argument to F2PY wrapper adaptation for inferred and
  reordered dimension arguments.
- Verified-only, sandboxed benchmark ranking with warmups, repeated raw timings,
  environment metadata, and serial-baseline selection.
- Explicit generated fallback dispatch and container-only F2PY bridge builds
  with hash-recorded, platform-specific artifacts.
- Deterministic `modernization-report.json` and escaped, self-contained,
  CSP-restricted `modernization-report.html` generation.
- Public seed corpus, complete CLI documentation, MVP boundary, and contributor
  extension guidance.

### Changed

- Require supported Python 3.11 or newer; Python 3.9 is end-of-life.
- Mark unresolved calls, malformed scopes, and unsupported statements as fallback-required.
- Correct fixed-form labeled loops, semicolon statements, typed functions, string-aware
  keyword detection, stable loop IDs, and stencil-shaped loop hints.
- Replace lexical-only support claims with authoritative, partial, and failed parser states.
- Declare PSyclone as a runtime dependency and NumPy/Numba as optional optimization extras.

### Security

- Reject unsafe artifact paths, symlinked verification inputs, digest mismatches, oversized
  manifests and case files, unpinned sandbox images, and native verification on the host.
- Reject stale or duplicate benchmark evidence, unverified candidates, mismatched
  images/cases, symlinked compiler products, implicit fallback loading, and
  unescaped report content.
