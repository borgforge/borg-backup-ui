"""Shared backup launch path for individual and grouped starts (#570)."""

import sys
from pathlib import Path
from lifecycle_log import emit_lifecycle


def start_backup(config, job_key, *, app_version="", request_id="", source="manual", actor="",
                 run_id=None, group_env=None, inherited_fds=(), state_sink=None):
    """Validate and launch one ordinary backup, returning its immutable run ID.

    Missing/disabled jobs and duplicate active jobs raise before launch. Internal
    group callers may preallocate the run ID and inherit their group guard FD;
    repository locks, hooks and job configuration retain their usual behavior.
    ``state_sink`` optionally captures the exact subprocess state for a caller
    awaiting completion, independent of subsequent starts of the same job.
    """
    from jobs_api import JobManager, discover_jobs, get_job_runtime_state, resolve_data_root, resolve_scripts_dir
    borg_scripts_dir = resolve_scripts_dir(config)
    backup_scripts_dir = Path(config["BACKUP_SCRIPTS_DIR"])
    data_root = resolve_data_root(config)
    jobs = {j.key: j for j in discover_jobs(borg_scripts_dir, data_root)}
    if job_key not in jobs:
        raise ValueError(f"Unknown job: {job_key}")
    if not jobs[job_key].enabled:
        raise RuntimeError(f"Job is disabled: {job_key}")
    if get_job_runtime_state(config, job_key).get("running"):
        raise RuntimeError("Job is already running")

    info = jobs[job_key]
    if info.standard != "wizard":
        raise RuntimeError(f"Unsupported job standard: {info.standard}")
    runner = Path(__file__).resolve().parent / "wizard_runner.py"
    extra_env = {
        "BORG_UI_BORG_SCRIPTS_DIR": str(borg_scripts_dir),
        "BORG_UI_JOB_KEY": job_key,
        "BORG_UI_JOB_NAME": info.name or info.display_name,
        "BORG_UI_JOB_LOCATION": info.location,
        "BORG_UI_APP_VERSION": app_version,
        "BORG_UI_REQUEST_ID": request_id,
        "BORG_UI_REQUEST_SOURCE": source,
        "BORG_UI_REQUEST_ACTOR": actor,
        "BORG_UI_FILE_ACTIVITY_RUN": "1" if getattr(info, "file_activity", False) else "0",
    }
    extra_env.update(group_env or {})
    if extra_env["BORG_UI_FILE_ACTIVITY_RUN"] == "1":
        from jobs_api import _runtime_log_dir
        extra_env["BORG_UI_ACTIVITY_LOG_DIR"] = str(_runtime_log_dir(config))
    captured_state = state_sink if state_sink is not None else {}
    ok, err = JobManager.get().start(
        job_key,
        [sys.executable, "-E", "-s", "-S", "-B", str(runner)],
        backup_scripts_dir,
        extra_env=extra_env, run_id=run_id, inherited_fds=inherited_fds, state_sink=captured_state,
    )
    if not ok:
        raise RuntimeError(err)
    launched_run_id = captured_state["state"].run_id
    emit_lifecycle(
        "JOB",
        "requested",
        request_id=request_id,
        source=source,
        actor=actor,
        job_key=job_key,
        backup_type=info.backup_type,
        location=info.location,
        run_id=launched_run_id,
        group_id=(group_env or {}).get("BORG_UI_GROUP_ID", ""),
        group_run_id=(group_env or {}).get("BORG_UI_GROUP_RUN_ID", ""),
    )
    return {"started": True, "job_key": job_key, "run_id": launched_run_id}
