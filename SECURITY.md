# Security policy

VAMC is pre-alpha and has not yet shipped a sandboxed execution runtime.

Please report suspected vulnerabilities privately through GitHub Security
Advisories after the repository is available. Do not include secrets or active
exploit payloads in a public issue.

The current `analyze` command is designed not to execute source code. Treat any
behavior that executes analyzed input, follows a source-tree symlink, or reads
outside the requested tree as a security defect.
