"""The dataset-viewer index identifies sessions and counts fixture files."""

import hashlib
import json

import pytest


def make_task(root, relative, task_id="child-task", session_id=None):
    task = root / relative
    (task / "fixtures").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "task.toml").write_text(
        f'[metadata]\ntask_id = "{task_id}"\n[agent]\ntimeout_sec = 1800\n'
    )
    (task / "instruction.md").write_text("# Synthetic task\n\nComplete the synthetic workflow.\n")
    (task / "tests/expectations.json").write_text(
        json.dumps(
            {"task_kind": "synthetic", "task_actor": "payer", "expected_target_status": "denied"}
        )
    )
    if session_id:
        (task / "fixtures/session_manifest.json").write_text(json.dumps({"session_id": session_id}))
    return task


def file_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_fixture_count_includes_files_and_excludes_directories(tmp_path):
    from scripts import build_tasks_jsonl

    task = make_task(tmp_path, "prior_auth_um/tasks/synthetic")
    (task / "fixtures/nested/empty").mkdir(parents=True)
    (task / "fixtures/nested/input.PDF").write_bytes(b"synthetic PDF")
    (task / "fixtures/facts.json").write_text("{}")

    row = build_tasks_jsonl.build_row(task / "task.toml", tmp_path)

    assert row["num_fixture_files"] == 2
    assert row["num_input_pdfs"] == 1


@pytest.mark.parametrize("domain", ["care_management", "prior_auth_provider", "prior_auth_um"])
def test_marathon_identity_comes_from_its_session_manifest(tmp_path, domain):
    from scripts import build_tasks_jsonl

    session_id = f"{domain}_session_v1"
    task = make_task(tmp_path, f"marathon/{domain}", task_id="child-task", session_id=session_id)

    row = build_tasks_jsonl.build_row(task / "task.toml", tmp_path)

    assert row["task_id"] == session_id
    assert row["path"] == f"marathon/{domain}"


def test_marathon_without_manifest_has_a_namespaced_session_identity(tmp_path):
    from scripts import build_tasks_jsonl

    task = make_task(tmp_path, "marathon/care_management", task_id="child-task")
    row = build_tasks_jsonl.build_row(task / "task.toml", tmp_path)
    assert row["task_id"] == "marathon_care_management"


def test_index_discovery_excludes_marathon_child_task_tomls(tmp_path):
    from scripts import build_tasks_jsonl

    make_task(tmp_path, "care_management/tasks/child-task", task_id="child-task")
    make_task(tmp_path, "marathon/care_management", session_id="care_management_session_v1")
    make_task(tmp_path, "marathon/care_management/fixtures/tasks/child-task", task_id="child-task")
    make_task(tmp_path, "unrelated/tasks/other", task_id="other")

    rows = build_tasks_jsonl.build_rows(tmp_path)

    assert [row["task_id"] for row in rows] == ["child-task", "care_management_session_v1"]
    assert len({row["task_id"] for row in rows}) == len(rows)


def test_regeneration_preserves_task_files_and_current_local_repairs(tmp_path):
    from scripts import build_tasks_jsonl

    task = make_task(tmp_path, "prior_auth_um/tasks/synthetic")
    before = file_hashes(task)
    output = tmp_path / "tasks.jsonl"
    output.write_text('{"stale":true}\n')

    assert build_tasks_jsonl.main([str(tmp_path), "-o", str(output)]) == 0
    first = output.read_bytes()
    row = json.loads(first)
    assert row["expected_target_status"] == "denied"
    assert row["task_kind"] == "synthetic"
    assert row["task_actor"] == "payer"
    assert row["title"] == "Synthetic task"
    assert row["agent_timeout_sec"] == 1800
    assert file_hashes(task) == before
    assert build_tasks_jsonl.main([str(tmp_path), "-o", str(output)]) == 0
    assert output.read_bytes() == first


def test_duplicate_normal_task_ids_leave_the_existing_index_untouched(tmp_path):
    from scripts import build_tasks_jsonl

    make_task(tmp_path, "prior_auth_um/tasks/first", task_id="duplicate")
    make_task(tmp_path, "prior_auth_um/tasks/second", task_id="duplicate")
    output = tmp_path / "tasks.jsonl"
    output.write_text("existing index\n")

    with pytest.raises(ValueError, match="Duplicate task_id"):
        build_tasks_jsonl.main([str(tmp_path)])

    assert output.read_text() == "existing index\n"


@pytest.mark.parametrize(
    "broken_file", ["task.toml", "tests/expectations.json", "fixtures/session_manifest.json"]
)
def test_invalid_source_metadata_leaves_the_existing_index_untouched(tmp_path, broken_file):
    from scripts import build_tasks_jsonl

    task = make_task(tmp_path, "marathon/care_management", session_id="care_management_session_v1")
    (task / broken_file).write_text("INVALID {")
    output = tmp_path / "tasks.jsonl"
    output.write_text("existing index\n")

    with pytest.raises((ValueError, json.JSONDecodeError)):
        build_tasks_jsonl.main([str(tmp_path)])

    assert output.read_text() == "existing index\n"


def test_default_data_root_supports_tracked_and_downloaded_script_locations(tmp_path, monkeypatch):
    from scripts import build_tasks_jsonl

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\n")
    monkeypatch.setattr(
        build_tasks_jsonl, "__file__", str(checkout / "scripts/build_tasks_jsonl.py")
    )
    assert build_tasks_jsonl.default_data_root() == checkout / "data"

    monkeypatch.setattr(
        build_tasks_jsonl, "__file__", str(checkout / "data/scripts/build_tasks_jsonl.py")
    )
    assert build_tasks_jsonl.default_data_root() == checkout / "data"


def test_wrong_dataset_root_cannot_replace_an_existing_index_with_zero_rows(tmp_path):
    from scripts import build_tasks_jsonl

    output = tmp_path / "tasks.jsonl"
    output.write_text("existing index\n")

    with pytest.raises(ValueError, match="No supported tasks"):
        build_tasks_jsonl.main([str(tmp_path)])

    assert output.read_text() == "existing index\n"


def test_repair_index_updates_only_identity_and_fixture_count(tmp_path):
    from scripts import build_tasks_jsonl

    make_task(tmp_path, "marathon/care_management", session_id="care_management_session_v1")
    current = build_tasks_jsonl.build_rows(tmp_path)[0]
    baseline = {
        **current,
        "task_id": "child-task",
        "num_fixture_files": 999,
        "expected_target_status": "previously-published-status",
        "instruction_excerpt": "Previously published instruction.",
        "unrelated_field": "preserve this too",
    }
    output = tmp_path / "tasks.jsonl"
    output.write_text(json.dumps(baseline) + "\n")

    assert build_tasks_jsonl.main([str(tmp_path), "--repair-index"]) == 0

    repaired = json.loads(output.read_text())
    assert repaired == {
        **baseline,
        "task_id": "care_management_session_v1",
        "num_fixture_files": current["num_fixture_files"],
    }


def test_repair_index_rejects_changed_task_membership_without_replacing_index(tmp_path):
    from scripts import build_tasks_jsonl

    make_task(tmp_path, "prior_auth_um/tasks/synthetic")
    output = tmp_path / "tasks.jsonl"
    original = json.dumps({"path": "prior_auth_um/tasks/other", "task_id": "other"}) + "\n"
    output.write_text(original)

    with pytest.raises(ValueError, match="same task paths"):
        build_tasks_jsonl.main([str(tmp_path), "--repair-index"])

    assert output.read_text() == original
