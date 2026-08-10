# Supported Fortran

The current pre-alpha lexical inventory recognizes `.f`, `.for`, `.ftn`, `.f77`,
`.f90`, and `.f95` files. It scans named programs, subroutines, common typed
functions, basic intrinsic declarations, `CALL` statements, block and labeled
indexed `DO` loops, free-form semicolons, and basic continuations.

It detects selected high-risk constructs such as process execution,
`EQUIVALENCE`, and computed `GOTO`, and marks the containing routine as requiring
fallback. Unknown calls, unrecognized statements, interfaces, contained
procedures, malformed continuations, and unclosed scopes are diagnostic and
fail closed. Character literals are masked before keyword detection.

Not yet authoritative: modules and interface semantics, internal procedures,
function-reference resolution, derived types, preprocessing, full fixed-form
blank/continuation rules, alias analysis, control/data-flow, I/O target
resolution, and effect absence. `UNKNOWN` means “not established,” never “safe.”
All loop hints remain serial, conditionally safe, or unresolved; none is proof
of parallel safety.
