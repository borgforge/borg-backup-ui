"""Startup detection is not consent to prepare or apply immutable IDs (#479)."""
MIGRATION_ID = "immutable_job_id_v1"
INTRODUCED_IN = "issue-447"
RECHECK_AFTER_FINAL = True
USER_INITIATED = True


def detect(config):
    from identity_migration_api import get_assistant
    return get_assistant(config).startup_detection()


def apply(config):
    # The central runner can record the gate but cannot authorize conversion.
    detected = detect(config)
    return {"migration_id": MIGRATION_ID, "status": "blocked" if detected["status"] == "blocked" else "pending",
            "details": {"reason": "Explicit migration preparation and separate approval required."}}
