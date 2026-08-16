# Public regression corpus

`manifest.json` lists small, reviewable kernels used by the deterministic parser,
translation, dependency-analysis, and case-schema tests. Each example keeps its
Fortran source next to bounded differential cases.

This seed corpus is deliberately small; it is a regression floor, not evidence
that VAMC supports arbitrary Fortran. Add every newly supported construct and
every fixed correctness or security bug here when a compact reproducer exists.
