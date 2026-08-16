# CLI reference

## Analyze

```bash
vamc analyze legacy/ --json
vamc analyze legacy/ --output analysis.json
```

Analysis is bounded, deterministic, and non-executing. Resource-limit flags are
available for files, bytes, lines, statements, nesting, and PSyIR nodes.

## Migrate

```bash
vamc migrate legacy/ --output modern/
vamc migrate legacy/ --output modern/ --optimize --parallel auto
vamc migrate legacy/ --output modern/ --fail-on-unsupported
```

The command only creates a new destination. It never clobbers an existing path.
`--parallel auto` generates candidates only after dependency analysis; every
candidate remains `REQUIRES_VERIFICATION`.

## Verify

Static, non-executing verification:

```bash
vamc verify modern/
vamc verify modern/ --json --output verification.json
```

Native differential verification:

```bash
vamc verify modern/ \
  --cases cases.json \
  --sandbox-image 'registry.example/vamc-sandbox@sha256:<digest>' \
  --verification-profile scientific_default \
  --output verification.json
```

`--cases` and `--sandbox-image` must be supplied together. A failed case exits
nonzero; unavailable requested native verification uses a distinct nonzero exit
status. VAMC never substitutes host execution.

Native verification tests the serial baseline and every generated optimization
candidate against the same oracle case. The evidence binds the migration and
normalized cases by SHA-256.

## Benchmark

```bash
vamc benchmark modern/ \
  --verification verification.json \
  --cases cases.json \
  --sandbox-image 'registry.example/vamc-sandbox@sha256:<same-digest>' \
  --output benchmark.json
```

Only candidates with `VERIFIED_FOR_TEST_DOMAIN` evidence for the exact
migration, cases, and image are timed. Imports, input decoding, and JIT warmup
are excluded from steady-state samples. The serial baseline participates in
selection and wins when no verified optimization is faster.

## Build a native fallback

```bash
vamc build-fallback modern/ \
  --sandbox-image 'registry.example/vamc-sandbox@sha256:<digest>' \
  --output fallback-build/
```

This command is valid only when at least one routine requires fallback. It
compiles retained source in Docker and writes a separate extension plus
`fallback-build.json`. Review the record, install the generated package with its
`fallback` extra, and bind the extension explicitly with
`bind_fallback_path()`. The extension is platform and ABI specific.

## Report

```bash
vamc report modern/
vamc report modern/ \
  --verification verification.json \
  --benchmark benchmark.json \
  --output-dir evidence/
```

The default destination is `modern/reports/`. VAMC validates evidence linkage
before producing `modernization-report.json` and a self-contained, escaped,
CSP-restricted `modernization-report.html`. Reports are not added to the signed
migration artifact inventory they describe.

## Exit behavior

- `0`: requested operation completed without a recorded failure.
- `1`: verification, compilation, or another evidence-producing stage failed.
- `2`: invalid input, unsafe path, unsupported configuration, or CLI error.
- `3`: a requested native verification, benchmark, or fallback build remained unavailable.
