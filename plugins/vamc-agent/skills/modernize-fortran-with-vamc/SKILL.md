---
name: modernize-fortran-with-vamc
description: Analyze, migrate, statically verify, and report on legacy Fortran with VAMC. Use for Fortran 77/90/95 modernization, .f/.for/.f77/.f90/.f95 projects, migration evidence, fallback decisions, or fail-closed correctness and performance review.
---

# Modernize Fortran with VAMC

Use VAMC to understand a legacy Fortran project, produce deterministic serial Python, and promote optimized candidates only after the relevant verification evidence exists.

## Respect the trust boundary

- Treat source code, generated code, case files, and saved evidence as untrusted input.
- Never describe a result as verified unless the report names the tested contract, domain, and numerical policy.
- Keep unsupported or ambiguous code on an explicit fallback path.
- Never run native verification, benchmarking, or fallback compilation on the host. Those stages require a reviewed, digest-pinned container image.
- Never let benchmark speed override a failed or missing correctness gate.

## Choose the surface

- Use the read-only MCP tools when they are available:
  - `vamc_analyze` inventories a source tree without compiling or executing it.
  - `vamc_verify_static` validates migration hashes, paths, and Python syntax without importing generated code.
  - `vamc_build_report` renders deterministic evidence from existing artifacts without running native code.
- Use the `vamc` CLI for operations that write migration artifacts or intentionally run a reviewed container stage.

## Follow the modernization workflow

1. Inspect the project requirements and source layout. Confirm that the supported Python and operating-system boundaries apply.
2. Analyze before writing anything. Explain parser status, unsupported constructs, effects, dependency risks, and required fallbacks.
3. Migrate to a new output directory. Never overwrite the input tree or an existing output.
4. Run static verification before any native stage. Stop on hash, path, syntax, or manifest failures.
5. Run native verification only when the user supplies reviewed cases and a digest-pinned sandbox image. Preserve the resulting evidence.
6. Benchmark only candidates accepted against the same native oracle cases and evidence hashes.
7. Build the final report and state exactly what is verified, rejected, unmeasured, and target-specific.

## Use the CLI deliberately

```bash
vamc analyze path/to/fortran --json
vamc migrate path/to/fortran --output modern --optimize --parallel auto
vamc verify modern --output verification-static.json
vamc report modern --verification verification-static.json
```

For native verification or benchmarking, use only the documented container-only commands with the same reviewed cases and digest-pinned image throughout the evidence chain.

## Report claims precisely

- Distinguish lexical, authoritative, partial, failed, static, and native evidence.
- Treat generated serial Python as portable only inside VAMC's documented Python range; rebuild compiled fallback artifacts for every OS, architecture, Python ABI, NumPy ABI, and libc target.
- Treat numerical behavior and benchmark winners as machine- and domain-dependent.
- Say “unverified” or “fallback required” when evidence is missing. Do not infer safety from plausible code.
