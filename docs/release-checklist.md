# Release checklist

The repository is public experimental pre-alpha software. Publishing a package
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

## Product work that remains intentionally out of scope

- Replace the lexical scanner with an authoritative Fortran frontend.
- Implement serial translation, native-Fortran oracle execution in a hardened
  sandbox, differential verification, dependency analysis, and only then
  parallel/optimized candidates.
- Add a representative Fortran golden corpus and parser-differential tests.

Until those product stages exist, no output may claim translated, verified, or
parallel-safe code.
