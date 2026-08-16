"""Rootless-container execution boundary for untrusted compilation and execution."""

from __future__ import annotations

import os
import re
import selectors
import shutil
import stat
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from pathlib import Path

from vamc.analysis.inventory import AnalysisError

_DIGEST_IMAGE = re.compile(r"(?:@sha256:|^sha256:)[0-9a-f]{64}$")
_SAFE_ENVIRONMENT_KEYS = {
    "DOCKER_CERT_PATH",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "DOCKER_TLS_VERIFY",
    "HOME",
    "PATH",
}


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 60.0
    cpus: float = 1.0
    memory_megabytes: int = 1024
    pids: int = 64
    file_megabytes: int = 256
    write_megabytes: int = 256
    write_entries: int = 100_000
    output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if self.wall_seconds <= 0 or self.cpus <= 0:
            raise ValueError("sandbox time and CPU limits must be positive")
        if (
            min(
                self.memory_megabytes,
                self.pids,
                self.file_megabytes,
                self.write_megabytes,
                self.write_entries,
                self.output_bytes,
            )
            <= 0
        ):
            raise ValueError("sandbox resource limits must be positive")


@dataclass(frozen=True)
class SandboxResult:
    command: tuple[str, ...]
    returncode: int
    output: str
    timed_out: bool
    output_limited: bool
    storage_limited: bool = False

    @property
    def succeeded(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.output_limited
            and not self.storage_limited
        )


@dataclass(frozen=True)
class SandboxMount:
    source: Path
    target: str
    read_only: bool


class DockerSandbox:
    """Construct and run hardened Docker invocations without a host-execution fallback."""

    def __init__(
        self,
        image: str,
        *,
        limits: SandboxLimits | None = None,
        executable: str | Path | None = None,
        require_pinned_image: bool = True,
    ) -> None:
        if require_pinned_image and not _DIGEST_IMAGE.search(image):
            raise ValueError("sandbox image must be pinned by sha256 digest")
        selected = Path(executable) if executable else Path(shutil.which("docker") or "")
        if not selected.is_absolute() or not selected.is_file():
            raise AnalysisError("Docker CLI is not installed or is not an absolute executable")
        self.executable = selected
        self.image = image
        self.limits = limits or SandboxLimits()

    def _mount_argument(self, mount: SandboxMount) -> str:
        source = mount.source.resolve()
        if not source.exists() or any(character in str(source) for character in ",\n\r"):
            raise AnalysisError("sandbox mount source is missing or contains an unsafe character")
        if not mount.target.startswith("/") or any(
            part in {"", ".", ".."} for part in Path(mount.target).parts[1:]
        ):
            raise AnalysisError("sandbox mount target must be a normalized absolute path")
        value = f"type=bind,source={source},target={mount.target}"
        if mount.read_only:
            value += ",readonly"
        return value

    def command(
        self,
        arguments: tuple[str, ...],
        *,
        mounts: tuple[SandboxMount, ...] = (),
        working_directory: str = "/work",
    ) -> tuple[str, ...]:
        """Return a complete hardened Docker command for audit and testing."""

        if not arguments or any("\x00" in item for item in arguments):
            raise AnalysisError("sandbox command arguments are invalid")
        if not working_directory.startswith("/") or ".." in Path(working_directory).parts:
            raise AnalysisError("sandbox working directory is invalid")
        file_bytes = self.limits.file_megabytes * 1024 * 1024
        command = [
            str(self.executable),
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            f"--pids-limit={self.limits.pids}",
            f"--memory={self.limits.memory_megabytes}m",
            f"--cpus={self.limits.cpus}",
            f"--ulimit=fsize={file_bytes}:{file_bytes}",
            "--ulimit=nofile=256:256",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
            f"--user={os.getuid()}:{os.getgid()}",
            f"--workdir={working_directory}",
            "--env=HOME=/tmp",
            "--env=PYTHONNOUSERSITE=1",
            "--env=PYTHONDONTWRITEBYTECODE=1",
        ]
        for mount in mounts:
            command.extend(("--mount", self._mount_argument(mount)))
        command.append(self.image)
        command.extend(arguments)
        return tuple(command)

    def probe(self) -> SandboxResult:
        """Check that the local Docker engine is reachable without pulling an image."""

        return self._run((str(self.executable), "version", "--format", "{{.Server.Version}}"), 10.0)

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        mounts: tuple[SandboxMount, ...] = (),
        working_directory: str = "/work",
    ) -> SandboxResult:
        writable_roots = tuple(mount.source.resolve() for mount in mounts if not mount.read_only)
        return self._run(
            self.command(arguments, mounts=mounts, working_directory=working_directory),
            self.limits.wall_seconds,
            writable_roots,
        )

    def _run(
        self,
        command: tuple[str, ...],
        timeout: float,
        writable_roots: tuple[Path, ...] = (),
    ) -> SandboxResult:
        environment = {
            key: value for key, value in os.environ.items() if key in _SAFE_ENVIRONMENT_KEYS
        }
        process = subprocess.Popen(  # noqa: S603  # nosec B603
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            close_fds=True,
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("sandbox output pipe was not created")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        captured = bytearray()
        timed_out = False
        output_limited = False
        storage_limited = False
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                process.kill()
                break
            for _key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(process.stdout.fileno(), 64 * 1024)
                if chunk:
                    captured.extend(chunk)
                    if len(captured) > self.limits.output_bytes:
                        output_limited = True
                        process.kill()
                        break
            if output_limited:
                break
            if _writable_limit_exceeded(
                writable_roots,
                self.limits.write_megabytes * 1024 * 1024,
                self.limits.write_entries,
            ):
                storage_limited = True
                process.kill()
                break
        process.wait()
        remaining_output = process.stdout.read(self.limits.output_bytes + 1 - len(captured))
        captured.extend(remaining_output)
        if len(captured) > self.limits.output_bytes:
            output_limited = True
            del captured[self.limits.output_bytes :]
        if _writable_limit_exceeded(
            writable_roots,
            self.limits.write_megabytes * 1024 * 1024,
            self.limits.write_entries,
        ):
            storage_limited = True
        selector.close()
        return SandboxResult(
            command=command,
            returncode=process.returncode,
            output=captured.decode("utf-8", errors="replace"),
            timed_out=timed_out,
            output_limited=output_limited,
            storage_limited=storage_limited,
        )


def _writable_limit_exceeded(roots: tuple[Path, ...], byte_limit: int, entry_limit: int) -> bool:
    """Bound aggregate regular-file bytes and entries without following links."""

    total = 0
    entries = 0
    pending = list(roots)
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > entry_limit:
                        return True
                    try:
                        metadata = child.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        return True
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(Path(child.path))
                    elif stat.S_ISREG(metadata.st_mode):
                        total += metadata.st_size
                        if total > byte_limit:
                            return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False
