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
    AUTHORITATIVELY_PARSED = "AUTHORITATIVELY_PARSED"
    REQUIRES_FALLBACK = "REQUIRES_FALLBACK"


class ParserStatus(StrEnum):
    LEXICAL_ONLY = "LEXICAL_ONLY"
    AUTHORITATIVE = "AUTHORITATIVE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DataType(StrEnum):
    INTEGER = "INTEGER"
    REAL = "REAL"
    LOGICAL = "LOGICAL"
    CHARACTER = "CHARACTER"
    COMPLEX = "COMPLEX"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"


class ArgumentAccess(StrEnum):
    NOT_ARGUMENT = "NOT_ARGUMENT"
    READ = "READ"
    WRITE = "WRITE"
    READWRITE = "READWRITE"
    UNKNOWN = "UNKNOWN"


class CallResolution(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


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


class TranslationStatus(StrEnum):
    TRANSLATED = "TRANSLATED"
    FALLBACK_REQUIRED = "FALLBACK_REQUIRED"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    STATICALLY_CHECKED = "STATICALLY_CHECKED"
    VERIFIED_FOR_TEST_DOMAIN = "VERIFIED_FOR_TEST_DOMAIN"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class CandidateBackend(StrEnum):
    SERIAL_PYTHON = "SERIAL_PYTHON"
    NUMPY = "NUMPY"
    NUMBA_SERIAL = "NUMBA_SERIAL"
    NUMBA_PARALLEL = "NUMBA_PARALLEL"


class CandidateStatus(StrEnum):
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


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
class SymbolDigest:
    name: str
    data_type: DataType
    precision: str
    rank: int
    shape: tuple[str, ...]
    is_argument: bool
    argument_access: ArgumentAccess
    is_constant: bool


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
    parser_status: ParserStatus = ParserStatus.LEXICAL_ONLY
    symbol_details: tuple[SymbolDigest, ...] = ()
    ir_node_count: int = 0


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
    parser_status: ParserStatus = ParserStatus.LEXICAL_ONLY
    ir_node_count: int = 0


@dataclass(frozen=True)
class CallGraphEdge:
    caller_file: str
    caller_routine: str
    callee: str
    resolution: CallResolution
    target_file: str | None = None
    target_routine: str | None = None


@dataclass(frozen=True)
class AnalysisSummary:
    files: int
    routines: int
    loops: int
    calls: int
    fallback_routines: int
    fallback_files: int
    diagnostics: int
    authoritative_files: int = 0
    partial_files: int = 0
    resolved_calls: int = 0
    unresolved_calls: int = 0
    ambiguous_calls: int = 0


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
    max_ir_nodes_per_file: int = 250_000


@dataclass(frozen=True)
class AnalysisProvenance:
    tool_version: str
    frontend: str
    limits: AnalysisLimits
    authoritative_frontend: str | None = None


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
    call_graph: tuple[CallGraphEdge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True)
class SourceMapEntry:
    source_file: str
    source_start_line: int
    source_end_line: int
    generated_file: str
    generated_start_line: int
    generated_end_line: int
    routine: str


@dataclass(frozen=True)
class RoutineTranslation:
    source_file: str
    routine: str
    status: TranslationStatus
    generated_file: str | None
    fallback_reasons: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedArtifact:
    """One deterministic output artifact held in memory until explicitly written."""

    path: str
    content: str
    sha256: str


@dataclass(frozen=True)
class ArtifactDigest:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class CandidateRecord:
    id: str
    parent: str
    source_file: str
    routine: str
    backend: CandidateBackend
    generated_file: str
    transforms: tuple[str, ...]
    preconditions: tuple[str, ...]
    status: CandidateStatus


@dataclass(frozen=True)
class MigrationSummary:
    files: int
    routines: int
    translated_routines: int
    fallback_routines: int


@dataclass(frozen=True)
class MigrationManifest:
    schema_version: str
    generator_version: str
    source_root: str
    target: str
    package_name: str
    analysis_schema_version: str
    artifacts: tuple[ArtifactDigest, ...]
    candidates: tuple[CandidateRecord, ...]
    source_maps: tuple[SourceMapEntry, ...]
    routines: tuple[RoutineTranslation, ...]
    summary: MigrationSummary

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation without generated source bodies."""

        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True)
class NumericalPolicy:
    name: str
    relative_tolerance: float
    absolute_tolerance: float
    equal_nan: bool = True


@dataclass(frozen=True)
class ComparisonMetrics:
    equal: bool
    compared_values: int
    max_absolute_error: float
    max_relative_error: float
    nan_mismatches: int
    infinity_mismatches: int
    structural_mismatches: int


@dataclass(frozen=True)
class RoutineVerification:
    routine: str
    status: VerificationStatus
    cases: int
    policy: NumericalPolicy
    metrics: ComparisonMetrics
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class CandidateVerification:
    candidate_id: str
    routine: str
    backend: CandidateBackend
    status: VerificationStatus
    cases: int
    policy: NumericalPolicy
    metrics: ComparisonMetrics
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class VerificationSummary:
    routines: int
    statically_checked: int
    verified_for_test_domain: int
    failed: int
    unavailable: int
    candidates_statically_checked: int = 0
    candidates_verified: int = 0
    candidates_rejected: int = 0
    candidates_unavailable: int = 0


@dataclass(frozen=True)
class VerificationReport:
    schema_version: str
    migration_schema_version: str
    migration_sha256: str
    cases_sha256: str | None
    status: VerificationStatus
    sandbox: str
    sandbox_image: str | None
    routines: tuple[RoutineVerification, ...]
    summary: VerificationSummary
    candidates: tuple[CandidateVerification, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible verification record."""

        return cast(dict[str, Any], _jsonable(asdict(self)))


class BenchmarkStatus(StrEnum):
    BENCHMARKED = "BENCHMARKED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class BenchmarkMeasurement:
    implementation_id: str
    routine: str
    backend: CandidateBackend
    status: BenchmarkStatus
    samples_ns: tuple[int, ...]
    median_ns: int | None
    minimum_ns: int | None
    maximum_ns: int | None
    relative_to_serial: float | None
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkSelection:
    routine: str
    candidate_id: str
    backend: CandidateBackend
    speedup_over_serial: float


@dataclass(frozen=True)
class BenchmarkEnvironment:
    python: str
    platform: str
    machine: str
    numpy: str
    numba: str


@dataclass(frozen=True)
class BenchmarkSummary:
    routines: int
    eligible_candidates: int
    benchmarked_candidates: int
    unavailable_candidates: int


@dataclass(frozen=True)
class BenchmarkReport:
    schema_version: str
    migration_sha256: str
    verification_sha256: str
    cases_sha256: str
    sandbox_image: str
    warmups: int
    repeats: int
    iterations: int
    environment: BenchmarkEnvironment | None
    measurements: tuple[BenchmarkMeasurement, ...]
    selections: tuple[BenchmarkSelection, ...]
    summary: BenchmarkSummary

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible benchmark record."""

        return cast(dict[str, Any], _jsonable(asdict(self)))


class FallbackBuildStatus(StrEnum):
    BUILT = "BUILT"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class FallbackBuildReport:
    schema_version: str
    migration_sha256: str
    sandbox_image: str
    module_name: str
    status: FallbackBuildStatus
    artifact: str | None
    artifact_sha256: str | None
    artifact_size_bytes: int | None
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible fallback build record."""

        return cast(dict[str, Any], _jsonable(asdict(self)))
