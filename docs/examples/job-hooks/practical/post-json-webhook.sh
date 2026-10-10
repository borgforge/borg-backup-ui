#!/bin/bash
# Practical hook example (#557). Read README.md / README.de.md before enabling.
# Configure the constants below; arguments and inherited credentials are unused.
set -euo pipefail
CONFIGURED="no"
# POST JSON {job_id, result} to your own HTTPS receiver, using a private curl config.
# This is a generic receiver contract, not a provider-specific monitoring API.
# Sends the result BEFORE this hook; delivery failure fails Post/the overall job.
# Assign Post "also on failure, skip or cancellation". Suggested timeout: 30 s.
CURL_CONFIG="/CHANGE_ME/private-webhook.curl"

[[ "$CONFIGURED" == "yes" ]] || { echo 'Configure this example before use.' >&2; exit 2; }
[[ "${BBUI_HOOK_PHASE:-}" == "post" ]] || { echo 'Assign this script as Post.' >&2; exit 2; }
command -v curl >/dev/null
command -v python3 >/dev/null
[[ -f "$CURL_CONFIG" && ! -L "$CURL_CONFIG" ]] || { echo 'Private curl configuration is missing.' >&2; exit 1; }
[[ $(stat -c %u -- "$CURL_CONFIG") == "$EUID" && $(stat -c %a -- "$CURL_CONFIG") == 600 ]] || {
    echo 'Curl configuration must be owned by the executing user with mode 0600.' >&2; exit 1;
}
case "${BBUI_JOB_RESULT:-}" in
    success|warning|failed|cancelled|skipped) ;;
    *) echo 'Missing or unsupported job result.' >&2; exit 2 ;;
esac
[[ -n "${BBUI_JOB_ID:-}" ]] || { echo 'Missing job ID.' >&2; exit 2; }
payload=$(python3 - <<'PYTHON'
import json
import os
print(json.dumps({"job_id": os.environ["BBUI_JOB_ID"], "result": os.environ["BBUI_JOB_RESULT"]}))
PYTHON
)
# -q disables ~/.curlrc. Keep URL and credentials out of argv and logs.
# The reviewed config must contain ONLY one HTTPS url and optional auth headers.
if ! http_code=$(printf '%s' "$payload" | curl -q --config "$CURL_CONFIG" \
    --proto '=https' --connect-timeout 5 --max-time 20 --retry 0 \
    --silent --fail --output /dev/null --write-out '%{http_code}' --request POST \
    --header 'Content-Type: application/json' --data-binary @- \
    2>/dev/null); then
    echo 'Webhook delivery failed.' >&2
    exit 1
fi
[[ "$http_code" =~ ^2[0-9][0-9]$ ]] || { echo 'Webhook receiver did not accept the request.' >&2; exit 1; }
echo 'Webhook delivered.'
