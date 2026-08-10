"""Stable, serializable analysis models."""

from dataclasses import asdict, dataclass
from enum import Enum, StrEnum
from typing import Any, cast


class SourceForm(StrEnum):
    FIXED = "fixed"
    FREE = "free"


class RoutineKind(StrEnum):
    PROGRAM = "program"
    SUBROUTINE = "subroutine"
    FUNCTION = "function"


class SupportStatus(StrEnum):
    LEXICALLY_SCANNED = "LEXICALLY_SCANNED"
    REQUIRES_FALLBACK = "REQUIRES_FALLBACK"


class EvidenceStatus(StrEnum):
    OBSERVED = "OBSERVED"
    UNKNOWN = "UNKNOWN"


class LoopPattern(StrEnum):
    MAP = "MAP"
    REDUCTION = "REDUCTION"
    STENCIL = "STENCIL"
    RECURRENCE = "RECURRENCE"
    SIDE_EFFECT = "SIDE_EFFECT"
    UNKNOWN = "UNKNOWN"


class ParallelStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    CONDITIONALLY_SAFE = "CONDITIONALLY_SAFE"
    SERIAL = "SERIAL"


@dataclass(frozen=True)
class SideEffects:
    """Lexical evidence, never proof that an effect is absent."""

    filesystem: EvidenceStatus = EvidenceStatus.UNKNOWN
    network: EvidenceStatus = EvidenceStatus.UNKNOWN
    global_state: EvidenceStatus = EvidenceStatus.UNKNOWN
    stdout: EvidenceStatus = EvidenceStatus.UNKNOWN
    process: EvidenceStatus = EvidenceStatus.UNKNOWN


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    line: int


@dataclass(frozen=True)
class LoopDigest:
    id: str
    start_line: int
    end_line: int
    induction_variable: str
    pattern: LoopPattern
    parallel_status: ParallelStatus
    rationale: str


@dataclass(frozen=True)
class RoutineDigest:
    name: str
    kind: RoutineKind
    file: str
    start_line: int
    end_line: int
    arguments: tuple[str, ...]
    symbols: tuple[str, ...]
    calls: tuple[str, ...]
    side_effects: SideEffects
    loops: tuple[LoopDigest, ...]
    support_status: SupportStatus
    unsupported_constructs: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class SourceFileDigest:
    path: str
    sha256: str
    size_bytes: int
    line_count: int
    source_form: SourceForm
    routines: tuple[RoutineDigest, ...]
    support_status: SupportStatus
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class AnalysisSummary:
    files: int
    routines: int
    loops: int
    calls: int
    fallback_routines: int
    fallback_files: int
    diagnostics: int


@dataclass(frozen=True)
class AnalysisLimits:
    max_file_bytes: int
    max_total_bytes: int
    max_files: int
    max_lines_per_file: int
    max_line_bytes: int
    max_statements_per_file: int
    max_loop_nesting: int
    include_hidden: bool


@dataclass(frozen=True)
class AnalysisProvenance:
    tool_version: str
    frontend: str
    limits: AnalysisLimits


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class AnalysisResult:
    schema_version: str
    source_root: str
    provenance: AnalysisProvenance
    files: tuple[SourceFileDigest, ...]
    summary: AnalysisSummary

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return cast(dict[str, Any], _jsonable(asdict(self)))
