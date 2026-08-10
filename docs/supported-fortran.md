# Supported Fortran

The current pre-alpha inventory recognizes `.f`, `.for`, `.ftn`, `.f77`, `.f90`,
and `.f95` files; programs, subroutines, and common typed functions; basic
declarations; `CALL` statements; and indexed `DO` loops.

It detects selected high-risk constructs such as process execution,
`EQUIVALENCE`, and computed `GOTO`, and marks the containing routine as requiring
fallback. It does not yet provide authoritative parsing or translation.

The supported subset will move to PSyclone/PSyIR in the next milestone. Until
then, all loop labels remain serial, conditionally safe, or unresolved. No loop
is marked parallel-safe by this scanner.
