"""Stable, serializable analysis models."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, cast


class SourceForm(str, Enum):
    FIXED = "fixed"
    FREE = "free"


class RoutineKind(str, Enum):
    PROGRAM = "program"
    SUBROUTINE = "subroutine"
    FUNCTION = "function"


class SupportStatus(str, Enum):
    ANALYZED = "ANALYZED"
    REQUIRES_FALLBACK = "REQUIRES_FALLBACK"


class LoopPattern(str, Enum):
    MAP = "MAP"
    REDUCTION = "REDUCTION"
    STENCIL = "STENCIL"
    RECURRENCE = "RECURRENCE"
    SIDE_EFFECT = "SIDE_EFFECT"
    UNKNOWN = "UNKNOWN"


class ParallelStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    CONDITIONALLY_SAFE = "CONDITIONALLY_SAFE"
    SERIAL = "SERIAL"


@dataclass(frozen=True)
class SideEffects:
    filesystem: bool = False
    network: bool = False
    global_state: bool = False
    stdout: bool = False
    process: bool = False


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


@dataclass(frozen=True)
class SourceFileDigest:
    path: str
    sha256: str
    size_bytes: int
    line_count: int
    source_form: SourceForm
    routines: tuple[RoutineDigest, ...]


@dataclass(frozen=True)
class AnalysisSummary:
    files: int
    routines: int
    loops: int
    calls: int
    fallback_routines: int


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
    files: tuple[SourceFileDigest, ...]
    summary: AnalysisSummary

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return cast(dict[str, Any], _jsonable(asdict(self)))
