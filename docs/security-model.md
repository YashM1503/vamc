# Security model

VAMC treats original source, generated code, compiler output, reports, and
benchmark results as untrusted.

## Implemented in the Understand milestone

- Analysis never compiles, imports, or executes Fortran.
- Directory traversal does not follow symbolic links.
- Explicit symbolic-link input roots are rejected.
- Per-file and per-project file-count limits bound common resource attacks.
- Hidden, VCS, dependency, build, and cache directories are excluded by default.
- Invalid UTF-8 and unsupported input types fail explicitly.

## Required before source execution

Compilation and execution will default to a rootless Docker/Podman sandbox with
no network, no host credentials, a read-only base filesystem, a private scratch
directory, a non-root user, dropped capabilities, no-new-privileges, and CPU,
memory, PID, file-size, disk, and time limits. Host execution will require an
explicit noisy opt-in.

Generated HTML will be static, escaped, and free of remote resources and
third-party scripts.

The CodeQL workflow is present but gated by a repository variable named
`CODEQL_ENABLED`. Set it to `true` after GitHub code scanning is enabled for the
private repository; this avoids a permanently failing workflow on plans without
GitHub Advanced Security.
