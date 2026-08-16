# Supported Fortran

VAMC discovers `.f`, `.for`, `.ftn`, `.f77`, `.f90`, `.f95`, `.f03`, and `.f08`
files. The v1 compatibility target remains Fortran 77/90/95; later suffixes are
accepted so supported constructs in those files can be assessed conservatively.

## Authoritative analysis

PSyclone 3.x and fparser2 provide authoritative parsing and PSyIR for supported
programs, subroutines, functions, declarations, typed symbols, argument intent,
array rank and bounds, assignments, arithmetic, conditionals, indexed loops,
intrinsics, returns, and calls. VAMC records parser status as `AUTHORITATIVE`,
`PARTIAL`, or `FAILED` and retains bounded lexical evidence when parsing fails.

Project analysis resolves a call only when exactly one project routine has that
name. Duplicate definitions are ambiguous; unknown externals remain unresolved.

## Serial Python lowering

The current emitter supports:

- integer, real, logical, and character literals;
- scalar arithmetic, comparisons, and logical operators;
- rank-one and multidimensional indexed arrays with Fortran lower-bound
  normalization;
- assignment, inclusive positive or negative `DO` ranges, nested loops,
  conditionals, calls, and returns;
- common mathematical intrinsics such as `ABS`, trigonometric functions,
  logarithms, square root, `MOD`, conversions, rounding, `SIGN`, and `SIZE`;
- automatic local arrays when their shape bounds are known.

Scalar `intent(out)` and `intent(inout)` arguments currently require fallback
because Python cannot preserve their caller-visible mutation contract directly.
Array sections, unknown automatic-array shapes, unsupported intrinsics, partial
PSyIR `CodeBlock` regions, ambiguous routine names, and any unimplemented node
also require fallback. No partial routine is emitted as if complete.

Generated fallback wrappers are public but raise `FallbackUnavailableError`
until a reviewed callable or container-built `_vamc_legacy` extension is bound
explicitly. The bridge preserves operational access to unsupported routines
without mislabeling them as Python translations.

## Dependency and candidate analysis

Loops are labeled `MAP`, `REDUCTION`, `STENCIL`, `RECURRENCE`, `SIDE_EFFECT`, or
`UNKNOWN`. PSyIR dependency analysis can mark map/stencil loops conditionally
safe, identifies scatter-style write risks as serial, and keeps recurrences and
effectful calls serial. Reduction candidates remain conditional because floating
point reassociation changes numerical order.

NumPy generation is currently limited to direct rank-one unit-step map loops.
Numba serial candidates cover the supported direct-array subset. `prange`
candidates require one conditionally safe unit-step loop. Standard Fortran
non-aliasing assumptions and differential verification are still required.

## Explicitly unsupported or deferred

Arbitrary `EQUIVALENCE`, unrestricted computed `GOTO`, compiler extensions,
preprocessor-dependent syntax, opaque callbacks, file-driven side effects,
shell/process execution, MPI translation, GPU lowering, distributed memory, and
arbitrary mixed-language builds are not claimed. `UNKNOWN` always means “not
established,” never “safe.”
