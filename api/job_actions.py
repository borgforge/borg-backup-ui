"""UUID control-plane boundaries and transactions (#447, #474)."""

from copy import deepcopy
import logging

from inventory_store import inventory_lock
from job_model import JobValidationError, validate_job_id
from job_store import read_jobs, read_repositories, validate_assignments, write_transaction


# Temporary HTTP compatibility only. Remove at the final #479 API cutover.
LEGACY_REQUEST_ENDPOINTS = frozenset({
    "jobs/run", "jobs/cancel", "jobs/enabled", "jobs/delete",
    "schedules/save", "schedules/delete",
})


def resolve_request_schedule_id(config, body, *, endpoint):
    if "service" in body:
        if body["service"] != "restore_test" or {"job_id", "job_key"}.intersection(body):
            raise JobValidationError("invalid_schedule_service", "The restore-test service must be addressed separately from job IDs")
        return "restore_test"
    return resolve_request_job_id(config, body, endpoint=endpoint)


def resolve_request_job_id(config, body, *, endpoint):
    from repository_context import jobs_dir
    with inventory_lock(jobs_dir(config).parent):
        jobs = read_jobs(jobs_dir(config))
        job_id = body.get("job_id")
        if "job_id" in body:
            validate_job_id(job_id)
            if job_id not in jobs:
                raise JobValidationError("unknown_job_id", "Unknown job_id")
        if "job_key" in body:
            if endpoint not in LEGACY_REQUEST_ENDPOINTS:
                raise JobValidationError("deprecated_job_key", "This endpoint requires job_id")
            alias = body["job_key"]
            if not isinstance(alias, str) or not alias:
                raise JobValidationError("invalid_job_alias", "An exact legacy alias is required")
            owners = [key for key, job in jobs.items() if alias in job["legacy_job_keys"]]
            if len(owners) != 1:
                raise JobValidationError("unresolved_job_alias", "The legacy alias has no unique owner")
            if job_id is not None and job_id != owners[0]:
                raise JobValidationError("conflicting_job_identity", "job_id and legacy alias address different jobs")
            job_id = owners[0]
            logging.getLogger(__name__).warning("Deprecated job_key request resolved at %s to job_id=%s", endpoint, job_id)
        if job_id is None:
            raise JobValidationError("invalid_job_id", "job_id is required")
        return job_id


def _inventory(config):
    from repository_context import jobs_dir
    from repositories_api import repositories_file
    jobs = read_jobs(jobs_dir(config))
    store = read_repositories(repositories_file(config))
    validate_assignments(jobs, store)
    return jobs, store


def prepare_job_action(config, job_id, *, require_enabled=False):
    from repository_context import jobs_dir, resolve_job_repository_context
    from schedule_api import get_schedules
    validate_job_id(job_id)
    with inventory_lock(jobs_dir(config).parent):
        jobs, _ = _inventory(config)
        get_schedules(config)
        if job_id not in jobs:
            raise JobValidationError("unknown_job_id", "Unknown job_id")
        job = jobs[job_id]
        if require_enabled and not job.get("enabled", True):
            raise JobValidationError("job_disabled", "The job is disabled")
        return resolve_job_repository_context(config, job_id, job=job, require_passphrase_file=False)


def set_job_enabled(config, job_id, enabled):
    from repository_context import jobs_dir
    from schedule_api import get_schedules, schedule_lines, _update_crontab
    if type(enabled) is not bool:
        raise JobValidationError("invalid_job_settings", "enabled must be boolean")
    validate_job_id(job_id)
    with inventory_lock(jobs_dir(config).parent):
        jobs, _ = _inventory(config)
        if job_id not in jobs:
            raise JobValidationError("unknown_job_id", "Unknown job_id")
        schedules = get_schedules(config)
        old_lines = schedule_lines(config, schedules, jobs)
        job = deepcopy(jobs[job_id])
        job["enabled"] = enabled
        jobs[job_id] = job
        new_lines = schedule_lines(config, schedules, jobs)
        write_transaction({jobs_dir(config) / (job_id + ".json"): job},
            after_write=lambda: _update_crontab(new_lines),
            rollback_after=lambda: _update_crontab(old_lines))
        return {"saved": True, "job_id": job_id, "enabled": enabled}


def delete_job_configuration(config, job_id):
    """Remove exactly one job, its reverse links and schedule, preserving artifacts."""
    from repository_context import jobs_dir
    from repositories_api import repositories_file
    from schedule_api import get_schedules, schedule_lines, _update_crontab, _schedules_path
    validate_job_id(job_id)
    with inventory_lock(jobs_dir(config).parent):
        jobs, store = _inventory(config)
        if job_id not in jobs:
            raise JobValidationError("unknown_job_id", "Unknown job_id")
        schedules = get_schedules(config)
        old_lines = schedule_lines(config, schedules, jobs)
        del jobs[job_id]
        schedules.pop(job_id, None)
        for repository in store["repositories"]:
            for field in ("job_ids", "source_job_ids"):
                repository[field] = [value for value in repository[field] if value != job_id]
        validate_assignments(jobs, store)
        new_lines = schedule_lines(config, schedules, jobs)
        write_transaction({
            jobs_dir(config) / (job_id + ".json"): None,
            repositories_file(config): store,
            _schedules_path(config): schedules,
        }, after_write=lambda: _update_crontab(new_lines),
           rollback_after=lambda: _update_crontab(old_lines))
        return {"deleted": True, "job_id": job_id, "deleted_metadata": 1, "deleted_artifacts": False}
