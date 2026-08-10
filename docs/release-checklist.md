# Public release checklist

The repository may be opened as experimental pre-alpha software only after all
items in the visibility gate are complete. Publishing a package is a separate,
later decision.

## Visibility gate

- [ ] Decide whether the email address in commit `408b925` may become public;
  rewrite the commit to a GitHub noreply address first if not.
- [ ] Review and merge the hardening changes through a passing pull request.
- [ ] Confirm the README, license, citation, security policy, and support scope.
- [ ] Change visibility to public.
- [ ] Recreate the `main` ruleset after the visibility change: require CI and
  Security checks, resolved conversations, and block force-pushes and deletion.
- [ ] Enable the dependency graph, Dependabot alerts/security updates, secret
  scanning, push protection, private vulnerability reporting, and CodeQL.
- [ ] Set repository variable `CODEQL_ENABLED=true`, run CodeQL manually, and
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
