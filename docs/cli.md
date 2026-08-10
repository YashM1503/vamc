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

## Exit behavior

- `0`: requested operation completed without a recorded failure.
- `1`: verification found a failed routine.
- `2`: invalid input, unsafe path, unsupported configuration, or CLI error.
- `3`: native verification was requested but remained unavailable.
