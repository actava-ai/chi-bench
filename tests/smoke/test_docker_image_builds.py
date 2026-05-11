"""Smoke test: the ci-skeleton Docker image builds cleanly.

Slow -- runs an actual docker build (~3 min). Skipped when docker is not
available (e.g. in CI environments without buildx, or sandboxed runners)
or when ``CHI_BENCH_SKIP_DOCKER_BUILD=1`` is set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.returncode == 0


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon unavailable")
@pytest.mark.skipif(
    os.environ.get("CHI_BENCH_SKIP_DOCKER_BUILD") == "1",
    reason="CHI_BENCH_SKIP_DOCKER_BUILD=1 set",
)
def test_ci_skeleton_target_builds() -> None:
    """Build the ci-skeleton target to a unique tag and confirm it succeeds."""
    tag = "chi-bench:smoke-ci-skeleton-test"
    cmd = [
        "docker",
        "build",
        "-f",
        "docker/Dockerfile",
        "--target",
        "ci-skeleton",
        "-t",
        tag,
        ".",
    ]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.fail(
            "docker build --target ci-skeleton failed\n"
            f"stdout (last 30 lines):\n{os.linesep.join(res.stdout.splitlines()[-30:])}\n"
            f"stderr (last 30 lines):\n{os.linesep.join(res.stderr.splitlines()[-30:])}"
        )
    # Cleanup: remove the image so repeated test runs don't fill the local registry.
    subprocess.run(["docker", "image", "rm", tag], capture_output=True)
