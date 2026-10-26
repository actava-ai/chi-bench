from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from threading import Event

import pytest

from chi_bench.core.models import AuditLog
from chi_bench.core.store import WorldStore


@pytest.mark.parametrize("side", ["provider", "payer"])
@pytest.mark.parametrize("operation", ["save", "get", "list", "save_order", "delete", "audit"])
def test_reconnect_waits_for_resource_and_audit_operations(tmp_path, monkeypatch, side, operation):
    store = WorldStore(tmp_path)
    store.save_resource(side, "synthetic", "item", {"id": "item"})
    closed = Event()
    reopen = Event()
    started = Event()
    open_connections = store._open_connections

    def paused_open():
        closed.set()
        assert reopen.wait(5)
        open_connections()

    def read_or_write():
        started.set()
        if operation == "save":
            store.save_resource(side, "synthetic", "next", {"id": "next"})
        elif operation == "get":
            assert store.get_resource(side, "synthetic", "item") == {"id": "item"}
        elif operation == "list":
            assert store.list_resources(side, "synthetic") == [{"id": "item"}]
        elif operation == "save_order":
            assert store.list_resources_in_save_order(side, "synthetic") == [{"id": "item"}]
        elif operation == "delete":
            store.delete_resource(side, "synthetic", "item")
        else:
            store.append_audit(
                AuditLog(
                    actor="synthetic",
                    app="test",
                    action="read",
                    created_at=datetime(2026, 1, 1),
                )
            )
            assert len(store.list_audit_logs()) == 1

    monkeypatch.setattr(store, "_open_connections", paused_open)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reconnect = executor.submit(store._reopen_connections)
            assert closed.wait(5)
            access = executor.submit(read_or_write)
            try:
                assert started.wait(5)
                with pytest.raises(TimeoutError):
                    access.result(timeout=0.05)
            finally:
                reopen.set()
            reconnect.result(timeout=5)
            access.result(timeout=5)
    finally:
        store.close()
