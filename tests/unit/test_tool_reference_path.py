"""The path advertised by published tasks follows runtime reference selection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("per_task", [True, False], ids=["provider", "care-management"])
@pytest.mark.parametrize("separator", [".", "__"], ids=["default-names", "rewritten-names"])
def test_advertised_tool_reference_path(tmp_path: Path, per_task: bool, separator: str) -> None:
    canonical = tmp_path / "opt/chi-bench-task-assets/tool_reference.md"
    advertised = tmp_path / "opt/healthverse-task-assets/tool_reference.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("Shared reference: cm_chart.get_member\nreport.v1.pdf\n")

    task_dir = tmp_path / "tasks/task"
    task_dir.mkdir(parents=True)
    if per_task:
        (task_dir / "tool_reference.md").write_text(
            "Task reference: chart.get_patient\nreport.v1.pdf\n"
        )

    # Execute the Dockerfile's asset setup, redirecting /opt into this test's
    # filesystem. The shared file above stands in for its COPY instruction.
    dockerfile = (REPO_ROOT / "docker/Dockerfile").read_text()
    asset_setup = dockerfile.split("RUN mkdir -p /opt/chi-bench-task-assets\n", 1)[1]
    asset_setup = asset_setup.split("COPY docker/entrypoint.sh", 1)[0]
    for line in asset_setup.splitlines():
        if line.startswith("RUN "):
            subprocess.run(
                ["sh", "-ec", line[4:].replace("/opt/", f"{tmp_path}/opt/")],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

    # Run the actual reference-selection and rewriting block without starting
    # the simulator. No Docker daemon, downloaded dataset, or API key is needed.
    entrypoint = (REPO_ROOT / "docker/entrypoint.sh").read_text()
    setup = "TOOL_REF_SRC=" + entrypoint.split("TOOL_REF_SRC=", 1)[1]
    setup = setup.split("# In docker-compose mode", 1)[0]
    subprocess.run(
        ["sh", "-ec", setup.replace("/opt/", f"{tmp_path}/opt/")],
        env={
            **os.environ,
            "TASKS_ROOT": str(task_dir.parent),
            "TASK_ID": task_dir.name,
            "CHI_BENCH_MCP_TOOL_SEP": separator,
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert advertised.is_file(), "The tool-reference path in task instructions is unreadable"
    expected = (
        f"Task reference: chart{separator}get_patient\nreport.v1.pdf\n"
        if per_task
        else f"Shared reference: cm_chart{separator}get_member\nreport.v1.pdf\n"
    )
    assert advertised.read_text() == expected
    assert advertised.read_bytes() == canonical.read_bytes()
