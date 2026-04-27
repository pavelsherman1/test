# Wyze RTSP Bridge

Exposes Wyze camera streams as standard RTSP, suitable for Home Assistant,
Blue Iris, Frigate, or any project that speaks RTSP.

## How it works

```
Wyze camera  ──TUTK P2P──►  Python bridge  ──H.264──►  FFmpeg  ──RTSP──►  mediamtx
                                                                               │
                                                                    ┌──────────┘
                                                                    ▼
                                                           Home Assistant / VLC / ...
```

1. The Python bridge authenticates with Wyze and opens a P2P connection to each camera using the TUTK/IoTCamera SDK (bundled with the `wyzecam` Python package).
2. Raw H.264 video frames are piped to an FFmpeg process per camera.
3. FFmpeg scales, limits bitrate/fps, and pushes to the bundled [mediamtx](https://github.com/bluenviron/mediamtx) RTSP server.
4. Clients connect to `rtsp://<host>:8554/<camera_name>`.

## Quick start

```bash
cp .env.example .env
# Edit .env with your Wyze credentials and desired quality settings
nano .env

docker compose up -d
docker compose logs -f
```

Stream URL: `rtsp://RTSP_USER:RTSP_PASSWORD@<YOUR_IP>:8554/<camera_name>`

Camera names are derived from the friendly name you set in the Wyze app (spaces replaced with underscores).

## Configuration

All configuration is via environment variables in `.env`.

| Variable | Default | Description |
|---|---|---|
| `WYZE_EMAIL` | — | Wyze account email **(required)** |
| `WYZE_PASSWORD` | — | Wyze account password **(required)** |
| `WYZE_TOTP_KEY` | — | Base32 TOTP secret for 2FA accounts |
| `CAMERAS` | *(all)* | Comma-separated camera names or MACs to bridge |
| `QUALITY` | `HD` | `HD`, `720p`, `480p`, `SD`, `360p`, or `WxH` (e.g. `1280x720`) |
| `BITRATE` | `2000k` | Target video bitrate (`500k`, `2000k`, `4M`, etc.) |
| `MAX_BITRATE` | `1.5×BITRATE` | Hard ceiling on bitrate |
| `FPS` | `20` | Output frames per second (1–60) |
| `ENCODER_PRESET` | `ultrafast` | FFmpeg preset (`ultrafast`…`medium`) |
| `BUFFER_SIZE` | `4M` | FFmpeg output buffer; larger = smoother, higher latency |
| `AUDIO` | `true` | Include audio in the RTSP stream |
| `RTSP_PORT` | `8554` | RTSP server port |
| `HLS_PORT` | `8888` | HLS server port (browser access) |
| `RTSP_USER` | — | Client read username (recommended) |
| `RTSP_PASSWORD` | — | Client read password (recommended) |
| `RECONNECT_DELAY` | `5` | Seconds between reconnect attempts |
| `DEBUG` | `false` | Verbose logging (never logs credentials) |

### Bandwidth guide

| Setting | Approximate bitrate |
|---|---|
| `QUALITY=360p BITRATE=500k FPS=10` | ~0.5 Mbit/s per camera |
| `QUALITY=SD BITRATE=1000k FPS=15` | ~1 Mbit/s per camera |
| `QUALITY=HD BITRATE=2000k FPS=20` | ~2 Mbit/s per camera *(default)* |
| `QUALITY=HD BITRATE=4M FPS=30` | ~4 Mbit/s per camera |

## Unraid setup

1. In Unraid → **Community Applications**, search for or install the container manually.
2. Under **Docker** → **Add Container**:
   - **Repository**: `your-registry/wyze-rtsp-bridge:latest` (or build locally)
   - **Port**: `8554` → `8554` (RTSP), `8888` → `8888` (HLS, optional)
   - **Environment variables**: Add each variable from `.env.example`
3. Start the container and check the log for stream URLs.

Alternatively, place this repository on your Unraid server and run:

```bash
docker compose up -d
```

## Home Assistant integration

After the bridge is running, add a camera in `configuration.yaml`:

```yaml
camera:
  - platform: generic
    name: Front Door
    still_image_url: "http://<YOUR_IP>:8888/Front_Door/index.m3u8"
    stream_source: "rtsp://viewer:your_password@<YOUR_IP>:8554/Front_Door"
    verify_ssl: false
```

Or use the **Generic Camera** integration in the UI with the RTSP URL.

## Security

- **No credentials are stored on disk.** All secrets exist only in container memory and your `.env` file.
- The `.env` file is gitignored — never commit it.
- The mediamtx management API binds to `127.0.0.1` inside the container and is never exposed on the host.
- The container runs as a **non-root user** (UID 1000) with no Linux capabilities.
- Publish credentials (bridge → mediamtx) are **auto-generated on every container start** and are never exposed to clients.
- RTSP read authentication is enabled by default via `RTSP_USER` / `RTSP_PASSWORD`. Using a strong, unique password is strongly recommended even on a local network.
- Credentials are **masked in all log output** even at `DEBUG` level.

## Supported camera models

Any Wyze camera supported by the `wyzecam` Python library:

- Wyze Cam v1, v2, v3, v3 Pro
- Wyze Cam Pan v1, v2, v3
- Wyze Cam Outdoor v1, v2
- Wyze Cam Floodlight

## Troubleshooting

**Stream not showing up**
- Check `docker compose logs` for auth or TUTK errors.
- Verify the camera is online in the Wyze app.
- If you have many cameras, add `CAMERAS=Camera Name` to limit to one.

**2FA error**
- Set `WYZE_TOTP_KEY` to the *base32 secret* shown during 2FA setup, not the 6-digit code.

**High CPU usage**
- Set `ENCODER_PRESET=ultrafast` (already the default).
- Reduce `FPS` or `QUALITY`.
- Use hardware-accelerated encoding if your host supports it (requires customising the FFmpeg command in `stream.py`).

**TUTK library not found**
- The `wyzecam` pip package bundles the TUTK `.so` for `linux/amd64` and `linux/arm64`. If you see warnings, ensure you're running on a supported architecture.
