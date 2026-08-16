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

## Candidate acceptance and benchmarking

Every candidate retains its source mapping, transformations, and preconditions.
Native verification executes it against the same oracle results used for the
serial baseline and records policy, case count, maximum errors, mutation, and
exception behavior. Failed candidates are rejected; unavailable candidates are
not silently accepted.

Benchmarking accepts only `VERIFIED_FOR_TEST_DOMAIN` candidates from an evidence
record whose migration digest, normalized-case digest, and sandbox image match
exactly. It warms implementations, records raw steady-state nanosecond samples
and environment metadata, and ranks deterministically by median time and ID.
The serial baseline participates, so an optimization is never selected merely
because one was generated.

Case inputs are user-authored domain contracts. Automatic scientific property
generation is not part of the scoped MVP because VAMC cannot infer valid input
domains safely from syntax alone.

F2PY wrapper behavior is part of the oracle boundary. Some compiler/wrapper
combinations reject otherwise valid edge domains such as zero-length explicit
shape arrays. VAMC fails closed on an oracle/candidate exception mismatch; users
should record such wrapper limits separately rather than treating them as a
translation acceptance case.
