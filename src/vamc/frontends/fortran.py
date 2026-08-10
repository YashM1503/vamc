"""A conservative, non-executing Fortran inventory frontend.

This first milestone intentionally extracts a semantic inventory without
claiming full Fortran parsing. PSyclone/PSyIR will replace the statement
scanner as the authoritative frontend in the next milestone.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Optional

from vamc.models import (
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
    r"^\s*(?:(?:recursive|pure|elemental)\s+)*(?:(?:integer|real|double\s+precision|"
    r"complex|logical|character(?:\s*\([^)]*\))?)\s+)?function\s+"
    r"(?P<name>[a-z_]\w*)\s*(?:\((?P<args>[^)]*)\))?",
    re.IGNORECASE,
)
_PROGRAM_RE = re.compile(r"^\s*program\s+(?P<name>[a-z_]\w*)", re.IGNORECASE)
_END_ROUTINE_RE = re.compile(
    r"^\s*end(?:\s+(?:program|subroutine|function)(?:\s+[a-z_]\w*)?)?\s*$",
    re.IGNORECASE,
)
_CALL_RE = re.compile(r"\bcall\s+([a-z_]\w*)", re.IGNORECASE)
_DO_RE = re.compile(r"^\s*do\s+(?:\d+\s+)?(?P<variable>[a-z_]\w*)\s*=", re.IGNORECASE)
_END_DO_RE = re.compile(r"^\s*(?:end\s*do|enddo)\b", re.IGNORECASE)
_DECLARATION_RE = re.compile(
    r"^\s*(?:integer|real|double\s+precision|complex|logical|character)"
    r"(?:\s*\([^)]*\)|\s*\*\s*\d+)?(?P<remainder>.*)$",
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


@dataclass
class _LoopBuilder:
    start_line: int
    variable: str
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
    filesystem: bool = False
    network: bool = False
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
    quote: Optional[str] = None
    result: list[str] = []
    for character in line:
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        if character == "!" and quote is None:
            break
        result.append(character)
    return "".join(result)


def _free_statements(lines: Sequence[str]) -> list[_Statement]:
    statements: list[_Statement] = []
    pending = ""
    start_line = 1
    for number, raw in enumerate(lines, 1):
        text = _strip_inline_comment(raw).strip()
        if not text:
            continue
        if not pending:
            start_line = number
        if text.startswith("&"):
            text = text[1:].lstrip()
        continued = text.endswith("&")
        if continued:
            text = text[:-1].rstrip()
        pending = f"{pending} {text}".strip()
        if not continued:
            statements.append(_Statement(start_line, pending))
            pending = ""
    if pending:
        statements.append(_Statement(start_line, pending))
    return statements


def _fixed_statements(lines: Sequence[str]) -> list[_Statement]:
    statements: list[_Statement] = []
    for number, raw in enumerate(lines, 1):
        if not raw:
            continue
        if raw[0] in {"c", "C", "*", "!"}:
            continue
        padded = raw.rstrip("\n")
        continuation = len(padded) > 5 and padded[5] not in {" ", "0"}
        text = _strip_inline_comment(padded[6:72] if len(padded) > 6 else "").strip()
        if not text:
            continue
        if continuation and statements:
            previous = statements[-1]
            statements[-1] = _Statement(previous.line, f"{previous.text} {text}")
        else:
            statements.append(_Statement(number, text))
    return statements


def _parse_arguments(raw: Optional[str]) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def _routine_start(statement: str) -> Optional[tuple[RoutineKind, str, tuple[str, ...]]]:
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
    statements = [statement.lower() for statement in loop.statements]
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
        if re.search(rf"\({variable}\s*[-+]\s*1\)", right) and base in right:
            return LoopDigest(
                loop_id,
                loop.start_line,
                end_line,
                loop.variable,
                LoopPattern.RECURRENCE,
                ParallelStatus.SERIAL,
                "iteration reads a neighboring value written by the loop",
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


def _inspect_statement(builder: _RoutineBuilder, statement: _Statement) -> None:
    lowered = statement.text.lower()
    builder.symbols.update(_declared_symbols(statement.text))
    builder.calls.update(match.group(1).lower() for match in _CALL_RE.finditer(statement.text))

    if re.search(r"\b(open|close|inquire|rewind|backspace|endfile)\b", lowered):
        builder.filesystem = True
    if re.search(r"\b(read|write)\s*\(\s*(?!\*)", lowered):
        builder.filesystem = True
    if re.search(r"\bprint\b|\bwrite\s*\(\s*\*", lowered):
        builder.stdout = True
    if re.search(r"\b(common|save)\b", lowered):
        builder.global_state = True
    if re.search(r"\b(system|execute_command_line)\b", lowered):
        builder.process = True
        builder.unsupported.add("process_execution")
    if re.search(r"\bequivalence\b", lowered):
        builder.unsupported.add("equivalence")
    if re.search(r"\bcomputed\s+goto\b|\bgoto\s*\(", lowered):
        builder.unsupported.add("computed_goto")

    if _END_DO_RE.match(statement.text):
        if builder.loop_stack:
            loop = builder.loop_stack.pop()
            loop_id = f"L{len(builder.loops) + 1}"
            builder.loops.append(_classify_loop(loop, statement.line, loop_id))
        return

    do_match = _DO_RE.match(statement.text)
    if do_match:
        builder.loop_stack.append(_LoopBuilder(statement.line, do_match.group("variable").lower()))
        return

    for loop in builder.loop_stack:
        loop.statements.append(statement.text)


def _finish_routine(builder: _RoutineBuilder, end_line: int) -> RoutineDigest:
    while builder.loop_stack:
        loop = builder.loop_stack.pop()
        loop_id = f"L{len(builder.loops) + 1}"
        builder.loops.append(_classify_loop(loop, end_line, loop_id))
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
            filesystem=builder.filesystem,
            network=builder.network,
            global_state=builder.global_state,
            stdout=builder.stdout,
            process=builder.process,
        ),
        loops=tuple(sorted(builder.loops, key=lambda item: item.start_line)),
        support_status=(SupportStatus.REQUIRES_FALLBACK if unsupported else SupportStatus.ANALYZED),
        unsupported_constructs=unsupported,
    )


def analyze_fortran_source(path: Path, relative_path: str, data: bytes) -> SourceFileDigest:
    """Inventory a Fortran source file without compiling or executing it."""

    text = data.decode("utf-8")
    lines = text.splitlines()
    form = source_form_for(path)
    statements = _fixed_statements(lines) if form is SourceForm.FIXED else _free_statements(lines)

    routines: list[RoutineDigest] = []
    current: Optional[_RoutineBuilder] = None
    for statement in statements:
        start = _routine_start(statement.text)
        if start:
            if current is not None:
                previous_end = max(statement.line - 1, current.start_line)
                routines.append(_finish_routine(current, previous_end))
            kind, name, arguments = start
            current = _RoutineBuilder(name, kind, relative_path, statement.line, arguments)
            continue
        if current is None:
            continue
        if _END_ROUTINE_RE.match(statement.text):
            routines.append(_finish_routine(current, statement.line))
            current = None
            continue
        _inspect_statement(current, statement)

    if current is not None:
        routines.append(_finish_routine(current, len(lines)))

    return SourceFileDigest(
        path=relative_path,
        sha256=sha256(data).hexdigest(),
        size_bytes=len(data),
        line_count=len(lines),
        source_form=form,
        routines=tuple(routines),
    )
