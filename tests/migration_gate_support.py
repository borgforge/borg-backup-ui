"""Explicit normal-startup fixture for tests of already-running services."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


def ready_gate(config, monkeypatch, gate_root):
    """Model successful startup verification; never use for migration inputs."""
    import migration_barrier as barrier
    monkeypatch.setenv("BORG_UI_MIGRATION_GATE_ROOT", str(gate_root))
    root = barrier.data_root(config)
    root.mkdir(parents=True, exist_ok=True)
    barrier.block_writers(config)
    with barrier.exclusive_migration(config):
        barrier.clear_block(config)

