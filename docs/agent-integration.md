# Agent integration

VAMC includes an installable agent skill and a read-only Model Context Protocol
(MCP) server. The integration helps an agent choose the safe VAMC workflow and
inspect analysis or evidence without silently running native code.

## Install from a clone

Set up VAMC first so the MCP server can use a supported Python environment:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
export VAMC_PYTHON="$PWD/.venv/bin/python"
```

Then register the GitHub marketplace and install the plugin:

```bash
codex plugin marketplace add YashM1503/vamc --ref main
codex plugin add vamc-agent@vamc-tools
```

For local development, replace `YashM1503/vamc --ref main` with the absolute
path to the clone.

Restart the client after installation. The plugin includes the
`modernize-fortran-with-vamc` skill. It uses `VAMC_PYTHON` when set, then looks
for a repository `.venv`, `vamc-mcp` on `PATH`, or an installed VAMC package in
Python 3.11 through 3.14. The explicit variable is the most predictable choice
for a cached GitHub plugin.

## Read-only MCP tools

| Tool | Purpose | Executes project code? |
| --- | --- | --- |
| `vamc_analyze` | Analyze a Fortran file or directory. | No |
| `vamc_verify_static` | Check migration paths, hashes, manifests, and syntax. | No |
| `vamc_build_report` | Render a report from existing migration and evidence artifacts. | No |

The MCP server deliberately does not expose migration writes, native
verification, benchmarking, or fallback compilation. Use the documented CLI
for those explicit operations. Native stages still require reviewed cases and a
digest-pinned sandbox image; there is no host fallback.

## Verify the package

Run the repository test and validation commands before publishing:

```bash
pytest tests/integration/test_agent_plugin.py
ruff check .
python -m build
```
