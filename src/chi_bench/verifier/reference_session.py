"""Compose task references inside one already-bootstrapped Marathon world."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any

from chi_bench.core.loaders import (
    load_expectation_definition,
    load_session_manifest,
    load_task_manifest,
)


@contextmanager
def _task_metadata(ctx: Any, fixtures: Path) -> Iterator[None]:
    """Change task metadata, never the world contents or its initialization marker."""
    names = (
        "fixtures_dir",
        "_expectations",
        "_manifest",
        "_scenario",
        "_is_session",
        "task_actor",
        "payer_mode",
    )
    previous = {name: getattr(ctx, name) for name in names}
    manifest = load_task_manifest(fixtures)
    try:
        ctx.fixtures_dir = fixtures
        ctx._manifest = manifest
        ctx._is_session = False
        ctx.task_actor = manifest.task_actor
        ctx.payer_mode = getattr(ctx, "_configured_payer_mode", None) or manifest.payer_mode
        ctx._expectations = None if ctx._cm_loaded else load_expectation_definition(fixtures)
        if ctx._scenario is not None:
            # WorldStore fingerprints explicitly exclude these task metadata
            # fields. Repeated ensure_loaded() therefore preserves all prior work.
            ctx._scenario = ctx._scenario.model_copy(
                update={
                    "scenario_id": manifest.task_id,
                    **{
                        name: getattr(manifest, name)
                        for name in (
                            "task_kind",
                            "task_actor",
                            "payer_mode",
                            "target_case_id",
                            "target_patient_id",
                            "target_order_id",
                            "companion_case_id",
                        )
                    },
                }
            )
        yield
    finally:
        for name, value in previous.items():
            setattr(ctx, name, value)


def run_session_reference(
    ctx: Any, *, run_one: Callable[[Any], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Run constituents in manifest order; a static CM collection stays static.

    The host freezes an executed session once, after this function returns.
    Neither constituent execution nor static answer assembly starts a verifier.
    """
    from chi_bench.verifier.reference_oracle import run_reference

    execute = run_one or run_reference
    root = ctx.fixtures_dir
    manifest = load_session_manifest(root)
    task_ids = [entry.task_id for entry in manifest.tasks]
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("Reference session requires distinct constituent tasks")
    for task_id in task_ids:
        if Path(task_id).name != task_id or task_id in {".", ".."}:
            raise ValueError("Reference session requires leaf task IDs")
        task = root / "tasks" / task_id
        load_task_manifest(task)
        json.loads((task / "expectations.json").read_text(encoding="utf-8"))

    results = []
    for task_id in task_ids:
        with _task_metadata(ctx, root / "tasks" / task_id):
            result = execute(ctx)
        results.append({**result, "task_id": task_id})
    executed = all(result.get("executed") is True for result in results)
    static = all(
        result.get("executed") is False and result.get("reference_mode") == "static_answer"
        for result in results
    )
    if not executed and not static:
        raise RuntimeError("A reference session cannot mix executed workflows and static answers")
    common = {
        "executed": executed,
        "reference_mode": "executed_session" if executed else "static_answer",
        "session_id": manifest.session_id,
        "semantic_verification": "not_run",
    }
    if executed:
        return {**common, "tasks": results}
    return {
        **common,
        "answer": {
            "tasks": [
                {"task_id": result["task_id"], "answer": result["answer"]} for result in results
            ]
        },
        "tasks": [{"task_id": result["task_id"], "executed": False} for result in results],
        "authorship": {
            "kind": "authored_ideal_path_collection",
            "observed": False,
            "simulator_run": False,
            "verifier_run": False,
        },
    }
