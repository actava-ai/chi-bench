"""Frozen evaluation evidence requires an independently stopped agent."""

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from chi_bench.experiment import frozen_state


def docker_probe(monkeypatch, *, running=False, project="synthetic-trial", matches=1):
    seen = []
    monkeypatch.setenv("CHI_BENCH_COMPOSE_PROJECT", project)

    def get(path, socket_path):
        seen.append(path)
        if path.startswith("/containers/json?"):
            query = parse_qs(urlsplit(path).query)
            assert query["all"] == ["1"]
            assert json.loads(query["filters"][0]) == {
                "label": [
                    "com.docker.compose.project=" + project,
                    "com.docker.compose.service=main",
                ]
            }
            return [{"Id": "synthetic-main"}] * matches
        if path == "/containers/synthetic-main/json":
            return {"State": {"Running": running, "Status": "running" if running else "exited"}}
        pytest.fail("Container hostnames are not Docker identities under host networking")

    monkeypatch.setattr(frozen_state, "_docker_json", get)
    return seen


@pytest.mark.parametrize("running,matches", [(True, 1), (False, 0), (False, 2)])
def test_uncertain_or_running_main_prevents_snapshot_before_export(
    tmp_path, monkeypatch, running, matches
):
    docker_probe(monkeypatch, running=running, matches=matches)
    monkeypatch.setattr(frozen_state, "urlopen", lambda *a, **kw: pytest.fail("must not export"))
    target = tmp_path / "frozen.json"
    target.write_text('{"stale": true}')
    with pytest.raises(RuntimeError):
        frozen_state.collect_frozen_state(output=target)
    assert not target.exists()


@pytest.mark.parametrize("failure", ["drain", "restart"])
def test_collection_failure_removes_stale_snapshot(tmp_path, monkeypatch, failure):
    docker_probe(monkeypatch)
    target = tmp_path / "frozen.json"
    target.write_text('{"stale": true}')
    token = tmp_path / "token"
    token.write_text("synthetic-token")

    def response(request, timeout):
        if failure == "drain":
            raise TimeoutError("admitted work did not finish")
        return io.BytesIO(b"{}")

    monkeypatch.setattr(frozen_state, "urlopen", response)
    if failure == "restart":
        states = iter(["stopped-main", "different-main"])
        monkeypatch.setattr(frozen_state, "require_stopped_main", lambda *a: next(states))
    with pytest.raises((RuntimeError, TimeoutError)):
        frozen_state.collect_frozen_state(token_path=token, output=target)
    assert not target.exists()


def test_stopped_main_snapshot_has_trusted_boundary_and_no_control_token(tmp_path, monkeypatch):
    docker_probe(monkeypatch)
    token = tmp_path / "token"
    token.write_text("synthetic-private-token")
    target = tmp_path / "frozen.json"
    requests = []

    def urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer synthetic-private-token"
        requests.append(request)
        return io.BytesIO(
            json.dumps(
                {"state": "frozen"} if request.full_url.endswith("/export") else {"ok": True}
            ).encode()
        )

    monkeypatch.setattr(frozen_state, "urlopen", urlopen)
    frozen_state.collect_frozen_state(token_path=token, output=target)
    result = json.loads(target.read_text())
    assert result["state"] == "frozen"
    assert result["_evaluation_boundary"] == {
        "version": 1,
        "main_stopped": True,
        "main_container_id": "synthetic-main",
    }
    assert "synthetic-private-token" not in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(requests[0].data) == {"role": "closed"}


def test_absent_compose_identity_does_not_create_stop_proof(tmp_path, monkeypatch):
    monkeypatch.delenv("CHI_BENCH_COMPOSE_PROJECT", raising=False)
    monkeypatch.setattr(
        frozen_state, "_docker_json", lambda *a, **kw: pytest.fail("must not guess a project")
    )
    with pytest.raises(RuntimeError, match="project"):
        frozen_state.collect_frozen_state(output=tmp_path / "frozen.json")
