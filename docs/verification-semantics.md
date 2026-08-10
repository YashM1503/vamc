# Verification semantics

VAMC uses explicit states and never collapses them into a generic correctness
claim:

- `UNVERIFIED`
- `STATICALLY_CHECKED`
- `VERIFIED_FOR_TEST_DOMAIN`
- `FAILED`
- `UNAVAILABLE`

Migration separately records `TRANSLATED` or `FALLBACK_REQUIRED`. Optimization
candidates begin as `REQUIRES_VERIFICATION`; generation alone cannot select one.

## Static verification

Static verification checks the manifest inventory, SHA-256 digests, byte sizes,
generated-file presence, source-map consistency, and Python syntax. It never
imports generated modules. Passing this level earns only `STATICALLY_CHECKED`.

## Differential verification

`VERIFIED_FOR_TEST_DOMAIN` means the original F2PY oracle and generated routine
agreed for the recorded cases, returned values, mutated positional and keyword
arguments, exception type, and numerical policy. Both sides run in separate
hardened containers. It is empirical evidence for that domain, not universal or
formal equivalence.

Case files are bounded JSON with schema `0.1.0`. Arrays specify values and dtype;
case IDs must be unique. See [`sandbox/README.md`](../sandbox/README.md) for an
example and the Docker invocation.

## Numerical policies

Built-in profiles are:

| Profile | Relative tolerance | Absolute tolerance |
| --- | ---: | ---: |
| `strict` | `1e-12` | `1e-14` |
| `scientific_default` | `1e-8` | `1e-10` |

Reports record compared-value count, maximum absolute and relative error, NaN
mismatches, infinity/sign mismatches, and structural mismatches. Boolean values
are not silently coerced to integers. Tolerances must be non-negative and cannot
be widened by generated code or an optional model.

## Acceptance and benchmarking

Every accepted candidate must eventually record its source mapping,
transformations, preconditions, policy, case count, seeds, maximum errors,
mutation comparison, exceptions, and failing reproducer. Benchmarking is allowed
only after candidate-specific verification succeeds. Candidate-specific native
acceptance and benchmark ranking are not yet implemented in this pre-alpha
build; generated candidates remain quarantined under `_candidates`.
