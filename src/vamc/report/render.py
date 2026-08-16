"""Build deterministic, self-contained modernization reports."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vamc.analysis.inventory import AnalysisError
from vamc.benchmark.runner import _document_digest, _read_json
from vamc.verify.static import (
    _load_migration_directory,
    manifest_digest,
    verify_migration_directory,
)

_MAX_REPORT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ReportBundle:
    """Machine-readable evidence and its self-contained HTML rendering."""

    document: dict[str, Any]
    json_text: str
    html_text: str


def _decode_object(content: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise AnalysisError(f"{name} is not valid bounded JSON") from error
    if not isinstance(value, dict):
        raise AnalysisError(f"{name} must be a JSON object")
    return value


def _evidence(
    path: str | Path | None,
    *,
    name: str,
    migration_sha256: str,
) -> dict[str, Any] | None:
    if path is None:
        return None
    value = _read_json(Path(path).expanduser())
    if value.get("migration_sha256") != migration_sha256:
        raise AnalysisError(f"{name} evidence does not match this migration")
    return value


def _validate_analysis(value: dict[str, Any]) -> None:
    files = value.get("files")
    if value.get("schema_version") != "0.3.0" or not isinstance(files, list):
        raise AnalysisError("analysis evidence schema is not supported")
    for source in files:
        if not isinstance(source, dict) or not isinstance(source.get("routines"), list):
            raise AnalysisError("analysis evidence contains an invalid routine inventory")
        for routine in source["routines"]:
            if not isinstance(routine, dict) or not isinstance(routine.get("loops"), list):
                raise AnalysisError("analysis evidence contains an invalid loop inventory")


def _cell(value: object) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def _join_strings(value: object) -> str:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return "invalid record"
    return ", ".join(value)


def _table(headers: tuple[str, ...], rows: Sequence[tuple[object, ...]]) -> str:
    heading = "".join(f'<th scope="col">{_cell(item)}</th>' for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell(item)}</td>" for item in row) + "</tr>" for row in rows
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">No records.</td></tr>'
    return f"<table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table>"


def _render_html(document: dict[str, Any]) -> str:
    analysis = document["analysis"]
    migration = document["migration"]
    verification = document["verification"]
    benchmark = document.get("benchmark")

    support_rows = [
        (
            item.get("source_file"),
            item.get("routine"),
            item.get("status"),
            _join_strings(item.get("fallback_reasons")),
        )
        for item in migration.get("routines", [])
        if isinstance(item, dict)
    ]
    loop_rows: list[tuple[object, ...]] = []
    for source in analysis.get("files", []):
        if not isinstance(source, dict):
            continue
        for routine in source.get("routines", []):
            if not isinstance(routine, dict):
                continue
            for loop in routine.get("loops", []):
                if isinstance(loop, dict):
                    loop_rows.append(
                        (
                            source.get("path"),
                            routine.get("name"),
                            loop.get("id"),
                            loop.get("pattern"),
                            loop.get("parallel_status"),
                            loop.get("rationale"),
                        )
                    )
    routine_evidence = {
        item.get("routine"): item
        for item in verification.get("routines", [])
        if isinstance(item, dict)
    }
    verification_rows: list[tuple[object, ...]] = []
    for item in routine_evidence.values():
        metrics = item.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        verification_rows.append(
            (
                item.get("routine"),
                item.get("status"),
                item.get("cases"),
                metrics.get("max_absolute_error"),
                metrics.get("max_relative_error"),
                _join_strings(item.get("diagnostics")),
            )
        )
    candidate_evidence = {
        item.get("candidate_id"): item
        for item in verification.get("candidates", [])
        if isinstance(item, dict)
    }
    measurements = {
        item.get("implementation_id"): item
        for item in (benchmark or {}).get("measurements", [])
        if isinstance(item, dict)
    }
    selected = {
        item.get("routine"): item.get("candidate_id")
        for item in (benchmark or {}).get("selections", [])
        if isinstance(item, dict)
    }
    candidate_rows = []
    for item in migration.get("candidates", []):
        if not isinstance(item, dict):
            continue
        identity = item.get("id")
        evidence = candidate_evidence.get(identity, {})
        timing = measurements.get(identity, {})
        candidate_rows.append(
            (
                identity,
                item.get("routine"),
                item.get("backend"),
                evidence.get("status", item.get("status")),
                timing.get("median_ns"),
                "yes" if selected.get(item.get("routine")) == identity else "no",
            )
        )
    source_map_rows = [
        (
            item.get("routine"),
            f"{item.get('source_file')}:{item.get('source_start_line')}",
            f"{item.get('generated_file')}:{item.get('generated_start_line')}",
        )
        for item in migration.get("source_maps", [])
        if isinstance(item, dict)
    ]
    summary = migration.get("summary", {})
    sandbox = verification.get("sandbox")
    image = verification.get("sandbox_image") or "not used"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline';
               base-uri 'none'; form-action 'none'">
<title>VAMC modernization report</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;max-width:1200px;margin:auto;padding:2rem;color:#172033}}
h1,h2{{line-height:1.2}} .summary{{display:flex;gap:1rem;flex-wrap:wrap}}
.card{{border:1px solid #ccd3df;border-radius:.5rem;padding:1rem;min-width:10rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0 2rem}}
th,td{{border:1px solid #ccd3df;padding:.5rem;text-align:left;vertical-align:top}}
th{{background:#f2f5f9}} code{{overflow-wrap:anywhere}}
.notice{{background:#fff7d6;padding:1rem;border-left:4px solid #d49b00}}
</style>
</head>
<body>
<h1>VAMC modernization report</h1>
<p>Deterministic evidence bundle for migration
<code>{_cell(document["migration_sha256"])}</code>.</p>
<div class="summary">
<div class="card"><strong>{_cell(summary.get("routines"))}</strong><br>routines</div>
<div class="card"><strong>{_cell(summary.get("translated_routines"))}</strong><br>translated</div>
<div class="card"><strong>{_cell(summary.get("fallback_routines"))}</strong>
<br>fallback required</div>
<div class="card"><strong>{_cell(verification.get("status"))}</strong><br>verification status</div>
</div>
<p class="notice"><strong>Scope:</strong> differential verification, when present,
applies only to the recorded cases and numerical policy. It is not a formal proof.
Generated and original code remain untrusted.</p>
<h2>Routine support matrix</h2>
{_table(("Source", "Routine", "Translation", "Fallback reasons"), support_rows)}
<h2>Loop classifications</h2>
{_table(("Source", "Routine", "Loop", "Pattern", "Parallel status", "Rationale"), loop_rows)}
<h2>Verification</h2>
<p>Boundary: {_cell(sandbox)}<br>Image: <code>{_cell(image)}</code></p>
{
        _table(
            ("Routine", "Status", "Cases", "Max abs error", "Max relative error", "Diagnostics"),
            verification_rows,
        )
    }
<h2>Optimization candidates</h2>
{_table(("Candidate", "Routine", "Backend", "Acceptance", "Median ns", "Selected"), candidate_rows)}
<h2>Source mappings</h2>
{_table(("Routine", "Original", "Generated"), source_map_rows)}
<h2>Provenance</h2>
{
        _table(
            ("Record", "SHA-256"),
            [
                ("migration", document["migration_sha256"]),
                ("verification", document["verification_sha256"]),
                ("benchmark", document.get("benchmark_sha256")),
            ],
        )
    }
</body>
</html>
"""


def build_report(
    migration_path: str | Path,
    *,
    verification_path: str | Path | None = None,
    benchmark_path: str | Path | None = None,
) -> ReportBundle:
    """Validate and combine migration, verification, and benchmark evidence."""

    migration_root = Path(migration_path).expanduser()
    manifest, contents = _load_migration_directory(migration_root)
    static = verify_migration_directory(migration_root)
    if static.summary.failed:
        raise AnalysisError("report generation refused because migration integrity failed")
    migration_sha256 = manifest_digest(manifest)
    analysis_content = contents.get("analysis.json")
    if analysis_content is None:
        raise AnalysisError("migration has no analysis evidence")
    analysis = _decode_object(analysis_content, "analysis.json")
    _validate_analysis(analysis)
    if not isinstance(manifest.get("summary"), dict):
        raise AnalysisError("migration summary is invalid")
    verification = (
        _evidence(
            verification_path,
            name="verification",
            migration_sha256=migration_sha256,
        )
        or static.to_dict()
    )
    if verification.get("schema_version") != "0.2.0":
        raise AnalysisError("verification evidence schema is not supported")
    if not isinstance(verification.get("routines"), list) or not isinstance(
        verification.get("candidates"), list
    ):
        raise AnalysisError("verification evidence record inventory is invalid")
    verification_sha256 = _document_digest(verification)
    benchmark = _evidence(
        benchmark_path,
        name="benchmark",
        migration_sha256=migration_sha256,
    )
    if benchmark is not None:
        if verification_path is None:
            raise AnalysisError("benchmark reports require the matching verification evidence")
        if benchmark.get("schema_version") != "0.1.0":
            raise AnalysisError("benchmark evidence schema is not supported")
        if not isinstance(benchmark.get("measurements"), list) or not isinstance(
            benchmark.get("selections"), list
        ):
            raise AnalysisError("benchmark evidence record inventory is invalid")
        if benchmark.get("verification_sha256") != verification_sha256:
            raise AnalysisError("benchmark evidence does not match the verification record")
        if benchmark.get("cases_sha256") != verification.get("cases_sha256"):
            raise AnalysisError("benchmark and verification case evidence do not match")
        if benchmark.get("sandbox_image") != verification.get("sandbox_image"):
            raise AnalysisError("benchmark and verification sandbox images do not match")
    document: dict[str, Any] = {
        "schema_version": "0.1.0",
        "migration_sha256": migration_sha256,
        "verification_sha256": verification_sha256,
        "benchmark_sha256": _document_digest(benchmark) if benchmark is not None else None,
        "analysis": analysis,
        "migration": manifest,
        "verification": verification,
        "benchmark": benchmark,
    }
    json_text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    html_text = _render_html(document)
    if max(len(json_text.encode("utf-8")), len(html_text.encode("utf-8"))) > _MAX_REPORT_BYTES:
        raise AnalysisError("rendered modernization report exceeds its size limit")
    return ReportBundle(document=document, json_text=json_text, html_text=html_text)
