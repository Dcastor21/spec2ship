"""Sandbox runner (T1.4): unit tests that need no Docker daemon.

The isolation itself is proven against a real daemon in test_sandbox_docker.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from factory import sandbox
from factory.sandbox import (
    FALLBACK_USER,
    OUTPUT_LIMIT,
    REPO_ROOT,
    Limits,
    SandboxError,
    build_image,
    docker_run_args,
    image_tag,
    run,
)

PY = sys.executable


def flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


# --- docker command line ----------------------------------------------------


def test_docker_args_carry_every_isolation_flag(tmp_path: Path) -> None:
    limits = Limits(cpus=0.5, memory_mb=256, pids=64)
    args = docker_run_args(tmp_path, ["pytest", "-q"], "img:tag", limits, "s2s-test")
    assert args[:2] == ["run", "--rm"]
    assert flag(args, "--network") == "none"
    assert flag(args, "--pull") == "never"
    assert flag(args, "--cpus") == "0.5"
    assert flag(args, "--memory") == flag(args, "--memory-swap") == "256m"
    assert flag(args, "--pids-limit") == "64"
    assert flag(args, "--cap-drop") == "ALL"
    assert flag(args, "--security-opt") == "no-new-privileges"
    assert "--read-only" in args
    assert flag(args, "--user").split(":")[0] not in {"0", "root"}
    assert flag(args, "--mount") == f"type=bind,source={tmp_path.resolve()},target=/workspace"
    assert "--init" in args
    # The container enforces its own deadline too: timeout + grace, killed hard.
    assert args[-7:] == ["img:tag", "timeout", "-s", "KILL", "310", "pytest", "-q"]


def test_workspace_path_with_comma_is_refused(tmp_path: Path) -> None:
    odd = tmp_path / "a,b"
    odd.mkdir()
    with pytest.raises(SandboxError, match="comma"):
        docker_run_args(odd, ["true"], "img", Limits(), "n")


@pytest.mark.parametrize(("uid", "expected"), [(0, FALLBACK_USER), (1000, "1000:1000")])
def test_container_never_runs_as_root(
    monkeypatch: pytest.MonkeyPatch, uid: int, expected: str
) -> None:
    monkeypatch.setattr(os, "getuid", lambda: uid, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    assert sandbox._container_user() == expected


# --- image build ------------------------------------------------------------


def completed(code: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, "", stderr)


def test_image_tag_changes_with_the_lock_file(tmp_path: Path) -> None:
    for rel in ("docker/sandbox.Dockerfile", "pyproject.toml", "uv.lock"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, tmp_path / rel)
    before = image_tag(tmp_path)
    (tmp_path / "uv.lock").write_text("changed", encoding="utf-8")
    assert image_tag(tmp_path) != before
    assert before.startswith("spec2ship-sandbox:")


def test_existing_image_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake(args: list[str], timeout_s: float = 60.0) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return completed(0)

    monkeypatch.setattr(sandbox, "_docker", fake)
    assert build_image() == image_tag()
    assert [call[0] for call in calls] == ["image"]


def test_failed_build_raises_with_dockers_output(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter([completed(1), completed(1, "no space left on device")])
    monkeypatch.setattr(sandbox, "_docker", lambda args, timeout_s=60.0: next(replies))
    with pytest.raises(SandboxError, match="no space left on device"):
        build_image()


def test_hung_docker_call_is_a_sandbox_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("docker", 60)

    monkeypatch.setattr(sandbox.subprocess, "run", hang)
    with pytest.raises(SandboxError, match="did not finish within 60s"):
        sandbox._docker(["image", "inspect", "x"])


def test_unrunnable_docker_is_a_sandbox_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(sandbox.subprocess, "run", broken)
    with pytest.raises(SandboxError, match="could not run docker: access denied"):
        sandbox._docker(["version"])


def test_container_kill_still_kills_the_client_when_docker_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[object] = []

    def failing_docker(args: list[str], timeout_s: float = 60.0) -> None:
        raise SandboxError("docker hung")

    monkeypatch.setattr(sandbox, "_docker", failing_docker)
    monkeypatch.setattr(sandbox, "_kill_tree", killed.append)
    client = object()
    sandbox._kill_container("s2s-x")(client)  # type: ignore[arg-type]
    assert killed == [client]


def test_missing_docker_cli_points_at_local_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)
    with pytest.raises(SandboxError, match="mode='local'"):
        run(["true"], tmp_path, image="img:tag")


# --- argument checks --------------------------------------------------------


def test_empty_command_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="command is empty"):
        run([], tmp_path, mode="local")


def test_missing_workspace_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="not a directory"):
        run([PY, "-V"], tmp_path / "nope", mode="local")


def test_missing_program_is_a_sandbox_error(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="could not start 'no-such-program-s2s'"):
        run(["no-such-program-s2s"], tmp_path, mode="local")


def test_limits_reject_a_zero_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        Limits(timeout_s=0)


# --- local mode -------------------------------------------------------------


def test_local_run_reports_output_and_is_marked_unisolated(tmp_path: Path) -> None:
    result = run([PY, "-c", "import os; print(os.getcwd())"], tmp_path, mode="local")
    assert result.ok
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()
    assert (result.mode, result.isolated, result.timed_out) == ("local", False, False)
    assert result.duration_s > 0


def test_local_run_reports_failure(tmp_path: Path) -> None:
    code = "import sys; print('boom', file=sys.stderr); sys.exit(3)"
    result = run([PY, "-c", code], tmp_path, mode="local")
    assert (result.exit_code, result.ok) == (3, False)
    assert "boom" in result.stderr


def test_local_mode_does_not_leak_host_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("S2S_TEST_SECRET", "sk-should-not-leak")
    code = "import os; print(os.environ.get('S2S_TEST_SECRET', 'absent'))"
    result = run([PY, "-c", code], tmp_path, mode="local")
    assert result.stdout.strip() == "absent"


def test_output_flood_is_stopped_not_buffered(tmp_path: Path) -> None:
    code = "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)"
    limits = Limits(timeout_s=60, max_output_bytes=2_000_000)
    result = run([PY, "-c", code], tmp_path, mode="local", limits=limits)
    assert result.output_overflow
    assert (result.timed_out, result.exit_code) == (False, None)
    assert result.duration_s < 30
    assert len(result.stdout) < OUTPUT_LIMIT + 100


def test_long_output_keeps_the_tail(tmp_path: Path) -> None:
    code = f"print('a' * {OUTPUT_LIMIT + 500} + 'END')"
    result = run([PY, "-c", code], tmp_path, mode="local")
    assert result.stdout.startswith("[... ")
    assert result.stdout.rstrip().endswith("END")
    assert len(result.stdout) < OUTPUT_LIMIT + 100


CHILD = """
import time
while True:
    with open("beat.txt", "a") as f:
        f.write("x")
    time.sleep(0.05)
"""

PARENT = """
import subprocess, sys, time
subprocess.Popen([sys.executable, "child.py"])
time.sleep(60)
"""


def test_local_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    (tmp_path / "child.py").write_text(CHILD, encoding="utf-8")
    (tmp_path / "parent.py").write_text(PARENT, encoding="utf-8")
    result = run([PY, "parent.py"], tmp_path, mode="local", limits=Limits(timeout_s=2))
    assert result.timed_out
    assert result.exit_code is None
    assert result.duration_s < 15
    beat = tmp_path / "beat.txt"
    assert beat.exists(), "the grandchild never started, so the test proves nothing"
    size = beat.stat().st_size
    time.sleep(0.6)
    assert beat.stat().st_size == size, "the grandchild outlived the timeout"


def test_interrupt_mid_run_kills_the_whole_process_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Ctrl-C while the factory waits must not leave the command running.
    (tmp_path / "child.py").write_text(CHILD, encoding="utf-8")
    (tmp_path / "parent.py").write_text(PARENT, encoding="utf-8")
    beat = tmp_path / "beat.txt"

    def pause(seconds: float) -> None:
        if beat.exists():
            raise KeyboardInterrupt
        time.sleep(seconds)

    monkeypatch.setattr(sandbox, "_pause", pause)
    with pytest.raises(KeyboardInterrupt):
        run([PY, "parent.py"], tmp_path, mode="local", limits=Limits(timeout_s=60))
    size = beat.stat().st_size
    time.sleep(0.6)
    assert beat.stat().st_size == size, "the grandchild outlived the interrupt"
