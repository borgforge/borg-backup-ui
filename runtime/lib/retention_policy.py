"""Validated job retention and Borg arguments shared by both prune paths (#459)."""

import re

PERIOD_DEFAULTS = {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"}
PERIODS = ("hourly", *PERIOD_DEFAULTS)
MAX_COUNT = 1_000_000


class RetentionError(ValueError):
    def __init__(self, message, code="retention_invalid"):
        super().__init__(message)
        self.api_code = code


def _count(value):
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,7}", raw) or int(raw) > MAX_COUNT:
        raise RetentionError("Job retention values must be non-negative whole numbers (at most 1000000)")
    return str(int(raw))


def normalize_retention(source):
    if not isinstance(source, dict):
        raise RetentionError("Job retention is missing")
    mode = source.get("mode", "tiered")
    if mode not in ("tiered", "last", "all"):
        raise RetentionError("Unknown retention mode")
    # Preserve the original four-field representation for unchanged old jobs.
    extended = any(key in source for key in ("mode", "hourly", "within", "last"))
    result = {period: "0" for period in PERIOD_DEFAULTS}
    if extended:
        result.update(mode=mode, hourly="0", within="", last="0")
    if mode == "last":
        result["last"] = _count(source.get("last", "0"))
        if result["last"] == "0":
            raise RetentionError("Last-archive count must be greater than zero")
    elif mode == "tiered":
        for period in PERIOD_DEFAULTS:
            result[period] = _count(source.get(period, ""))
        if extended:
            result["hourly"] = _count(source.get("hourly", "0"))
            within = str(source.get("within", "")).strip()
            if within and not re.fullmatch(r"[1-9][0-9]{0,5}[Hdwmy]", within):
                raise RetentionError("Keep-within requires a positive interval in H, d, w, m or y")
            result["within"] = within
        if not any(int(result.get(period, "0")) for period in PERIODS):
            if result.get("within"):
                raise RetentionError(
                    "Keep-within requires an additional positive count rule to prevent deleting all archives after a backup gap",
                    "retention_within_only",
                )
            raise RetentionError("At least one retention value must be greater than zero", "retention_all_zero")
    return result


def prune_arguments(source):
    policy = normalize_retention(source)
    if policy.get("mode") == "all":
        raise RetentionError("Prune is disabled: this job keeps all archives", "retention_keep_all")
    if policy.get("mode") == "last":
        return ["--keep-last", policy["last"]]
    args = []
    if policy.get("within"):
        args.extend(["--keep-within", policy["within"]])
    for period in PERIODS:
        if period in policy:
            args.extend([f"--keep-{period}", policy[period]])
    return args


def retention_description(source):
    policy = normalize_retention(source)
    if policy.get("mode") == "all":
        return "Keep all archives; prune disabled"
    return " ".join(prune_arguments(policy))
