# Extending VAMC safely

This guide maps common contributions to the evidence they must carry.

## Add Fortran support

1. Put a minimal source and bounded `cases.json` in `examples/` and register it
   in `corpus/manifest.json`.
2. Confirm the authoritative PSyIR shape; lexical hints are not proof of support.
3. Extend `frontends/psyir.py` or `backends/python.py` for exactly that shape.
4. Add accepted, rejected, malformed, and resource-bound tests.
5. Update `docs/supported-fortran.md` with both support and fallback behavior.

Never turn parser failure, a `CodeBlock`, unknown argument mutation, or an
unresolved call into translated output.

## Add an optimization candidate

Candidate generation belongs in `backends/optimized.py`. Record its parent,
backend, transforms, preconditions, generated file, and initial
`REQUIRES_VERIFICATION` status. Dependency analysis must establish the required
loop property before generation. Pattern similarity alone is insufficient.

Add tests proving that:

- an eligible loop emits the candidate deterministically;
- an unsafe or unknown loop does not emit it;
- candidate-specific differential verification can accept and reject it;
- benchmarking ignores it unless evidence matches the exact migration, cases,
  and digest-pinned image.

## Add a numerical policy or comparator type

Work in `verify/compare.py`. Specify structural behavior, NaN and infinity
semantics, absolute and relative error definitions, empty inputs, mutation, and
exception comparison. Tolerances must be selected by the caller and recorded in
evidence; generated code cannot widen them.

## Change the sandbox

`runtime/sandbox.py` is a critical trust boundary. Preserve network isolation,
read-only root, capability removal, non-root identity, sanitized environment,
bounded output/time/CPU/memory/PIDs/files, and the absence of a host fallback.
Every new mount should be read-only unless it is a dedicated result directory.

Sandbox changes require adversarial command-construction tests and a security
model update. Do not run native fixtures in credential-bearing pull-request CI.

## Change evidence or reports

Schemas in `models.py` are versioned public records. Readers must reject unknown
or inconsistent versions and bind downstream records with SHA-256. Report HTML
must use escaped text, no remote resources or scripts, and a restrictive CSP.
Keep output deterministic: avoid timestamps, random IDs, absolute temporary
paths, and unordered collections.

## Definition of done

A smart change is small enough to audit, conservative on uncertainty,
deterministic, typed, documented, covered by regression and adversarial tests,
and explicit about what its evidence does not prove.
