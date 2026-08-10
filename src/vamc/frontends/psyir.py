"""Authoritative PSyclone/PSyIR adapter for stable VAMC evidence models."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from psyclone.psyir.backend.fortran import FortranWriter  # type: ignore[import-untyped]
from psyclone.psyir.frontend.fortran import FortranReader  # type: ignore[import-untyped]
from psyclone.psyir.nodes import (  # type: ignore[import-untyped]
    ArrayReference,
    Assignment,
    Call,
    CodeBlock,
    IntrinsicCall,
    Loop,
    Node,
    Reference,
    Routine,
)
from psyclone.psyir.symbols import (  # type: ignore[import-untyped]
    ArgumentInterface,
    ArrayType,
    DataSymbol,
)
from psyclone.psyir.tools import DependencyTools  # type: ignore[import-untyped]

from vamc.models import (
    ArgumentAccess,
    DataType,
    Diagnostic,
    LoopDigest,
    LoopPattern,
    ParallelStatus,
    ParserStatus,
    RoutineDigest,
    RoutineKind,
    SideEffects,
    SourceFileDigest,
    SourceForm,
    SupportStatus,
    SymbolDigest,
)

_BOOTSTRAP_FILE_DIAGNOSTICS = {
    "interface_not_scanned",
    "no_supported_program_unit",
    "unscanned_top_level_statement",
}
_BOOTSTRAP_ROUTINE_DIAGNOSTICS = {
    "contained_procedure",
    "nested_or_unterminated_routine",
    "unrecognized_statement",
}
_BOOTSTRAP_UNSUPPORTED = {
    "contained_procedure",
    "unterminated_do",
    "unterminated_routine",
}


class PsyIRResourceLimitError(ValueError):
    """Raised when an authoritative parse exceeds a configured bound."""


def _span_from_ast(ast: Any) -> tuple[int, int] | None:
    """Return the outer source span carried by an fparser node."""

    spans: list[tuple[int, int]] = []
    pending = [ast]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is None or isinstance(current, (str, bytes, int, float, bool)):
            continue
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        item = getattr(current, "item", None)
        span = getattr(item, "span", None)
        if (
            isinstance(span, tuple)
            and len(span) == 2
            and all(isinstance(value, int) for value in span)
        ):
            spans.append((span[0], span[1]))
        children = getattr(current, "children", ())
        if isinstance(children, (tuple, list)):
            pending.extend(children)
    if not spans:
        return None
    return min(start for start, _ in spans), max(end for _, end in spans)


def _node_span(node: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    return _span_from_ast(getattr(node, "ast", None)) or fallback


def _expression_text(expression: Any) -> str:
    try:
        return str(FortranWriter()(expression)).strip()
    except (TypeError, ValueError, AttributeError):
        return "?"


def _data_type(datatype: Any) -> DataType:
    intrinsic = getattr(datatype, "intrinsic", None)
    name = getattr(intrinsic, "name", "")
    return {
        "INTEGER": DataType.INTEGER,
        "REAL": DataType.REAL,
        "BOOLEAN": DataType.LOGICAL,
        "LOGICAL": DataType.LOGICAL,
        "CHARACTER": DataType.CHARACTER,
        "COMPLEX": DataType.COMPLEX,
    }.get(
        name, DataType.DERIVED if type(datatype).__name__ == "DataTypeSymbol" else DataType.UNKNOWN
    )


def _precision(datatype: Any) -> str:
    precision = getattr(datatype, "precision", None)
    if precision is None:
        return "UNKNOWN"
    name = getattr(precision, "name", None)
    if isinstance(name, str):
        return name
    rendered = _expression_text(precision)
    return rendered if rendered != "?" else str(precision)


def _shape(datatype: Any) -> tuple[str, ...]:
    if not isinstance(datatype, ArrayType):
        return ()
    dimensions: list[str] = []
    for dimension in datatype.shape:
        lower = getattr(dimension, "lower", None)
        upper = getattr(dimension, "upper", None)
        if lower is not None and upper is not None:
            dimensions.append(f"{_expression_text(lower)}:{_expression_text(upper)}")
        else:
            name = getattr(dimension, "name", "")
            dimensions.append("*" if name == "ASSUMED_SIZE" else ":")
    return tuple(dimensions)


def _argument_access(symbol: Any) -> ArgumentAccess:
    interface = getattr(symbol, "interface", None)
    if not isinstance(interface, ArgumentInterface):
        return ArgumentAccess.NOT_ARGUMENT
    return {
        "READ": ArgumentAccess.READ,
        "WRITE": ArgumentAccess.WRITE,
        "READWRITE": ArgumentAccess.READWRITE,
    }.get(getattr(interface.access, "name", ""), ArgumentAccess.UNKNOWN)


def _symbol_digest(symbol: Any) -> SymbolDigest:
    datatype = symbol.datatype
    return SymbolDigest(
        name=symbol.name.lower(),
        data_type=_data_type(datatype),
        precision=_precision(datatype),
        rank=len(datatype.shape) if isinstance(datatype, ArrayType) else 0,
        shape=_shape(datatype),
        is_argument=bool(getattr(symbol, "is_argument", False)),
        argument_access=_argument_access(symbol),
        is_constant=bool(getattr(symbol, "is_constant", False)),
    )


def _routine_kind(routine: Any) -> RoutineKind:
    if bool(getattr(routine, "is_program", False)):
        return RoutineKind.PROGRAM
    if getattr(routine, "return_symbol", None) is not None:
        return RoutineKind.FUNCTION
    return RoutineKind.SUBROUTINE


def _classify_loop(
    loop: Any, lexical_pattern: LoopPattern
) -> tuple[LoopPattern, ParallelStatus, str]:
    if loop.walk(CodeBlock):
        return (
            LoopPattern.UNKNOWN,
            ParallelStatus.UNRESOLVED,
            "unsupported IR exists inside the loop; parallelization is disabled",
        )
    if any(not isinstance(call, IntrinsicCall) for call in loop.walk(Call)):
        return (
            LoopPattern.SIDE_EFFECT,
            ParallelStatus.SERIAL,
            "a procedure call has unresolved effects; loop remains serial",
        )

    variable = loop.variable.name.lower()
    pattern = lexical_pattern
    recurrence = False
    stencil = False
    reduction = False
    for assignment in loop.loop_body.walk(Assignment):
        if isinstance(assignment.lhs, Reference) and not isinstance(assignment.lhs, ArrayReference):
            if any(
                reference.name.lower() == assignment.lhs.name.lower()
                for reference in assignment.rhs.walk(Reference)
            ):
                reduction = True
        if isinstance(assignment.lhs, ArrayReference):
            left_indices = tuple(
                _expression_text(item).replace(" ", "").lower() for item in assignment.lhs.indices
            )
            for reference in assignment.rhs.walk(ArrayReference):
                right_indices = tuple(
                    _expression_text(item).replace(" ", "").lower() for item in reference.indices
                )
                shifted = any(variable in item and item != variable for item in right_indices)
                if reference.name.lower() == assignment.lhs.name.lower() and (
                    shifted or right_indices != left_indices
                ):
                    recurrence = True
                elif shifted:
                    stencil = True

    if recurrence:
        return (
            LoopPattern.RECURRENCE,
            ParallelStatus.SERIAL,
            "a loop iteration reads a different element of an array it writes",
        )
    if reduction:
        return (
            LoopPattern.REDUCTION,
            ParallelStatus.CONDITIONALLY_SAFE,
            "explicit scalar reduction detected; numerical reordering requires verification",
        )
    if stencil:
        pattern = LoopPattern.STENCIL
    elif pattern is LoopPattern.UNKNOWN:
        pattern = LoopPattern.MAP

    dependency_tools = DependencyTools()
    try:
        parallel = dependency_tools.can_loop_be_parallelised(loop, test_all_variables=True)
    except (TypeError, KeyError, ValueError, NotImplementedError):
        return (
            pattern,
            ParallelStatus.UNRESOLVED,
            "dependency analysis could not establish loop independence",
        )
    if not parallel:
        return (
            pattern,
            ParallelStatus.SERIAL,
            "dependency analysis found a loop-carried access risk",
        )
    return (
        pattern,
        ParallelStatus.CONDITIONALLY_SAFE,
        "PSyIR dependency analysis found no loop-carried access; standard non-aliasing "
        "assumptions and differential verification remain required",
    )


def _loops(
    routine: Any, lexical: RoutineDigest | None, span: tuple[int, int]
) -> tuple[LoopDigest, ...]:
    lexical_loops = lexical.loops if lexical else ()
    loops: list[LoopDigest] = []
    for index, loop in enumerate(routine.walk(Loop), 1):
        loop_span = _node_span(loop, span)
        if index <= len(lexical_loops):
            hint = lexical_loops[index - 1]
            lexical_pattern = hint.pattern
        else:
            lexical_pattern = LoopPattern.UNKNOWN
        pattern, parallel_status, rationale = _classify_loop(loop, lexical_pattern)
        loops.append(
            LoopDigest(
                id=f"L{index}",
                start_line=loop_span[0],
                end_line=loop_span[1],
                induction_variable=loop.variable.name.lower(),
                pattern=pattern,
                parallel_status=parallel_status,
                rationale=rationale,
            )
        )
    return tuple(loops)


def _routine_digest(
    routine: Any,
    relative_path: str,
    lexical: RoutineDigest | None,
    file_span: tuple[int, int],
) -> RoutineDigest:
    span = _node_span(routine, file_span)
    codeblocks = routine.walk(CodeBlock)
    parser_status = ParserStatus.PARTIAL if codeblocks else ParserStatus.AUTHORITATIVE
    lexical_unsupported = set(lexical.unsupported_constructs if lexical else ())
    lexical_unsupported.difference_update(_BOOTSTRAP_UNSUPPORTED)
    if codeblocks:
        lexical_unsupported.add("psyir_codeblock")
    diagnostics = [
        item
        for item in (lexical.diagnostics if lexical else ())
        if item.code not in _BOOTSTRAP_ROUTINE_DIAGNOSTICS
    ]
    if codeblocks:
        diagnostics.append(
            Diagnostic(
                "psyir_codeblock",
                f"authoritative parser retained {len(codeblocks)} unsupported region(s)",
                span[0],
            )
        )
    symbols = tuple(
        sorted(
            (
                _symbol_digest(symbol)
                for symbol in routine.symbol_table.symbols
                if isinstance(symbol, DataSymbol)
            ),
            key=lambda item: item.name,
        )
    )
    calls = tuple(
        sorted(
            {
                call.routine.name.lower()
                for call in routine.walk(Call)
                if not isinstance(call, IntrinsicCall)
            }
        )
    )
    support = (
        SupportStatus.REQUIRES_FALLBACK
        if lexical_unsupported
        else SupportStatus.AUTHORITATIVELY_PARSED
    )
    return RoutineDigest(
        name=routine.name.lower(),
        kind=_routine_kind(routine),
        file=relative_path,
        start_line=span[0],
        end_line=span[1],
        arguments=tuple(symbol.name.lower() for symbol in routine.symbol_table.argument_list),
        symbols=tuple(item.name for item in symbols),
        calls=calls,
        side_effects=lexical.side_effects if lexical else SideEffects(),
        loops=_loops(routine, lexical, span),
        support_status=support,
        unsupported_constructs=tuple(sorted(lexical_unsupported)),
        diagnostics=tuple(diagnostics),
        parser_status=parser_status,
        symbol_details=symbols,
        ir_node_count=len(routine.walk(Node)),
    )


def _failed_digest(digest: SourceFileDigest) -> SourceFileDigest:
    diagnostic = Diagnostic(
        "authoritative_parse_failed",
        "PSyclone/fparser2 rejected this source; lexical evidence is retained for fallback",
        1,
    )
    routines = tuple(
        replace(
            routine,
            support_status=SupportStatus.REQUIRES_FALLBACK,
            unsupported_constructs=tuple(
                sorted(set(routine.unsupported_constructs) | {"authoritative_parse_failed"})
            ),
            diagnostics=(*routine.diagnostics, diagnostic),
            parser_status=ParserStatus.FAILED,
        )
        for routine in digest.routines
    )
    return replace(
        digest,
        routines=routines,
        support_status=SupportStatus.REQUIRES_FALLBACK,
        diagnostics=(*digest.diagnostics, diagnostic),
        parser_status=ParserStatus.FAILED,
    )


def enrich_with_psyir(
    source: str,
    digest: SourceFileDigest,
    *,
    max_ir_nodes: int,
) -> SourceFileDigest:
    """Parse bounded source into PSyIR and return stable semantic evidence."""

    reader = FortranReader(free_form=digest.source_form is SourceForm.FREE)
    try:
        tree = reader.psyir_from_source(source)
    except Exception:  # PSyclone exposes multiple parser-specific exception classes.
        return _failed_digest(digest)

    node_count = len(tree.walk(Node))
    if node_count > max_ir_nodes:
        raise PsyIRResourceLimitError("PSyIR node count exceeds configured limit")

    lexical_by_name = {routine.name: routine for routine in digest.routines}
    file_span = (1, max(digest.line_count, 1))
    routines = tuple(
        _routine_digest(
            routine,
            digest.path,
            lexical_by_name.get(routine.name.lower()),
            file_span,
        )
        for routine in tree.walk(Routine)
    )
    partial = bool(tree.walk(CodeBlock))
    diagnostics = tuple(
        item for item in digest.diagnostics if item.code not in _BOOTSTRAP_FILE_DIAGNOSTICS
    )
    if not routines:
        diagnostics = (
            *diagnostics,
            Diagnostic(
                "no_executable_routine",
                "source parsed authoritatively but contains no executable routine",
                1,
            ),
        )
    fallback = (
        partial
        or not routines
        or any(routine.support_status is SupportStatus.REQUIRES_FALLBACK for routine in routines)
    )
    return replace(
        digest,
        routines=routines,
        support_status=(
            SupportStatus.REQUIRES_FALLBACK if fallback else SupportStatus.AUTHORITATIVELY_PARSED
        ),
        diagnostics=diagnostics,
        parser_status=ParserStatus.PARTIAL if partial else ParserStatus.AUTHORITATIVE,
        ir_node_count=node_count,
    )
