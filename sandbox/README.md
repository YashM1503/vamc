# VAMC verification sandbox

VAMC never compiles or executes user Fortran or generated Python directly on the
host. Native differential verification requires Docker and a purpose-built image.

Build the image from a digest-pinned, platform-appropriate Python base:

```bash
docker build sandbox \
  --build-arg BASE_IMAGE='python:3.13-slim@sha256:<base-image-digest>' \
  --tag vamc-sandbox:local

docker image inspect vamc-sandbox:local --format '{{index .RepoDigests 0}}'
```

The tag alone is intentionally rejected by `vamc verify`. Use the resulting
`name@sha256:...` reference. If a locally built image has no repository digest,
push it to a trusted registry or address it by its `sha256:...` image ID.

Every verification container runs with networking disabled, a read-only root
filesystem, all Linux capabilities dropped, `no-new-privileges`, a non-root UID,
bounded CPU, memory, PIDs, output, file size, and wall time, plus explicit
read-only input mounts and a dedicated result directory. There is no automatic
host-execution fallback.

Case files use schema `0.1.0`:

```json
{
  "schema_version": "0.1.0",
  "cases": [
    {
      "id": "daxpy-small",
      "routine": "daxpy",
      "arguments": [
        {"kind": "scalar", "value": 3},
        {"kind": "scalar", "value": 2.0},
        {"kind": "array", "dtype": "float64", "value": [1, 2, 3]},
        {"kind": "array", "dtype": "float64", "value": [10, 20, 30]}
      ]
    }
  ]
}
```

Run:

```bash
vamc verify modern/ \
  --cases cases.json \
  --sandbox-image 'registry.example/vamc-sandbox@sha256:<digest>' \
  --verification-profile scientific_default \
  --output verification.json
```

The report uses `VERIFIED_FOR_TEST_DOMAIN`; differential tests are never called
formal proof.
