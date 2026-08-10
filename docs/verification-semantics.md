# Verification semantics

VAMC uses the following labels and will not collapse them into a generic
“verified” claim:

- `UNPARSED`
- `UNSUPPORTED`
- `TRANSLATED`
- `STATICALLY_CHECKED`
- `TESTED`
- `VERIFIED_FOR_TEST_DOMAIN`
- `FORMALLY_VERIFIED`

`VERIFIED_FOR_TEST_DOMAIN` will mean that the original executable and a
candidate agreed for the recorded fixtures, generated cases, mutation contract,
exception behavior, and numerical policy. It will not mean universal
mathematical equivalence.

Every accepted candidate must record its source mapping, transformations,
verification profile, case count, seeds, maximum errors, and failing
reproducers. Benchmarking is permitted only after verification succeeds.
