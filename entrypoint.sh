#!/bin/sh
# Container entrypoint
#
# 1. Validate that the required TUTK library is present
# 2. Export the auto-generated publish credentials into the environment
#    so mediamtx's ${VAR} substitution picks them up
# 3. Start mediamtx in the background
# 4. Start the Python bridge in the foreground
#
# All secrets (Wyze credentials, RTSP passwords, publish credentials)
# remain solely in memory — nothing is written to disk.

set -eu

# ── Generate internal publish credentials if not already set ─────────────
# These are ephemeral per container start and are never exposed to clients.
if [ -z "${MTX_PUBLISH_USER:-}" ]; then
    MTX_PUBLISH_USER="bridge"
fi
if [ -z "${MTX_PUBLISH_PASS:-}" ]; then
    MTX_PUBLISH_PASS="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)"
fi
export MTX_PUBLISH_USER
export MTX_PUBLISH_PASS

# Pass the publish credentials to the Python bridge via dedicated env vars
# (config.py reads these to construct the RTSP publish URL).
export BRIDGE_PUBLISH_USER="${MTX_PUBLISH_USER}"
export BRIDGE_PUBLISH_PASS="${MTX_PUBLISH_PASS}"

# ── Verify TUTK library is available (bundled with wyzecam wheel) ─────────
TUTK_LIB=""
for path in \
    /usr/local/lib/libIOTCAPIs_ALL.so \
    /usr/lib/libIOTCAPIs_ALL.so \
    /app/lib/libIOTCAPIs_ALL.so; do
    if [ -f "$path" ]; then
        TUTK_LIB="$path"
        break
    fi
done

# wyzecam may bundle the library inside its Python package directory
if [ -z "$TUTK_LIB" ]; then
    TUTK_LIB="$(python3 -c \
        "import wyzecam, os; d=os.path.dirname(wyzecam.__file__); \
         libs=[f for f in os.listdir(d) if 'IOTC' in f or 'tutk' in f.lower()]; \
         print(os.path.join(d, libs[0]) if libs else '')" 2>/dev/null || true)"
fi

if [ -z "$TUTK_LIB" ]; then
    echo "WARNING: TUTK/IoTCamera library not found." >&2
    echo "  The wyzecam package should bundle it automatically." >&2
    echo "  If streaming fails, see README for manual SDK setup." >&2
else
    echo "INFO: TUTK library found at ${TUTK_LIB}"
    export TUTK_LIBRARY_PATH="${TUTK_LIB}"
fi

# ── Start mediamtx ───────────────────────────────────────────────────────
echo "INFO: Starting mediamtx…"
mediamtx /app/mediamtx.yml &
MEDIAMTX_PID=$!

# Wait for mediamtx API to become available (up to 10 s)
API_PORT="${API_PORT:-9997}"
i=0
while ! wget -q -O /dev/null "http://127.0.0.1:${API_PORT}/v3/paths/list" 2>/dev/null; do
    i=$((i + 1))
    if [ $i -ge 20 ]; then
        echo "ERROR: mediamtx API did not come up after 10 seconds" >&2
        kill "$MEDIAMTX_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 0.5
done
echo "INFO: mediamtx is ready"

# ── Propagate SIGTERM to child processes ─────────────────────────────────
_shutdown() {
    echo "INFO: Shutting down…"
    kill "$MEDIAMTX_PID" 2>/dev/null || true
    wait "$MEDIAMTX_PID" 2>/dev/null || true
    exit 0
}
trap _shutdown TERM INT

# ── Start the Python bridge ──────────────────────────────────────────────
echo "INFO: Starting Wyze RTSP Bridge…"
exec python3 -m app.main
