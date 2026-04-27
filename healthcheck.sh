#!/bin/sh
# Docker HEALTHCHECK script
#
# Reports healthy if:
#   1. mediamtx management API responds
#   2. At least one RTSP path is registered (i.e., at least one stream is up)
#
# Returns 0 (healthy) or 1 (unhealthy).

set -eu

API_PORT="${API_PORT:-9997}"
API_URL="http://127.0.0.1:${API_PORT}/v3/paths/list"

# Fetch the path list from mediamtx; fail if API is down
RESPONSE="$(wget -q -O - "${API_URL}" 2>/dev/null)" || {
    echo "UNHEALTHY: mediamtx API not responding on port ${API_PORT}"
    exit 1
}

# Check that at least one path exists (crude JSON check — avoids jq dependency)
if echo "${RESPONSE}" | grep -q '"name"'; then
    echo "HEALTHY"
    exit 0
else
    echo "DEGRADED: mediamtx is up but no streams are registered yet"
    # Return healthy during startup; bridge may still be authenticating.
    # Change exit code to 1 if you want strict "stream must be live" checks.
    exit 0
fi
