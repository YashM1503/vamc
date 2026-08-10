"""Verification-gated NumPy and Numba candidate generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psyclone.psyir.frontend.fortran import FortranReader  # type: ignore[import-untyped]
from psyclone.psyir.nodes import (  # type: ignore[import-untyped]
    ArrayReference,
    Assignment,
    BinaryOperation,
    CodeBlock,
    IntrinsicCall,
    Literal,
    Loop,
    Reference,
    Routine,
    UnaryOperation,
)
from psyclone.psyir.symbols import ArrayType  # type: ignore[import-untyped]

from vamc.backends.python import (
    _BINARY_OPERATORS,
    _MATH_INTRINSICS,
    _UNARY_OPERATORS,
    _artifact,
    _RoutineEmitter,
    _safe_identifier,
    module_name,
)
from vamc.models import (
    AnalysisResult,
    CandidateBackend,
    CandidateRecord,
    CandidateStatus,
    GeneratedArtifact,
    LoopPattern,
    ParallelStatus,
    RoutineDigest,
    RoutineTranslation,
    SourceForm,
    TranslationStatus,
)


@dataclass(frozen=True)
class OptimizedGeneration:
    artifacts: tuple[GeneratedArtifact, ...]
    candidates: tuple[CandidateRecord, ...]


class _NumPyMapEmitter:
    def __init__(self, routine: Any, digest: RoutineDigest) -> None:
        self.routine = routine
        self.digest = digest
        self.scalar = _RoutineEmitter(routine, digest, {}, "", direct_arrays=True)

    def emit(self) -> list[str]:
        if self.routine.walk(CodeBlock) or len(self.routine.children) != 1:
            raise ValueError("numpy_requires_single_map_loop")
        loop = self.routine.children[0]
        if not isinstance(loop, Loop) or len(loop.loop_body.children) != 1:
            raise ValueError("numpy_requires_single_map_assignment")
        assignment = loop.loop_body.children[0]
        if not isinstance(assignment, Assignment) or not isinstance(assignment.lhs, ArrayReference):
            raise ValueError("numpy_requires_array_assignment")
        if len(assignment.lhs.indices) != 1 or not isinstance(assignment.lhs.indices[0], Reference):
            raise ValueError("numpy_requires_rank_one_unit_index")
        variable = loop.variable.name.lower()
        if assignment.lhs.indices[0].name.lower() != variable:
            raise ValueError("numpy_requires_direct_induction_index")
        if not isinstance(loop.step_expr, Literal) or loop.step_expr.value != "1":
            raise ValueError("numpy_requires_unit_loop_step")

        start = self.scalar._expression(loop.start_expr)
        stop = self.scalar._expression(loop.stop_expr)
        array_type = assignment.lhs.symbol.datatype
        if not isinstance(array_type, ArrayType):
            raise ValueError("numpy_requires_array_type")
        lower = getattr(array_type.shape[0], "lower", None)
        lower_text = self.scalar._expression(lower) if lower is not None else "1"
        section = f"({start}) - ({lower_text}):(({stop}) - ({lower_text}) + 1)"
        arguments = ", ".join(
            _safe_identifier(item, prefix="arg") for item in self.digest.arguments
        )
        target_name = _safe_identifier(assignment.lhs.name, prefix="array")
        target = f"{target_name}[{section}]"
        expression = self._expression(assignment.rhs, variable, section)
        return [
            f"def {_safe_identifier(self.digest.name, prefix='routine')}({arguments}):",
            f'    """NumPy map candidate from {self.digest.file}:{self.digest.start_line}."""',
            f"    {target} = {expression}",
        ]

    def _expression(self, node: Any, variable: str, section: str) -> str:
        if isinstance(node, ArrayReference):
            if (
                len(node.indices) != 1
                or not isinstance(node.indices[0], Reference)
                or node.indices[0].name.lower() != variable
            ):
                raise ValueError("numpy_non_map_array_access")
            array_name = _safe_identifier(node.name, prefix="array")
            return f"{array_name}[{section}]"
        if isinstance(node, Reference):
            return _safe_identifier(node.name, prefix="value")
        if isinstance(node, Literal):
            return self.scalar._literal(node)
        if isinstance(node, BinaryOperation):
            operator = _BINARY_OPERATORS.get(node.operator.name)
            if operator is None:
                raise ValueError("numpy_unsupported_binary_operation")
            left = self._expression(node.children[0], variable, section)
            right = self._expression(node.children[1], variable, section)
            return f"({left} {operator} {right})"
        if isinstance(node, UnaryOperation):
            operator = _UNARY_OPERATORS.get(node.operator.name)
            if operator is None:
                raise ValueError("numpy_unsupported_unary_operation")
            return f"({operator}{self._expression(node.children[0], variable, section)})"
        if isinstance(node, IntrinsicCall):
            name = node.intrinsic.name
            arguments = ", ".join(
                self._expression(item, variable, section) for item in node.arguments
            )
            if name == "ABS":
                return f"np.abs({arguments})"
            function = _MATH_INTRINSICS.get(name)
            if function:
                return f"np.{function}({arguments})"
            raise ValueError("numpy_unsupported_intrinsic")
        raise ValueError("numpy_unsupported_expression")


def _candidate(
    *,
    digest: RoutineDigest,
    backend: CandidateBackend,
    path: str,
    transforms: tuple[str, ...],
    preconditions: tuple[str, ...],
) -> CandidateRecord:
    identifier = f"{module_name(digest.file)}.{digest.name}.{backend.value.lower()}.v1"
    return CandidateRecord(
        id=identifier,
        parent=f"{digest.file}:{digest.name}:serial-python",
        source_file=digest.file,
        routine=digest.name,
        backend=backend,
        generated_file=path,
        transforms=transforms,
        preconditions=preconditions,
        status=CandidateStatus.REQUIRES_VERIFICATION,
    )


def _module_source(title: str, imports: tuple[str, ...], emitted: list[str]) -> str:
    lines = [f'"""{title}"""', "", "from __future__ import annotations", ""]
    lines.extend(imports)
    lines.append("")
    lines.extend(emitted)
    lines.append("")
    return "\n".join(lines)


def generate_optimized_candidates(
    analysis: AnalysisResult,
    sources: tuple[tuple[str, str], ...],
    translations: tuple[RoutineTranslation, ...],
    *,
    package_name: str,
    parallel: str,
) -> OptimizedGeneration:
    """Generate unaccepted candidates whose manifest status requires verification."""

    if parallel not in {"off", "auto"}:
        raise ValueError("parallel must be 'off' or 'auto'")
    translated = {
        (item.source_file, item.routine)
        for item in translations
        if item.status is TranslationStatus.TRANSLATED
    }
    digests = {
        (file_digest.path, routine.name): routine
        for file_digest in analysis.files
        for routine in file_digest.routines
    }
    forms = {item.path: item.source_form for item in analysis.files}
    artifacts: list[GeneratedArtifact] = []
    candidates: list[CandidateRecord] = []
    base_path = f"src/{package_name}/_candidates"
    artifacts.append(
        _artifact(f"{base_path}/__init__.py", '"""Unaccepted optimization candidates."""\n')
    )

    for source_path, source in sources:
        reader = FortranReader(free_form=forms[source_path] is SourceForm.FREE)
        try:
            tree = reader.psyir_from_source(source)
        except Exception:
            tree = None
        if tree is None:
            continue
        for routine in tree.walk(Routine):
            key = (source_path, routine.name.lower())
            if key not in translated:
                continue
            digest = digests[key]
            safe_name = _safe_identifier(digest.name, prefix="routine")
            module = module_name(source_path)

            if digest.loops and all(
                loop.pattern is LoopPattern.MAP
                and loop.parallel_status is ParallelStatus.CONDITIONALLY_SAFE
                for loop in digest.loops
            ):
                try:
                    numpy_emitted = _NumPyMapEmitter(routine, digest).emit()
                except ValueError:
                    pass
                else:
                    path = f"{base_path}/{module}__{safe_name}__numpy.py"
                    artifacts.append(
                        _artifact(
                            path,
                            _module_source(
                                "NumPy candidate generated by VAMC; not accepted until verified.",
                                ("import numpy as np",),
                                numpy_emitted,
                            ),
                        )
                    )
                    candidates.append(
                        _candidate(
                            digest=digest,
                            backend=CandidateBackend.NUMPY,
                            path=path,
                            transforms=("map loop -> NumPy array expression",),
                            preconditions=(
                                "direct rank-one induction indexing",
                                "unit positive loop step",
                                "PSyIR dependency analysis found no loop-carried access",
                            ),
                        )
                    )

            try:
                serial_emitted = _RoutineEmitter(
                    routine,
                    digest,
                    {},
                    module,
                    direct_arrays=True,
                    jit_mode="serial",
                ).emit()
            except ValueError:
                pass
            else:
                path = f"{base_path}/{module}__{safe_name}__numba_serial.py"
                artifacts.append(
                    _artifact(
                        path,
                        _module_source(
                            "Numba serial candidate generated by VAMC; verification required.",
                            ("import math", "from numba import njit, prange"),
                            serial_emitted,
                        ),
                    )
                )
                candidates.append(
                    _candidate(
                        digest=digest,
                        backend=CandidateBackend.NUMBA_SERIAL,
                        path=path,
                        transforms=("serial Python -> Numba nopython JIT",),
                        preconditions=("direct typed-array access",),
                    )
                )

            parallel_safe = (
                parallel == "auto"
                and len(digest.loops) == 1
                and digest.loops[0].parallel_status is ParallelStatus.CONDITIONALLY_SAFE
                and digest.loops[0].pattern
                in {LoopPattern.MAP, LoopPattern.REDUCTION, LoopPattern.STENCIL}
            )
            if not parallel_safe:
                continue
            try:
                parallel_emitted = _RoutineEmitter(
                    routine,
                    digest,
                    {},
                    module,
                    direct_arrays=True,
                    jit_mode="parallel",
                ).emit()
            except ValueError:
                continue
            path = f"{base_path}/{module}__{safe_name}__numba_parallel.py"
            artifacts.append(
                _artifact(
                    path,
                    _module_source(
                        "Numba parallel candidate generated by VAMC; verification required.",
                        ("import math", "from numba import njit, prange"),
                        parallel_emitted,
                    ),
                )
            )
            candidates.append(
                _candidate(
                    digest=digest,
                    backend=CandidateBackend.NUMBA_PARALLEL,
                    path=path,
                    transforms=(f"loop:{digest.loops[0].id} -> numba.prange",),
                    preconditions=(
                        "single loop routine",
                        "PSyIR dependency analysis found no blocking dependence",
                        "unit positive loop step",
                        "differential verification required before acceptance",
                    ),
                )
            )
    return OptimizedGeneration(
        artifacts=tuple(sorted(artifacts, key=lambda item: item.path)),
        candidates=tuple(sorted(candidates, key=lambda item: item.id)),
    )
