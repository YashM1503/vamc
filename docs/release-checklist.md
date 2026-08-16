# Release checklist

The repository is public experimental alpha software. Publishing a package
is a separate, later decision.

## Public repository record (2026-08-10)

- [x] Preserve the original repository and pull-request record in a private
  archive.
- [x] Create the public repository from a sanitized, GitHub-noreply-only history.
- [x] Review and merge the hardening changes through a passing pull request.
- [x] Confirm the README, license, citation, security policy, and support scope.
- [x] Enable the dependency graph, Dependabot alerts/security updates, secret
  scanning, push protection, and private vulnerability reporting.
- [x] Create the `main` ruleset: require CI and
  Security checks, resolved conversations, and block force-pushes and deletion.
- [x] Run CodeQL manually with `CODEQL_ENABLED=true` and
  confirm a successful result.
- [ ] Verify the private vulnerability reporting link from a non-owner account.

## Package release gate

- [ ] Complete a second security review of the merged public commit.
- [ ] Add a tag-protected, OIDC trusted-publishing workflow with an approval
  environment, artifact attestations, checksums, and version/tag validation.
- [ ] Install and test the built wheel on every supported Python version.
- [ ] Create a matching changelog section, CFF version/date, signed tag, and
  GitHub release. Do not publish from a developer token.

## Scoped MVP record

- [x] Authoritative PSyclone/fparser2 frontend and bounded semantic inventory.
- [x] Deterministic serial translation, source maps, and fail-closed dependency analysis.
- [x] Hardened container-only F2PY oracle and candidate-specific verification.
- [x] Verified-only benchmark ranking with environment and raw-sample evidence.
- [x] Explicit compiled fallback bridge and deterministic JSON/HTML reports.
- [x] Public seed corpus and parser/property/security regression tests.

Before a stable package release, expand the real-world corpus, run the live
native matrix on each supported deployment architecture, commission an
independent sandbox review, define schema compatibility policy, and complete the
unchecked package release gates above. Domain-scoped verification must never be
presented as formal or universal correctness.
