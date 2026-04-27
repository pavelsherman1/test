# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Download mediamtx binary for the target architecture
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS mediamtx-download

ARG MEDIAMTX_VERSION=1.9.3
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Map Docker TARGETARCH to mediamtx release naming
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64)  MTX_ARCH="amd64"   ;; \
        arm64)  MTX_ARCH="arm64v8" ;; \
        arm)    MTX_ARCH="armv7"   ;; \
        *)      echo "Unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    wget -q \
      "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_${MTX_ARCH}.tar.gz" \
      -O /tmp/mediamtx.tar.gz; \
    tar -xzf /tmp/mediamtx.tar.gz -C /usr/local/bin mediamtx; \
    chmod +x /usr/local/bin/mediamtx; \
    /usr/local/bin/mediamtx --version


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Python dependency builder (wheel cache)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS python-builder

# Build-time dependencies for any C-extension packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: Final production image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System packages ──────────────────────────────────────────────────────────
#   ffmpeg    – video transcoding pipeline
#   wget      – used by entrypoint healthcheck
#   ca-certs  – HTTPS to Wyze API
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    # Remove apt caches and other unnecessary files
    && apt-get clean \
    && rm -rf /tmp/* /var/tmp/*

# ── Non-root user ─────────────────────────────────────────────────────────────
# Running as a non-root user limits the blast radius of any security issue.
# UID/GID 1000 matches the Unraid default "nobody" user convention.
RUN groupadd -g 1000 bridge \
    && useradd -u 1000 -g bridge -s /sbin/nologin -M bridge

# ── Copy mediamtx binary ──────────────────────────────────────────────────────
COPY --from=mediamtx-download /usr/local/bin/mediamtx /usr/local/bin/mediamtx

# ── Install Python dependencies ───────────────────────────────────────────────
COPY --from=python-builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# ── Copy application files ────────────────────────────────────────────────────
WORKDIR /app
COPY app/ ./app/
COPY mediamtx.yml .
COPY entrypoint.sh .
COPY healthcheck.sh .

# ── File permissions ──────────────────────────────────────────────────────────
RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh \
    && chown -R bridge:bridge /app

# ── Switch to non-root user ───────────────────────────────────────────────────
USER bridge

# ── Ports ─────────────────────────────────────────────────────────────────────
# 8554 – RTSP (primary, used by Home Assistant)
# 8888 – HLS  (HTTP Live Streaming, optional browser access)
EXPOSE 8554/tcp 8888/tcp

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD /app/healthcheck.sh

# ── Metadata labels ────────────────────────────────────────────────────────────
LABEL \
    org.opencontainers.image.title="Wyze RTSP Bridge" \
    org.opencontainers.image.description="Expose Wyze camera streams as RTSP via mediamtx" \
    org.opencontainers.image.source="https://github.com/your-org/wyze-rtsp-bridge" \
    org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["/app/entrypoint.sh"]
