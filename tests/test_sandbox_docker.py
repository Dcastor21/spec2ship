"""Sandbox runner (T1.4) against a real Docker daemon. Run with: uv run pytest -m docker

These prove invariant 3: no network, a timeout, resource limits, non-root.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from factory.sandbox import Limits, SandboxError, build_image, run

pytestmark = pytest.mark.docker


@pytest.fixture(scope="session")
def image() -> str:
    return build_image()


def docker_ps(*args: str) -> list[str]:
    docker = shutil.which("docker")
    assert docker is not None
    out = subprocess.run(  # noqa: S603 - test helper, fixed argument list
        [docker, "ps", "-aq", *args], capture_output=True, text=True, check=True
    ).stdout
    return out.split()


def test_runs_in_the_workspace_as_non_root_with_target_deps(image: str, tmp_path: Path) -> None:
    code = "import os, fastapi; open('out.txt', 'w').write('hi'); print(os.getuid())"
    result = run(["python", "-c", code], tmp_path, image=image)
    assert result.ok, result.stderr
    assert (result.mode, result.isolated) == ("docker", True)
    assert int(result.stdout.strip()) != 0
    assert (tmp_path / "out.txt").read_text() == "hi"


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        (
            "import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)",
            "OSError: [Errno 101] Network is unreachable",
        ),
        (
            "import socket; socket.getaddrinfo('pypi.org', 443)",
            "socket.gaierror: [Errno -3] Temporary failure in name resolution",
        ),
    ],
    ids=["connect", "dns"],
)
def test_network_calls_fail(image: str, tmp_path: Path, code: str, failure: str) -> None:
    result = run(["python", "-c", code], tmp_path, image=image, limits=Limits(timeout_s=30))
    assert not result.timed_out  # refused at once, not hanging on a dropped packet
    assert result.exit_code == 1
    assert result.stderr.strip().splitlines()[-1] == failure


def test_timeout_kills_the_container(image: str, tmp_path: Path) -> None:
    result = run(["sleep", "120"], tmp_path, image=image, limits=Limits(timeout_s=3))
    assert result.timed_out
    assert result.exit_code is None
    assert result.duration_s < 60
    for _ in range(40):  # --rm removes the killed container shortly after
        if not docker_ps("--filter", f"ancestor={image}"):
            break
        time.sleep(0.25)
    assert docker_ps("--filter", f"ancestor={image}") == []


def test_memory_limit_is_applied(image: str, tmp_path: Path) -> None:
    result = run(
        ["cat", "/sys/fs/cgroup/memory.max"], tmp_path, image=image, limits=Limits(memory_mb=256)
    )
    assert result.ok, result.stderr
    assert result.stdout.strip() == str(256 * 1024 * 1024)


def test_root_filesystem_is_read_only(image: str, tmp_path: Path) -> None:
    code = "open('/opt/venv/planted.py', 'w').write('x')"
    result = run(["python", "-c", code], tmp_path, image=image)
    assert not result.ok
    assert "Read-only file system" in result.stderr


def test_container_has_no_network_interface_but_loopback(image: str, tmp_path: Path) -> None:
    result = run(["ls", "/sys/class/net"], tmp_path, image=image)
    assert result.ok, result.stderr
    assert result.stdout.split() == ["lo"]


def test_command_exiting_125_is_a_normal_failure(image: str, tmp_path: Path) -> None:
    # 125 is also Docker's own failure code; only Docker's "docker:" errors raise.
    result = run(["python", "-c", "import sys; sys.exit(125)"], tmp_path, image=image)
    assert result.exit_code == 125


def test_missing_image_is_a_sandbox_error(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="could not start"):
        run(["true"], tmp_path, image="spec2ship-sandbox:does-not-exist")
