"""Readiness retries can never become migration authorization (#479)."""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import identity_startup_watch as watcher


def assistant(result, **values):
    return SimpleNamespace(_operation=threading.Lock(), _failed_here=False,
                           _busy=False, startup_detection=lambda: result,
                           **values)


@pytest.mark.parametrize("result", [
    {"required": True, "status": "pending"},
    {"required": True, "status": "blocked"},
    {"required": True, "status": "failed"},
    {"required": True, "status": "pending", "stage": "interrupted"},
    {}, None, {"required": 0},
])
def test_pending_interrupted_and_invalid_detection_never_activate(result):
    state = assistant(result)
    observed = watcher.retry_startup_once({}, assistant=state, storage_ready=lambda _: True,
                                         activate=lambda _: pytest.fail("consent bypass"))
    assert observed == "waiting"
    assert state._operation.acquire(blocking=False)
    state._operation.release()


def test_missing_mount_checks_neither_inventory_nor_activation():
    state = assistant({})
    state.startup_detection = lambda: pytest.fail("unavailable mounted data was read")
    assert watcher.retry_startup_once({}, assistant=state, storage_ready=lambda _: False,
        activate=lambda _: pytest.fail("unavailable storage was activated")) == "waiting"


def test_explicit_user_completion_stops_observer_without_duplicate_activation():
    state = assistant({})
    state.startup_detection = lambda: pytest.fail("completed startup was rescanned")
    config = {"_STARTUP_STATE": {"mode": "normal"}}
    assert watcher.retry_startup_once(config, assistant=state,
        storage_ready=lambda _: pytest.fail("completed startup was rechecked"),
        activate=lambda _: pytest.fail("normal services started twice")) == "ready"
    assert state._operation.acquire(blocking=False)
    state._operation.release()


def test_only_no_conversion_can_activate_through_repeated_startup_gate():
    state = assistant({"required": False, "status": "not_applicable"})
    calls = []
    def activate(cfg):
        assert not state._operation.acquire(blocking=False)
        calls.append(cfg)
        return True
    assert watcher.retry_startup_once({"setup": "fresh"}, assistant=state,
        storage_ready=lambda _: True, activate=activate) == "ready"
    assert calls == [{"setup": "fresh"}]


def test_prepare_in_flight_and_failed_apply_cannot_be_retried_automatically():
    state = assistant({"required": False})
    state._operation.acquire()
    assert watcher.retry_startup_once({}, assistant=state, storage_ready=lambda _: True,
        activate=lambda _: pytest.fail("duplicate operation")) == "waiting"
    state._operation.release()
    state._failed_here = True
    assert watcher.retry_startup_once({}, assistant=state, storage_ready=lambda _: True,
        activate=lambda _: pytest.fail("failed migration activated")) == "restart_required"


def test_detection_or_activation_errors_keep_gate_closed():
    state = assistant({"required": False})
    def fail(_):
        raise OSError("confidential diagnostic detail")
    assert watcher.retry_startup_once({}, assistant=state, storage_ready=lambda _: True,
        activate=fail) == "waiting"


def test_background_observer_is_unique_and_stops_after_readiness(tmp_path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    checking = threading.Event()
    finish = threading.Event()
    calls = []
    def retry(cfg, **kwargs):
        calls.append(cfg)
        checking.set()
        assert finish.wait(3)
        return "ready"
    monkeypatch.setattr(watcher, "retry_startup_once", retry)
    first = watcher.start_startup_readiness_watch(config, storage_ready=None, activate=None, interval_seconds=.01)
    try:
        assert checking.wait(3)
        assert watcher.start_startup_readiness_watch(config, storage_ready=None, activate=None) is first
    finally:
        finish.set()
        first.join(timeout=3)
    assert not first.is_alive() and len(calls) == 1
    assert str(tmp_path) not in watcher._WATCHERS
