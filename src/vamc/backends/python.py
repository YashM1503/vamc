"""Conservative PSyIR-to-Python source generation."""

from __future__ import annotations

import hashlib
import keyword
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from psyclone.psyir.frontend.fortran import FortranReader  # type: ignore[import-untyped]
from psyclone.psyir.nodes import (  # type: ignore[import-untyped]
    ArrayReference,
    Assignment,
    BinaryOperation,
    Call,
    CodeBlock,
    IfBlock,
    IntrinsicCall,
    Literal,
    Loop,
    Reference,
    Return,
    Routine,
    Schedule,
    UnaryOperation,
)
from psyclone.psyir.symbols import ArrayType, DataSymbol  # type: ignore[import-untyped]

from vamc.models import (
    AnalysisResult,
    GeneratedArtifact,
    ParserStatus,
    RoutineDigest,
    RoutineTranslation,
    SourceForm,
    SourceMapEntry,
    SupportStatus,
    TranslationStatus,
)


class UnsupportedPythonTranslation(ValueError):
    """Raised when a PSyIR construct has no semantics-preserving Python lowering."""


@dataclass(frozen=True)
class PythonGeneration:
    artifacts: tuple[GeneratedArtifact, ...]
    routines: tuple[RoutineTranslation, ...]
    source_maps: tuple[SourceMapEntry, ...]


_BINARY_OPERATORS = {
    "ADD": "+",
    "SUB": "-",
    "MUL": "*",
    "DIV": "/",
    "REM": "%",
    "POW": "**",
    "EQ": "==",
    "NE": "!=",
    "GT": ">",
    "LT": "<",
    "GE": ">=",
    "LE": "<=",
    "AND": "and",
    "OR": "or",
    "EQV": "==",
    "NEQV": "!=",
}
_UNARY_OPERATORS = {"MINUS": "-", "PLUS": "+", "NOT": "not "}
_BUILTIN_INTRINSICS = {
    "ABS": "abs",
    "INT": "int",
    "MAX": "max",
    "MIN": "min",
    "REAL": "float",
    "SUM": "sum",
}
_MATH_INTRINSICS = {
    "ACOS": "acos",
    "ASIN": "asin",
    "ATAN": "atan",
    "ATAN2": "atan2",
    "CEILING": "ceil",
    "COS": "cos",
    "COSH": "cosh",
    "EXP": "exp",
    "FLOOR": "floor",
    "LOG": "log",
    "LOG10": "log10",
    "SIN": "sin",
    "SINH": "sinh",
    "SQRT": "sqrt",
    "TAN": "tan",
    "TANH": "tanh",
}


def _safe_identifier(value: str, *, prefix: str = "vamc") -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_").lower()
    if not identifier or identifier[0].isdigit() or keyword.iskeyword(identifier):
        identifier = f"{prefix}_{identifier}"
    return identifier


def module_name(source_path: str) -> str:
    """Create a deterministic collision-resistant module name from a source path."""

    path = PurePosixPath(source_path)
    stem = _safe_identifier("__".join((*path.parts[:-1], path.stem)), prefix="source")
    suffix = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{suffix}"


def _artifact(path: str, content: str) -> GeneratedArtifact:
    encoded = content.encode("utf-8")
    return GeneratedArtifact(path=path, content=content, sha256=hashlib.sha256(encoded).hexdigest())


class _RoutineEmitter:
    """Emit one routine while rejecting every unimplemented semantic construct."""

    def __init__(
        self,
        routine: Any,
        digest: RoutineDigest,
        call_targets: dict[str, str],
        current_module: str,
        direct_arrays: bool = False,
        jit_mode: str | None = None,
    ) -> None:
        self.routine = routine
        self.digest = digest
        self.call_targets = call_targets
        self.current_module = current_module
        self.direct_arrays = direct_arrays
        self.jit_mode = jit_mode
        self.lines: list[str] = []

    def emit(self) -> list[str]:
        if self.routine.walk(CodeBlock):
            raise UnsupportedPythonTranslation("psyir_codeblock")
        self._validate_arguments()
        arguments = ", ".join(
            _safe_identifier(item, prefix="arg") for item in self.digest.arguments
        )
        if self.jit_mode:
            parallel = ", parallel=True" if self.jit_mode == "parallel" else ""
            self.lines.append(f"@njit(cache=True{parallel})")
        self.lines.append(
            f"def {_safe_identifier(self.digest.name, prefix='routine')}({arguments}):"
        )
        self.lines.append(f'    """Generated from {self.digest.file}:{self.digest.start_line}."""')
        self._emit_lazy_imports()
        self._emit_constants_and_local_arrays()
        self._emit_schedule(self.routine, 1)
        return_symbol = getattr(self.routine, "return_symbol", None)
        if return_symbol is not None:
            self.lines.append(f"    return {_safe_identifier(return_symbol.name, prefix='result')}")
        elif not self.routine.children or not self._has_executable_line():
            self.lines.append("    pass")
        return self.lines

    def _validate_arguments(self) -> None:
        details = {item.name: item for item in self.digest.symbol_details}
        for argument in self.digest.arguments:
            detail = details.get(argument)
            if (
                detail
                and detail.rank == 0
                and detail.argument_access.value in {"WRITE", "READWRITE"}
            ):
                raise UnsupportedPythonTranslation("scalar_output_argument")

    def _has_executable_line(self) -> bool:
        return any(
            line.startswith("    ") and not line.lstrip().startswith(('"""', "from "))
            for line in self.lines[2:]
        )

    def _emit_lazy_imports(self) -> None:
        if self.jit_mode and self.digest.calls:
            raise UnsupportedPythonTranslation("jit_cross_routine_call")
        for called in sorted(set(self.digest.calls)):
            target_module = self.call_targets.get(called)
            if target_module and target_module != self.current_module:
                safe = _safe_identifier(called, prefix="routine")
                self.lines.append(f"    from .{target_module} import {safe} as _vamc_call_{safe}")

    def _emit_constants_and_local_arrays(self) -> None:
        argument_names = set(self.digest.arguments)
        return_symbol = getattr(self.routine, "return_symbol", None)
        for symbol in self.routine.symbol_table.symbols:
            if not isinstance(symbol, DataSymbol) or symbol.name.lower() in argument_names:
                continue
            if return_symbol is not None and symbol is return_symbol:
                continue
            constant_value = getattr(symbol, "constant_value", None)
            if constant_value is not None:
                symbol_name = _safe_identifier(symbol.name, prefix="value")
                rendered_value = self._expression(constant_value)
                self.lines.append(f"    {symbol_name} = {rendered_value}")
                continue
            if isinstance(symbol.datatype, ArrayType):
                if self.jit_mode:
                    raise UnsupportedPythonTranslation("jit_local_array")
                dimensions = []
                for dimension in symbol.datatype.shape:
                    lower = getattr(dimension, "lower", None)
                    upper = getattr(dimension, "upper", None)
                    if lower is None or upper is None:
                        raise UnsupportedPythonTranslation("automatic_array_unknown_shape")
                    dimensions.append(
                        f"(({self._expression(upper)}) - ({self._expression(lower)}) + 1)"
                    )
                rendered = ", ".join(dimensions)
                if len(dimensions) == 1:
                    rendered += ","
                symbol_name = _safe_identifier(symbol.name, prefix="array")
                self.lines.append(f"    {symbol_name} = _vamc_zeros(({rendered}))")

    def _emit_schedule(self, parent: Any, indent: int) -> None:
        children = parent.children if isinstance(parent, (Routine, Schedule)) else ()
        for child in children:
            self._statement(child, indent)

    def _statement(self, node: Any, indent: int) -> None:
        prefix = "    " * indent
        if isinstance(node, Assignment):
            rhs = self._expression(node.rhs)
            if isinstance(node.lhs, ArrayReference):
                indices = ", ".join(self._normalized_indices(node.lhs))
                array_name = _safe_identifier(node.lhs.name, prefix="array")
                if self.direct_arrays:
                    self.lines.append(f"{prefix}{array_name}[{indices}] = {rhs}")
                else:
                    self.lines.append(f"{prefix}_vamc_set({array_name}, ({indices},), {rhs})")
            elif isinstance(node.lhs, Reference):
                self.lines.append(
                    f"{prefix}{_safe_identifier(node.lhs.name, prefix='value')} = {rhs}"
                )
            else:
                raise UnsupportedPythonTranslation(type(node.lhs).__name__)
            return
        if isinstance(node, Loop):
            variable = _safe_identifier(node.variable.name, prefix="index")
            start = self._expression(node.start_expr)
            stop = self._expression(node.stop_expr)
            step = self._expression(node.step_expr)
            if self.jit_mode == "parallel":
                if not isinstance(node.step_expr, Literal) or node.step_expr.value != "1":
                    raise UnsupportedPythonTranslation("parallel_nonunit_loop_step")
                iteration = f"prange({start}, ({stop}) + 1)"
            elif self.jit_mode:
                iteration = f"range({start}, ({stop}) + (1 if ({step}) > 0 else -1), {step})"
            else:
                iteration = f"_vamc_range({start}, {stop}, {step})"
            self.lines.append(f"{prefix}for {variable} in {iteration}:")
            before = len(self.lines)
            self._emit_schedule(node.loop_body, indent + 1)
            if len(self.lines) == before:
                self.lines.append(f"{prefix}    pass")
            return
        if isinstance(node, IfBlock):
            self.lines.append(f"{prefix}if {self._expression(node.condition)}:")
            before = len(self.lines)
            self._emit_schedule(node.if_body, indent + 1)
            if len(self.lines) == before:
                self.lines.append(f"{prefix}    pass")
            if node.else_body:
                self.lines.append(f"{prefix}else:")
                before = len(self.lines)
                self._emit_schedule(node.else_body, indent + 1)
                if len(self.lines) == before:
                    self.lines.append(f"{prefix}    pass")
            return
        if isinstance(node, Call) and not isinstance(node, IntrinsicCall):
            self.lines.append(f"{prefix}{self._call(node)}")
            return
        if isinstance(node, Return):
            return_symbol = getattr(self.routine, "return_symbol", None)
            if return_symbol is None:
                self.lines.append(f"{prefix}return")
            else:
                self.lines.append(
                    f"{prefix}return {_safe_identifier(return_symbol.name, prefix='result')}"
                )
            return
        raise UnsupportedPythonTranslation(type(node).__name__)

    def _expression(self, node: Any) -> str:
        if isinstance(node, ArrayReference):
            indices = ", ".join(self._normalized_indices(node))
            array_name = _safe_identifier(node.name, prefix="array")
            if self.direct_arrays:
                return f"{array_name}[{indices}]"
            return f"_vamc_get({array_name}, ({indices},))"
        if isinstance(node, Reference):
            return _safe_identifier(node.name, prefix="value")
        if isinstance(node, Literal):
            return self._literal(node)
        if isinstance(node, BinaryOperation):
            operator = _BINARY_OPERATORS.get(node.operator.name)
            if operator is None:
                raise UnsupportedPythonTranslation(f"binary_{node.operator.name.lower()}")
            left = self._expression(node.children[0])
            right = self._expression(node.children[1])
            return f"({left} {operator} {right})"
        if isinstance(node, UnaryOperation):
            operator = _UNARY_OPERATORS.get(node.operator.name)
            if operator is None:
                raise UnsupportedPythonTranslation(f"unary_{node.operator.name.lower()}")
            return f"({operator}{self._expression(node.children[0])})"
        if isinstance(node, IntrinsicCall):
            return self._intrinsic(node)
        if isinstance(node, Call):
            return self._call(node)
        raise UnsupportedPythonTranslation(type(node).__name__)

    def _literal(self, node: Any) -> str:
        value = str(node.value).strip()
        intrinsic = getattr(getattr(node, "datatype", None), "intrinsic", None)
        intrinsic_name = getattr(intrinsic, "name", "")
        if intrinsic_name in {"BOOLEAN", "LOGICAL"}:
            return "True" if value.lower() in {"true", ".true."} else "False"
        if intrinsic_name == "CHARACTER":
            return repr(value)
        if intrinsic_name == "REAL":
            value = re.sub(r"(?<=\d)[dD](?=[+-]?\d)", "e", value)
            value = re.sub(r"_[A-Za-z0-9_]+$", "", value)
        if intrinsic_name == "INTEGER":
            value = re.sub(r"_[A-Za-z0-9_]+$", "", value)
        if intrinsic_name not in {"INTEGER", "REAL", "BOOLEAN", "LOGICAL", "CHARACTER"}:
            raise UnsupportedPythonTranslation(f"literal_{intrinsic_name.lower() or 'unknown'}")
        return value

    def _intrinsic(self, node: Any) -> str:
        name = node.intrinsic.name
        arguments = [self._expression(item) for item in node.arguments]
        if name in _BUILTIN_INTRINSICS:
            return f"{_BUILTIN_INTRINSICS[name]}({', '.join(arguments)})"
        if name in _MATH_INTRINSICS:
            return f"math.{_MATH_INTRINSICS[name]}({', '.join(arguments)})"
        if name in {"MOD", "MODULO"} and len(arguments) == 2:
            return f"({arguments[0]} % {arguments[1]})"
        if name == "SIGN" and len(arguments) == 2:
            if self.jit_mode:
                raise UnsupportedPythonTranslation("jit_intrinsic_sign")
            return f"_vamc_sign({arguments[0]}, {arguments[1]})"
        if name == "NINT" and len(arguments) == 1:
            return f"round({arguments[0]})"
        if name == "AINT" and len(arguments) == 1:
            return f"math.trunc({arguments[0]})"
        if name == "SIZE" and len(arguments) in {1, 2}:
            if self.jit_mode:
                raise UnsupportedPythonTranslation("jit_intrinsic_size")
            dimension = arguments[1] if len(arguments) == 2 else "None"
            return f"_vamc_size({arguments[0]}, {dimension})"
        raise UnsupportedPythonTranslation(f"intrinsic_{name.lower()}")

    def _call(self, node: Any) -> str:
        name = node.routine.name.lower()
        safe = _safe_identifier(name, prefix="routine")
        target_module = self.call_targets.get(name)
        callable_name = (
            f"_vamc_call_{safe}" if target_module and target_module != self.current_module else safe
        )
        arguments = ", ".join(self._expression(item) for item in node.arguments)
        return f"{callable_name}({arguments})"

    def _normalized_indices(self, reference: Any) -> tuple[str, ...]:
        datatype = reference.symbol.datatype
        if not isinstance(datatype, ArrayType):
            raise UnsupportedPythonTranslation("array_reference_without_array_type")
        if len(reference.indices) != len(datatype.shape):
            raise UnsupportedPythonTranslation("array_rank_mismatch")
        normalized: list[str] = []
        for index, dimension in zip(reference.indices, datatype.shape, strict=True):
            if type(index).__name__ == "Range":
                raise UnsupportedPythonTranslation("array_section")
            lower = getattr(dimension, "lower", None)
            lower_expression = self._expression(lower) if lower is not None else "1"
            normalized.append(f"({self._expression(index)}) - ({lower_expression})")
        return tuple(normalized)


_RUNTIME_SOURCE = '''"""Runtime helpers for VAMC-generated serial Python."""

from __future__ import annotations

from typing import Any


def _vamc_range(start: int, stop: int, step: int = 1) -> range:
    """Represent an inclusive Fortran DO range."""
    if step == 0:
        raise ValueError("Fortran DO step cannot be zero")
    return range(start, stop + (1 if step > 0 else -1), step)


def _vamc_get(value: Any, indices: tuple[int, ...]) -> Any:
    if len(indices) == 1:
        return value[indices[0]]
    try:
        return value[indices]
    except TypeError:
        result = value
        for index in indices:
            result = result[index]
        return result


def _vamc_set(value: Any, indices: tuple[int, ...], assigned: Any) -> None:
    if len(indices) == 1:
        value[indices[0]] = assigned
        return
    try:
        value[indices] = assigned
    except TypeError:
        target = value
        for index in indices[:-1]:
            target = target[index]
        target[indices[-1]] = assigned


def _vamc_zeros(shape: tuple[int, ...]) -> Any:
    if not shape or any(size < 0 for size in shape):
        raise ValueError("invalid generated array shape")
    if len(shape) == 1:
        return [0 for _ in range(shape[0])]
    return [_vamc_zeros(shape[1:]) for _ in range(shape[0])]


def _vamc_sign(first: float, second: float) -> float:
    return abs(first) if second >= 0 else -abs(first)


def _vamc_size(value: Any, dimension: int | None = None) -> int:
    if dimension is None:
        size = 1
        current = value
        while hasattr(current, "__len__"):
            length = len(current)
            size *= length
            if length == 0:
                break
            current = current[0]
        return size
    current = value
    for _ in range(dimension - 1):
        current = current[0]
    return len(current)
'''


def generate_python(
    analysis: AnalysisResult,
    sources: tuple[tuple[str, str], ...],
    *,
    package_name: str,
) -> PythonGeneration:
    """Generate deterministic serial Python from an analyzed in-memory source snapshot."""

    digests_by_path = {item.path: item for item in analysis.files}
    modules_by_path = {path: module_name(path) for path, _ in sources}
    definitions: dict[str, list[str]] = {}
    for file_digest in analysis.files:
        for routine_digest in file_digest.routines:
            if routine_digest.support_status is SupportStatus.AUTHORITATIVELY_PARSED:
                definitions.setdefault(routine_digest.name, []).append(
                    modules_by_path[file_digest.path]
                )
    call_targets = {name: modules[0] for name, modules in definitions.items() if len(modules) == 1}

    artifacts: list[GeneratedArtifact] = []
    translations: list[RoutineTranslation] = []
    source_maps: list[SourceMapEntry] = []
    exported: dict[str, str] = {}
    package_path = f"src/{package_name}"
    artifacts.append(_artifact(f"{package_path}/_runtime.py", _RUNTIME_SOURCE))

    for source_path, source in sources:
        file_digest = digests_by_path[source_path]
        module = modules_by_path[source_path]
        reader = FortranReader(free_form=file_digest.source_form is SourceForm.FREE)
        try:
            tree = reader.psyir_from_source(source)
            psyir_routines = {item.name.lower(): item for item in tree.walk(Routine)}
        except Exception:  # Analysis already records parser failure without leaking source text.
            psyir_routines = {}

        module_lines = [
            '"""Deterministic serial Python generated by VAMC."""',
            "",
            "from __future__ import annotations",
            "",
            "import math",
            "",
            "from ._runtime import (",
            "    _vamc_get,",
            "    _vamc_range,",
            "    _vamc_set,",
            "    _vamc_sign,",
            "    _vamc_size,",
            "    _vamc_zeros,",
            ")",
            "",
        ]
        for digest in file_digest.routines:
            reasons = set(digest.unsupported_constructs)
            if len(definitions.get(digest.name, ())) > 1:
                reasons.add("ambiguous_routine_name")
            if digest.parser_status is not ParserStatus.AUTHORITATIVE:
                reasons.add(f"parser_{digest.parser_status.value.lower()}")
            routine: Any | None = psyir_routines.get(digest.name)
            if digest.support_status is not SupportStatus.AUTHORITATIVELY_PARSED:
                reasons.add("analysis_requires_fallback")
            if routine is None:
                reasons.add("missing_authoritative_ir")
            if reasons:
                translations.append(
                    RoutineTranslation(
                        source_file=source_path,
                        routine=digest.name,
                        status=TranslationStatus.FALLBACK_REQUIRED,
                        generated_file=None,
                        fallback_reasons=tuple(sorted(reasons)),
                    )
                )
                continue
            try:
                emitted = _RoutineEmitter(routine, digest, call_targets, module).emit()
            except UnsupportedPythonTranslation as error:
                translations.append(
                    RoutineTranslation(
                        source_file=source_path,
                        routine=digest.name,
                        status=TranslationStatus.FALLBACK_REQUIRED,
                        generated_file=None,
                        fallback_reasons=(str(error),),
                    )
                )
                continue
            if module_lines[-1] != "":
                module_lines.append("")
            start_line = len(module_lines) + 1
            module_lines.extend(emitted)
            end_line = len(module_lines)
            generated_file = f"{package_path}/{module}.py"
            translations.append(
                RoutineTranslation(
                    source_file=source_path,
                    routine=digest.name,
                    status=TranslationStatus.TRANSLATED,
                    generated_file=generated_file,
                    fallback_reasons=(),
                )
            )
            source_maps.append(
                SourceMapEntry(
                    source_file=source_path,
                    source_start_line=digest.start_line,
                    source_end_line=digest.end_line,
                    generated_file=generated_file,
                    generated_start_line=start_line,
                    generated_end_line=end_line,
                    routine=digest.name,
                )
            )
            if len(definitions.get(digest.name, ())) == 1:
                exported[digest.name] = module
            module_lines.append("")
        artifacts.append(
            _artifact(f"{package_path}/{module}.py", "\n".join(module_lines).rstrip() + "\n")
        )

    init_lines = ['"""Public API for the VAMC-modernized package."""', ""]
    for routine_name, module in sorted(exported.items()):
        safe = _safe_identifier(routine_name, prefix="routine")
        init_lines.append(f"from .{module} import {safe}")
    init_lines.extend(
        (
            "",
            f"__all__ = {sorted(_safe_identifier(name, prefix='routine') for name in exported)!r}",
            "",
        )
    )
    artifacts.append(_artifact(f"{package_path}/__init__.py", "\n".join(init_lines)))
    return PythonGeneration(
        artifacts=tuple(sorted(artifacts, key=lambda item: item.path)),
        routines=tuple(sorted(translations, key=lambda item: (item.source_file, item.routine))),
        source_maps=tuple(sorted(source_maps, key=lambda item: (item.source_file, item.routine))),
    )
