"""Run one command against a workspace, isolated, with a timeout.

docker mode (default): a throwaway container from the sandbox image with no
network, CPU/memory/process limits, a read-only root filesystem, no Linux
capabilities and a non-root user. Only the workspace is mounted (read-write).

local mode: a plain subprocess with a scrubbed environment and a timeout that
kills the whole process tree. It is NOT a sandbox. It is opt-in only and every
result says `isolated=False`, so it can never stand in for docker mode silently.

In both modes the command is killed on timeout, on too much output, and if the
caller is interrupted or crashes mid-run. Output goes to temporary files, never
to memory, and only the tail of each stream is kept.

Not limited: disk use inside the mounted workspace (workspaces live under runs/
and are thrown away after each run), and, in local mode only, background
processes a command leaves behind when it exits normally. A container ends with
its init process, so docker mode has no such leftovers.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = Path("docker") / "sandbox.Dockerfile"
IMAGE_NAME = "spec2ship-sandbox"
WORKSPACE_MOUNT = "/workspace"
FALLBACK_USER = "10001:10001"  # the image's `sandbox` user
OUTPUT_LIMIT = 64_000  # bytes kept from the end of stdout and of stderr
KILL_GRACE_S = 10.0
POLL_S = 0.1
DOCKER_FAILED = 125  # `docker run` exit code when Docker itself may have failed

# The only host variables a local-mode command sees. Never API keys or tokens.
LOCAL_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
)

Mode = Literal["docker", "local"]

if sys.platform == "win32":
    _GROUP_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    _GROUP_FLAGS = 0


class SandboxError(RuntimeError):
    """The sandbox could not run the command (as opposed to the command failing)."""


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeout_s: float = Field(default=300.0, gt=0, le=1800)
    cpus: float = Field(default=1.0, gt=0, le=8)
    memory_mb: int = Field(default=1024, ge=128, le=8192)
    pids: int = Field(default=256, ge=16, le=4096)
    max_output_bytes: int = Field(default=10_000_000, ge=OUTPUT_LIMIT, le=1_000_000_000)


class SandboxResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Mode
    isolated: bool
    command: list[str]
    exit_code: int | None  # None when the sandbox killed the command
    timed_out: bool
    output_overflow: bool  # killed for printing more than max_output_bytes
    stdout: str
    stderr: str
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class _Outcome(NamedTuple):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    output_overflow: bool
    duration_s: float


Killer = Callable[["subprocess.Popen[bytes]"], None]


# --- docker plumbing --------------------------------------------------------


def _docker_exe() -> str:
    exe = shutil.which("docker")
    if exe is None:
        raise SandboxError(
            "docker CLI not found on PATH; install Docker, or pass mode='local' "
            "to run without isolation"
        )
    return exe


def _docker(args: Sequence[str], timeout_s: float = 60.0) -> subprocess.CompletedProcess[str]:
    try:
        # Argument list, no shell; this module's job is to start processes.
        return subprocess.run(  # noqa: S603
            [_docker_exe(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"`docker {args[0]}` did not finish within {timeout_s:.0f}s") from exc
    except OSError as exc:
        raise SandboxError(f"could not run docker: {exc}") from exc


def image_tag(root: Path = REPO_ROOT) -> str:
    """Tag the image by the hash of everything baked into it, so a new lock means a new image."""
    digest = hashlib.sha256()
    for path in (root / DOCKERFILE, root / "pyproject.toml", root / "uv.lock"):
        digest.update(path.read_bytes())
    return f"{IMAGE_NAME}:{digest.hexdigest()[:12]}"


def build_image(root: Path = REPO_ROOT) -> str:
    """Build the sandbox image unless this exact one exists. Returns its tag."""
    tag = image_tag(root)
    if _docker(["image", "inspect", tag]).returncode == 0:
        return tag
    proc = _docker(["build", "-f", str(root / DOCKERFILE), "-t", tag, str(root)], 900.0)
    if proc.returncode != 0:
        raise SandboxError(f"docker build failed for {tag}:\n{_tail_text(proc.stderr)}")
    return tag


def _container_user() -> str:
    # On Linux, run as the host user so the bind-mounted workspace stays writable
    # and owned by them; never as root. If the host user IS root, fall back to the
    # image's user, which then needs a workspace it can write (runs/ creates one).
    # Docker Desktop maps bind-mount ownership itself.
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is not None and getgid is not None and getuid() != 0:
        return f"{getuid()}:{getgid()}"
    return FALLBACK_USER


def docker_run_args(
    workspace: Path, command: Sequence[str], image: str, limits: Limits, name: str
) -> list[str]:
    """Every isolation flag in one place, so it can be read and tested as a list."""
    source = workspace.resolve()
    if "," in str(source):
        raise SandboxError(f"workspace path {source} contains a comma, which --mount cannot take")
    memory = f"{limits.memory_mb}m"
    # The container also enforces its own deadline, in case the factory itself dies.
    deadline = str(math.ceil(limits.timeout_s + KILL_GRACE_S))
    return [
        "run",
        "--rm",
        "--init",  # reap zombies so they don't count against --pids-limit
        "--name",
        name,
        "--pull",
        "never",
        "--network",
        "none",
        "--cpus",
        str(limits.cpus),
        "--memory",
        memory,
        "--memory-swap",
        memory,  # equal to --memory: no swap on top
        "--pids-limit",
        str(limits.pids),
        "--user",
        _container_user(),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=256m",  # noqa: S108 - a fresh tmpfs inside the container
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--mount",
        f"type=bind,source={source},target={WORKSPACE_MOUNT}",
        "--workdir",
        WORKSPACE_MOUNT,
        image,
        "timeout",
        "-s",
        "KILL",
        deadline,
        *command,
    ]


def _kill_container(name: str) -> Killer:
    def kill(client: subprocess.Popen[bytes]) -> None:
        # Killing the `docker run` client alone would leave the container running.
        try:
            with contextlib.suppress(SandboxError):
                _docker(["kill", name], 30.0)
        finally:
            _kill_tree(client)
        # Covers a container created but never started, which --rm does not remove.
        with contextlib.suppress(SandboxError):
            _docker(["rm", "-f", name], 30.0)

    return kill


# --- process plumbing -------------------------------------------------------


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the process and everything it started, not just the direct child."""
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        subprocess.run(  # noqa: S603 - fixed system binary, argument list
            [str(taskkill), "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        with contextlib.suppress(ProcessLookupError):  # already gone
            os.killpg(proc.pid, signal.SIGKILL)


def _local_env() -> dict[str, str]:
    env = {key: value for key in LOCAL_ENV_KEYS if (value := os.environ.get(key)) is not None}
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # same as the image: no .pyc files in the diff
    return env


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _size(stream: IO[bytes]) -> int:
    return os.fstat(stream.fileno()).st_size


def _tail_text(text: str) -> str:
    if len(text) <= OUTPUT_LIMIT:
        return text
    return f"[... {len(text) - OUTPUT_LIMIT} characters cut ...]\n{text[-OUTPUT_LIMIT:]}"


def _read_tail(stream: IO[bytes]) -> str:
    size = _size(stream)
    stream.seek(max(0, size - OUTPUT_LIMIT))
    text = stream.read().decode("utf-8", errors="replace")
    return text if size <= OUTPUT_LIMIT else f"[... {size - OUTPUT_LIMIT} bytes cut ...]\n{text}"


def _execute(
    argv: Sequence[str],
    cwd: Path | None,
    env: dict[str, str] | None,
    limits: Limits,
    kill: Killer,
) -> _Outcome:
    start = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(  # noqa: S603 - argument list, no shell
                list(argv),
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=sys.platform != "win32",
                creationflags=_GROUP_FLAGS,
            )
        except OSError as exc:
            raise SandboxError(f"could not start {argv[0]!r}: {exc}") from exc
        timed_out = overflow = False
        try:
            while proc.poll() is None:
                if time.monotonic() - start > limits.timeout_s:
                    timed_out = True
                    break
                if _size(out) + _size(err) > limits.max_output_bytes:
                    overflow = True
                    break
                _pause(POLL_S)
        finally:
            # Timeout, too much output, Ctrl-C or any error: never leave it running.
            if proc.poll() is None:
                kill(proc)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=KILL_GRACE_S)
        killed = timed_out or overflow
        return _Outcome(
            exit_code=None if killed else proc.returncode,
            stdout=_read_tail(out),
            stderr=_read_tail(err),
            timed_out=timed_out,
            output_overflow=overflow,
            duration_s=time.monotonic() - start,
        )


# --- public entry point -----------------------------------------------------


def run(
    command: Sequence[str],
    workspace: Path,
    *,
    mode: Mode = "docker",
    limits: Limits | None = None,
    image: str | None = None,
) -> SandboxResult:
    """Run `command` with `workspace` as its working directory and return what happened.

    A failing command is a normal result. SandboxError means the sandbox itself
    could not run it (no Docker, missing image, bad workspace).
    """
    limits = limits or Limits()
    if not command:
        raise SandboxError("command is empty; pass the program and its arguments as a list")
    if not workspace.is_dir():
        raise SandboxError(f"workspace {workspace} is not a directory")

    if mode == "docker":
        name = f"s2s-{uuid.uuid4().hex[:12]}"
        args = docker_run_args(workspace, command, image or build_image(), limits, name)
        outcome = _execute([_docker_exe(), *args], None, None, limits, _kill_container(name))
        # 125 is ambiguous: a command may exit 125 itself. Docker's own errors say "docker:".
        if outcome.exit_code == DOCKER_FAILED and outcome.stderr.lstrip().startswith("docker:"):
            raise SandboxError(f"docker could not start the sandbox:\n{outcome.stderr}")
    else:
        outcome = _execute(command, workspace, _local_env(), limits, _kill_tree)

    return SandboxResult(
        mode=mode,
        isolated=mode == "docker",
        command=list(command),
        exit_code=outcome.exit_code,
        timed_out=outcome.timed_out,
        output_overflow=outcome.output_overflow,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        duration_s=round(outcome.duration_s, 3),
    )
