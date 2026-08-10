"""A conservative, non-executing Fortran inventory frontend.

This bootstrap milestone extracts a lexical inventory without claiming full
Fortran parsing. An authoritative parser must replace the statement scanner
before any downstream transformation may treat its output as semantic proof.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

from vamc.models import (
    Diagnostic,
    EvidenceStatus,
    LoopDigest,
    LoopPattern,
    ParallelStatus,
    RoutineDigest,
    RoutineKind,
    SideEffects,
    SourceFileDigest,
    SourceForm,
    SupportStatus,
)

_SUBROUTINE_RE = re.compile(
    r"^\s*(?:recursive\s+|pure\s+|elemental\s+)*subroutine\s+"
    r"(?P<name>[a-z_]\w*)\s*(?:\((?P<args>[^)]*)\))?",
    re.IGNORECASE,
)
_FUNCTION_RE = re.compile(
    r"^\s*(?:(?:recursive|pure|elemental|impure|module|non_recursive)\s+)*"
    r"(?:(?:integer|real|double\s+precision|complex|logical|character|type\s*\([^)]*\))"
    r"(?:\s*(?:\([^)]*\)|\*\s*\d+))?\s+)?function\s+"
    r"(?P<name>[a-z_]\w*)\s*(?:\((?P<args>[^)]*)\))?",
    re.IGNORECASE,
)
_PROGRAM_RE = re.compile(r"^\s*program\s+(?P<name>[a-z_]\w*)", re.IGNORECASE)
_END_ROUTINE_RE = re.compile(
    r"^\s*end(?:\s+(?:program|subroutine|function)(?:\s+[a-z_]\w*)?)?\s*$",
    re.IGNORECASE,
)
_CALL_RE = re.compile(r"\bcall\s+([a-z_]\w*(?:\s*%\s*[a-z_]\w*)*)", re.IGNORECASE)
_DO_RE = re.compile(r"^\s*do\s+(?:(?P<label>\d+)\s+)?(?P<variable>[a-z_]\w*)\s*=", re.IGNORECASE)
_END_DO_RE = re.compile(r"^\s*(?:end\s*do|enddo)\b", re.IGNORECASE)
_DECLARATION_RE = re.compile(
    r"^\s*(?:integer|real|double\s+precision|complex|logical|character)"
    r"(?:\s*\([^)]*\)|\s*\*\s*\d+)?\b(?P<remainder>.*)$",
    re.IGNORECASE,
)
_ASSIGNMENT_RE = re.compile(
    r"^\s*(?P<left>[a-z_]\w*(?:\s*\([^=]*\))?)\s*=\s*(?P<right>.+)$",
    re.IGNORECASE,
)

_FIXED_SUFFIXES = {".f", ".for", ".ftn", ".f77"}
_FREE_SUFFIXES = {".f90", ".f95"}
FORTRAN_SUFFIXES = _FIXED_SUFFIXES | _FREE_SUFFIXES


@dataclass
class _Statement:
    line: int
    text: str
    label: str | None = None


@dataclass
class _LoopBuilder:
    start_line: int
    variable: str
    terminal_label: str | None = None
    statements: list[str] = field(default_factory=list)


@dataclass
class _RoutineBuilder:
    name: str
    kind: RoutineKind
    file: str
    start_line: int
    arguments: tuple[str, ...]
    symbols: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    loops: list[LoopDigest] = field(default_factory=list)
    loop_stack: list[_LoopBuilder] = field(default_factory=list)
    unsupported: set[str] = field(default_factory=set)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    filesystem: bool = False
    global_state: bool = False
    stdout: bool = False
    process: bool = False


def source_form_for(path: Path) -> SourceForm:
    suffix = path.suffix.lower()
    if suffix in _FIXED_SUFFIXES:
        return SourceForm.FIXED
    if suffix in _FREE_SUFFIXES:
        return SourceForm.FREE
    raise ValueError(f"unsupported Fortran suffix: {path.suffix}")


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    result: list[str] = []
    index = 0
    while index < len(line):
        character = line[index]
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                if index + 1 < len(line) and line[index + 1] == character:
                    result.extend((character, character))
                    index += 2
                    continue
                quote = None
        if character == "!" and quote is None:
            break
        result.append(character)
        index += 1
    return "".join(result)


def _code_only(text: str) -> str:
    """Mask character literal contents while preserving token positions."""

    quote: str | None = None
    result: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if quote is None and character in {"'", '"'}:
            quote = character
            result.append(" ")
        elif quote is not None:
            result.append(" ")
            if character == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    result.append(" ")
                    index += 1
                else:
                    quote = None
        else:
            result.append(character)
        index += 1
    return "".join(result)


def _split_semicolons(text: str) -> list[str]:
    masked = _code_only(text)
    starts = [0]
    starts.extend(index + 1 for index, character in enumerate(masked) if character == ";")
    ends = [index for index, character in enumerate(masked) if character == ";"]
    ends.append(len(text))
    return [
        text[start:end].strip()
        for start, end in zip(starts, ends, strict=True)
        if text[start:end].strip()
    ]


def _append_statement(
    statements: list[_Statement], statement: _Statement, max_statements: int
) -> None:
    for part in _split_semicolons(statement.text):
        statements.append(_Statement(statement.line, part, statement.label))
        if len(statements) > max_statements:
            raise ValueError("source file exceeds statement-count limit")


def _free_statements(
    lines: Sequence[str], max_statements: int
) -> tuple[list[_Statement], list[Diagnostic]]:
    statements: list[_Statement] = []
    diagnostics: list[Diagnostic] = []
    pending = ""
    start_line = 1
    for number, raw in enumerate(lines, 1):
        text = _strip_inline_comment(raw).strip()
        if not text:
            continue
        if not pending:
            start_line = number
        leading_continuation = text.startswith("&")
        if leading_continuation:
            if not pending:
                diagnostics.append(
                    Diagnostic(
                        "orphan_continuation",
                        "leading continuation marker has no preceding statement",
                        number,
                    )
                )
            text = text[1:].lstrip()
        continued = text.endswith("&")
        if continued:
            text = text[:-1].rstrip()
        pending = f"{pending}{text}".strip()
        if not continued:
            _append_statement(statements, _Statement(start_line, pending), max_statements)
            pending = ""
    if pending:
        diagnostics.append(
            Diagnostic(
                "unterminated_continuation",
                "source ends while a continuation is pending",
                start_line,
            )
        )
        _append_statement(statements, _Statement(start_line, pending), max_statements)
    return statements, diagnostics


def _fixed_statements(
    lines: Sequence[str], max_statements: int
) -> tuple[list[_Statement], list[Diagnostic]]:
    statements: list[_Statement] = []
    diagnostics: list[Diagnostic] = []
    for number, raw in enumerate(lines, 1):
        if not raw:
            continue
        if raw[0] in {"c", "C", "*", "!"}:
            continue
        padded = raw.rstrip("\n")
        continuation = len(padded) > 5 and padded[5] not in {" ", "0"}
        raw_label = padded[:5].strip()
        label = raw_label if raw_label.isdigit() else None
        text = _strip_inline_comment(padded[6:72] if len(padded) > 6 else "").strip()
        if not text:
            continue
        if continuation and statements:
            previous = statements[-1]
            statements[-1] = _Statement(previous.line, f"{previous.text} {text}", previous.label)
        elif continuation:
            diagnostics.append(
                Diagnostic(
                    "orphan_continuation",
                    "fixed-form continuation has no preceding statement",
                    number,
                )
            )
            _append_statement(statements, _Statement(number, text, label), max_statements)
        else:
            _append_statement(statements, _Statement(number, text, label), max_statements)
    return statements, diagnostics


def _parse_arguments(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def _routine_start(statement: str) -> tuple[RoutineKind, str, tuple[str, ...]] | None:
    for regex, kind in (
        (_SUBROUTINE_RE, RoutineKind.SUBROUTINE),
        (_FUNCTION_RE, RoutineKind.FUNCTION),
        (_PROGRAM_RE, RoutineKind.PROGRAM),
    ):
        match = regex.match(statement)
        if match:
            arguments = _parse_arguments(match.groupdict().get("args"))
            return kind, match.group("name").lower(), arguments
    return None


def _declared_symbols(statement: str) -> Iterable[str]:
    match = _DECLARATION_RE.match(statement)
    if not match:
        return ()
    remainder = match.group("remainder")
    names_part = remainder.split("::", 1)[1] if "::" in remainder else remainder
    symbols: list[str] = []
    depth = 0
    current: list[str] = []
    declarations: list[str] = []
    for character in names_part:
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        if character == "," and depth == 0:
            declarations.append("".join(current))
            current = []
        else:
            current.append(character)
    declarations.append("".join(current))
    for raw in declarations:
        name_match = re.match(r"\s*([a-z_]\w*)", raw, re.IGNORECASE)
        if name_match:
            symbols.append(name_match.group(1).lower())
    return symbols


def _classify_loop(loop: _LoopBuilder, end_line: int, loop_id: str) -> LoopDigest:
    statements = [_code_only(statement).lower() for statement in loop.statements]
    joined = "\n".join(statements)
    variable = re.escape(loop.variable.lower())

    if re.search(r"\b(call|read|write|print|open|close|system)\b", joined):
        return LoopDigest(
            loop_id,
            loop.start_line,
            end_line,
            loop.variable,
            LoopPattern.SIDE_EFFECT,
            ParallelStatus.SERIAL,
            "loop contains an observable or unresolved side effect",
        )

    assignments = [match for text in statements if (match := _ASSIGNMENT_RE.match(text))]
    for assignment in assignments:
        left = assignment.group("left").replace(" ", "")
        right = assignment.group("right").replace(" ", "")
        base = left.split("(", 1)[0]
        neighboring_references = re.findall(
            rf"\b([a-z_]\w*)\s*\(\s*{variable}\s*[-+]\s*\d+\s*\)", right
        )
        if base in neighboring_references:
            return LoopDigest(
                loop_id,
                loop.start_line,
                end_line,
                loop.variable,
                LoopPattern.RECURRENCE,
                ParallelStatus.SERIAL,
                "iteration reads a neighboring value written by the loop",
            )
        if neighboring_references:
            return LoopDigest(
                loop_id,
                loop.start_line,
                end_line,
                loop.variable,
                LoopPattern.STENCIL,
                ParallelStatus.UNRESOLVED,
                "neighboring-index reads require alias and boundary analysis",
            )
        scalar_left = "(" not in left
        if scalar_left and re.search(rf"\b{re.escape(base)}\b", right):
            return LoopDigest(
                loop_id,
                loop.start_line,
                end_line,
                loop.variable,
                LoopPattern.REDUCTION,
                ParallelStatus.CONDITIONALLY_SAFE,
                "reduction-shaped update requires explicit numerical and dependency checks",
            )

    if assignments and all(re.search(rf"\({variable}\)", m.group("left")) for m in assignments):
        return LoopDigest(
            loop_id,
            loop.start_line,
            end_line,
            loop.variable,
            LoopPattern.MAP,
            ParallelStatus.UNRESOLVED,
            "map-shaped loop; alias and effects analysis must still prove safety",
        )

    return LoopDigest(
        loop_id,
        loop.start_line,
        end_line,
        loop.variable,
        LoopPattern.UNKNOWN,
        ParallelStatus.SERIAL,
        "insufficient evidence for parallel execution",
    )


def _inspect_statement(
    builder: _RoutineBuilder, statement: _Statement, max_loop_nesting: int
) -> None:
    code = _code_only(statement.text)
    lowered = code.lower()
    builder.symbols.update(_declared_symbols(statement.text))
    calls = {re.sub(r"\s+", "", match.group(1).lower()) for match in _CALL_RE.finditer(code)}
    builder.calls.update(calls)
    if calls:
        builder.unsupported.add("unresolved_external_call")
        builder.diagnostics.append(
            Diagnostic(
                "unresolved_external_call",
                "lexical scanning cannot establish the effects of a call target",
                statement.line,
            )
        )

    if re.search(r"\b(open|close|inquire|rewind|backspace|endfile)\b", lowered):
        builder.filesystem = True
    if re.search(r"\b(read|write)\s*\(\s*(?!\*)", lowered):
        builder.filesystem = True
    if re.search(r"\bprint\b|\bwrite\s*\(\s*\*", lowered):
        builder.stdout = True
    if re.search(r"\b(common|save)\b", lowered):
        builder.global_state = True
    if re.search(r"\bcall\s+(?:system|execute_command_line)\b", lowered):
        builder.process = True
        builder.unsupported.add("process_execution")
    if re.search(r"\bequivalence\b", lowered):
        builder.unsupported.add("equivalence")
    if re.search(r"\bcomputed\s+goto\b|\bgo\s*to\s*\(|\bgoto\s*\(", lowered):
        builder.unsupported.add("computed_goto")

    if _END_DO_RE.match(statement.text):
        if builder.loop_stack:
            loop = builder.loop_stack.pop()
            loop_id = f"L{len(builder.loops) + 1}"
            builder.loops.append(_classify_loop(loop, statement.line, loop_id))
        return

    do_match = _DO_RE.match(statement.text)
    if do_match:
        if len(builder.loop_stack) >= max_loop_nesting:
            raise ValueError("source file exceeds loop-nesting limit")
        builder.loop_stack.append(
            _LoopBuilder(
                statement.line,
                do_match.group("variable").lower(),
                do_match.group("label"),
            )
        )
        return

    for loop in builder.loop_stack:
        loop.statements.append(statement.text)

    if statement.label:
        while builder.loop_stack and builder.loop_stack[-1].terminal_label == statement.label:
            loop = builder.loop_stack.pop()
            builder.loops.append(_classify_loop(loop, statement.line, "pending"))


def _mark_unrecognized(builder: _RoutineBuilder, statement: _Statement) -> None:
    code = _code_only(statement.text)
    known = (
        _DECLARATION_RE.match(code)
        or _ASSIGNMENT_RE.match(code)
        or _CALL_RE.search(code)
        or _DO_RE.match(code)
        or _END_DO_RE.match(code)
        or re.match(
            r"^\s*(?:use|implicit|parameter|dimension|external|intrinsic|data|include|"
            r"if|else|else\s*if|end\s*if|select\s+case|case|end\s*select|where|"
            r"elsewhere|end\s*where|return|continue|cycle|exit|stop|error\s+stop|"
            r"allocate|deallocate|nullify|format|print|read|write|open|close|inquire|"
            r"rewind|backspace|endfile)\b",
            code,
            re.IGNORECASE,
        )
    )
    if not known:
        builder.unsupported.add("unrecognized_statement")
        builder.diagnostics.append(
            Diagnostic(
                "unrecognized_statement",
                "statement is outside the bootstrap scanner's supported subset",
                statement.line,
            )
        )


def _finish_routine(
    builder: _RoutineBuilder, end_line: int, *, missing_terminator: bool = False
) -> RoutineDigest:
    if missing_terminator:
        builder.unsupported.add("unterminated_routine")
        builder.diagnostics.append(
            Diagnostic(
                "unterminated_routine",
                "routine has no matching END statement",
                builder.start_line,
            )
        )
    while builder.loop_stack:
        loop = builder.loop_stack.pop()
        builder.loops.append(_classify_loop(loop, end_line, "pending"))
        builder.unsupported.add("unterminated_do")
        builder.diagnostics.append(
            Diagnostic("unterminated_do", "DO loop has no matching terminator", loop.start_line)
        )
    ordered_loops = sorted(builder.loops, key=lambda item: (item.start_line, item.end_line))
    stable_loops = tuple(
        replace(loop, id=f"L{number}") for number, loop in enumerate(ordered_loops, 1)
    )
    unsupported = tuple(sorted(builder.unsupported))
    return RoutineDigest(
        name=builder.name,
        kind=builder.kind,
        file=builder.file,
        start_line=builder.start_line,
        end_line=end_line,
        arguments=builder.arguments,
        symbols=tuple(sorted(builder.symbols)),
        calls=tuple(sorted(builder.calls)),
        side_effects=SideEffects(
            filesystem=(EvidenceStatus.OBSERVED if builder.filesystem else EvidenceStatus.UNKNOWN),
            network=EvidenceStatus.UNKNOWN,
            global_state=(
                EvidenceStatus.OBSERVED if builder.global_state else EvidenceStatus.UNKNOWN
            ),
            stdout=(EvidenceStatus.OBSERVED if builder.stdout else EvidenceStatus.UNKNOWN),
            process=(EvidenceStatus.OBSERVED if builder.process else EvidenceStatus.UNKNOWN),
        ),
        loops=stable_loops,
        support_status=(
            SupportStatus.REQUIRES_FALLBACK if unsupported else SupportStatus.LEXICALLY_SCANNED
        ),
        unsupported_constructs=unsupported,
        diagnostics=tuple(builder.diagnostics),
    )


def analyze_fortran_source(
    path: Path,
    relative_path: str,
    data: bytes,
    *,
    max_statements: int = 100_000,
    max_loop_nesting: int = 128,
) -> SourceFileDigest:
    """Inventory a Fortran source file without compiling or executing it."""

    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    form = source_form_for(path)
    if form is SourceForm.FIXED:
        statements, file_diagnostics = _fixed_statements(lines, max_statements)
    else:
        statements, file_diagnostics = _free_statements(lines, max_statements)

    routines: list[RoutineDigest] = []
    current: _RoutineBuilder | None = None
    interface_depth = 0
    for statement in statements:
        code = _code_only(statement.text)
        if re.match(r"^\s*(?:abstract\s+)?interface\b", code, re.IGNORECASE):
            interface_depth += 1
            file_diagnostics.append(
                Diagnostic(
                    "interface_not_scanned",
                    "interface bodies are outside the bootstrap scanner's supported subset",
                    statement.line,
                )
            )
            continue
        if interface_depth:
            if re.match(r"^\s*end\s*interface\b", code, re.IGNORECASE):
                interface_depth -= 1
            continue

        start = _routine_start(statement.text)
        if start:
            if current is not None:
                current.unsupported.add("unterminated_routine")
                current.diagnostics.append(
                    Diagnostic(
                        "nested_or_unterminated_routine",
                        "a new routine began before the current routine ended",
                        statement.line,
                    )
                )
                previous_end = max(statement.line - 1, current.start_line)
                routines.append(_finish_routine(current, previous_end, missing_terminator=True))
            kind, name, arguments = start
            current = _RoutineBuilder(name, kind, relative_path, statement.line, arguments)
            continue
        if current is None:
            if not re.match(
                r"^\s*(?:module(?:\s+procedure)?|end\s+module|contains)\b",
                code,
                re.IGNORECASE,
            ):
                file_diagnostics.append(
                    Diagnostic(
                        "unscanned_top_level_statement",
                        "top-level statement was not assigned to a supported program unit",
                        statement.line,
                    )
                )
            continue
        if _END_ROUTINE_RE.match(statement.text):
            routines.append(_finish_routine(current, statement.line))
            current = None
            continue
        if re.match(r"^\s*contains\b", code, re.IGNORECASE):
            current.unsupported.add("contained_procedure")
            current.diagnostics.append(
                Diagnostic(
                    "contained_procedure",
                    "contained procedures require an authoritative parser",
                    statement.line,
                )
            )
            continue
        _mark_unrecognized(current, statement)
        _inspect_statement(current, statement, max_loop_nesting)

    if current is not None:
        routines.append(_finish_routine(current, len(lines), missing_terminator=True))
    if interface_depth:
        file_diagnostics.append(
            Diagnostic(
                "unterminated_interface",
                "INTERFACE block has no matching END INTERFACE",
                len(lines) or 1,
            )
        )
    if not routines:
        file_diagnostics.append(
            Diagnostic(
                "no_supported_program_unit",
                "no supported program, subroutine, or function was discovered",
                1,
            )
        )

    file_fallback = bool(file_diagnostics) or any(
        routine.support_status is SupportStatus.REQUIRES_FALLBACK for routine in routines
    )

    return SourceFileDigest(
        path=relative_path,
        sha256=sha256(data).hexdigest(),
        size_bytes=len(data),
        line_count=len(lines),
        source_form=form,
        routines=tuple(routines),
        support_status=(
            SupportStatus.REQUIRES_FALLBACK if file_fallback else SupportStatus.LEXICALLY_SCANNED
        ),
        diagnostics=tuple(file_diagnostics),
    )
