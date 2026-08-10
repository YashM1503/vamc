# Security policy

## Supported versions

VAMC is pre-alpha. Only the latest commit on `main` receives security fixes;
there is no supported package release yet.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. If that path
is unavailable, contact the repository owner privately through GitHub before
sharing exploit details. Do not open a public issue, attach secrets, or test a
report against systems or source trees you do not own.

We aim to acknowledge a report within 3 business days, provide an initial
assessment within 10 business days, and coordinate disclosure after a fix is
available. These are response targets, not guarantees for this volunteer alpha.

The `analyze` command must never execute Fortran. Treat source execution,
reading outside the selected source root, following source symlinks, resource
limit bypass, report-path clobbering, or a false claim of verified safety as a
security defect.

## Scope

Reports, source trees, and paths are untrusted. Generated-code execution is not
implemented. When it is added, it will not be considered supported until the
sandbox described in `docs/security-model.md` is implemented and reviewed.
