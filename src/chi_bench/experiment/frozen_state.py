"""Collect trusted benchmark evidence only after Docker confirms main stopped."""

from __future__ import annotations

import http.client
import json
import os
import socket
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BOUNDARY_KEY = "_evaluation_boundary"


class _DockerConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost", timeout=10)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _docker_json(path: str, socket_path: str):
    connection = _DockerConnection(socket_path)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(
                f"Could not confirm the agent container state (HTTP {response.status})"
            )
        return json.load(response)
    finally:
        connection.close()


def require_stopped_main(socket_path: str = "/var/run/docker.sock") -> str:
    # Compose injects its resolved project into this trusted service. Host
    # networking can inherit a host name that is not a Docker container ID.
    project = os.environ.get("CHI_BENCH_COMPOSE_PROJECT")
    if not project:
        raise RuntimeError("Cannot establish the trusted Compose project identity")
    query = urlencode(
        {
            "all": "1",
            "filters": json.dumps(
                {
                    "label": [
                        "com.docker.compose.project=" + project,
                        "com.docker.compose.service=main",
                    ]
                }
            ),
        }
    )
    containers = _docker_json("/containers/json?" + query, socket_path)
    if not isinstance(containers, list) or len(containers) != 1:
        raise RuntimeError("Cannot identify exactly one agent container")
    identity = containers[0]["Id"]
    state = _docker_json("/containers/" + quote(identity, safe="") + "/json", socket_path).get(
        "State", {}
    )
    if state.get("Running") is not False or state.get("Status") not in ("exited", "dead"):
        raise RuntimeError("Agent container has not stopped; refusing to freeze evaluation state")
    return identity


def collect_frozen_state(
    *,
    token_path: Path = Path("/run/chi-bench/control-token"),
    output: Path = Path("/logs/artifacts/final-state.json"),
    socket_path: str = "/var/run/docker.sock",
) -> None:
    # A failed collection cannot leave a previous snapshot usable by a retry.
    output.unlink(missing_ok=True)
    identity = require_stopped_main(socket_path)
    token = token_path.read_text().strip()
    if not token:
        raise RuntimeError("Missing trusted control token")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    request = Request(
        "http://localhost:8023/_admin/agent_role",
        data=b'{"role":"closed"}',
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=135) as response:
        json.load(response)
    with urlopen(Request("http://localhost:8023/export", headers=headers), timeout=60) as response:
        state = json.load(response)
    if not isinstance(state, dict):
        raise RuntimeError("Invalid frozen simulator state")
    if require_stopped_main(socket_path) != identity:
        raise RuntimeError("Agent container identity changed during collection")
    state[BOUNDARY_KEY] = {"version": 1, "main_stopped": True, "main_container_id": identity}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(output)
