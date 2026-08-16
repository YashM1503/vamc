# Security model

VAMC treats original source, generated code, compiler output, case files,
reports, and benchmark results as untrusted.

## Analysis and migration

- Analysis never compiles, imports, or executes Fortran.
- Symbolic-link input roots and discovered symlink files are rejected.
- Root-anchored descriptor reads reject path traversal, symlinks, device files,
  FIFOs, and source replacement during open.
- File count, per-file and aggregate bytes, lines, line length, normalized
  statements, loop nesting, and PSyIR node counts are bounded.
- Hidden, VCS, dependency, cache, build, and generated directories are excluded
  by default.
- Invalid UTF-8, unsupported input types, parser failure, partial PSyIR, unknown
  calls, and unsupported lowering all fail closed.
- Migration output is assembled in a private temporary directory and renamed
  atomically. Existing destinations and symlinks are never overwritten.
- Artifact paths are normalized and the manifest records SHA-256 and byte size.

## Static verification

`vamc verify modern/` uses root-anchored reads, enforces artifact and aggregate
size limits, checks every declared digest, and parses generated Python with
`ast`. It does not import or execute generated modules.

## Native execution boundary

There is no automatic host-execution fallback. Native differential verification
requires a digest-pinned Docker image and applies:

- `--network=none`;
- a read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- the caller's non-root UID/GID;
- bounded CPU, memory, PIDs, open files, output, per-file size, aggregate writable
  bytes/entries, and wall time;
- `noexec`, `nosuid`, and `nodev` runtime temporary storage;
- sanitized environment variables;
- read-only source, runner, oracle, and generated-package mounts;
- a dedicated writable result directory.

Native compilation uses the aggregate-monitored writable output mount as its
compiler scratch directory because Meson must execute compiler sanity products.
That mount is executable only inside the already isolated container; VAMC never
executes its products on the host.

The Docker daemon itself is a privileged boundary and must be operated according
to local security policy. The sandbox image must contain Python, NumPy, Numba,
Meson, Ninja, and a Fortran compiler. See
[`sandbox/README.md`](../sandbox/README.md).

Candidate verification, benchmarking, and fallback compilation reuse this
boundary and never substitute host execution. Benchmark evidence must match the
exact migration, normalized cases, verification record, and digest-pinned image.
Compiler-produced fallback files are treated as untrusted: symlinks, non-regular
files, oversized products, and ambiguous extension sets are rejected. Generated
packages do not import or compile a fallback automatically; a caller must review
and explicitly bind it.

## Reports and sensitive data

Reports can contain proprietary paths, hashes, routine names, call names, and
numerical results. JSON outputs are created atomically and default to mode
`0600`. HTML reports escape source-controlled text, use no remote resources or
scripts, and ship a restrictive CSP. Evidence readers reject symlinks, oversized
records, unsupported schemas, duplicate identities, and broken digest linkage.

SHA-256 detects accidental or local evidence substitution but is not a digital
signature. Users needing adversarial provenance must sign and archive the
records externally.

## Repository controls

The public GitHub repository uses protected main-branch rules, pull-request
checks, dependency review, CodeQL, secret scanning, Dependabot, and release
artifact validation. CI analysis and tests do not execute contributor-supplied
Fortran or generated code outside the explicit sandbox workflow.
