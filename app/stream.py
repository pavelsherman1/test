"""
Single-camera streaming pipeline:

  Wyze camera (TUTK P2P)
      ↓  H.264 NAL units (Annex B)
  FFmpeg subprocess (stdin)
      ↓  transcoded / scaled / bitrate-limited H.264 + AAC
  mediamtx (local RTSP publish)
      ↓  RTSP stream exposed to Home Assistant / other consumers

Each CameraStream instance runs in its own thread and automatically
reconnects on failure with exponential back-off.
"""

import logging
import struct
import subprocess
import threading
import time
from typing import Optional

from .cameras import CameraInfo
from .config import BridgeConfig, StreamConfig

logger = logging.getLogger(__name__)

# Maximum consecutive reconnect attempts before giving up permanently
_MAX_RECONNECTS = 20

# Annex B start codes
_START_CODE_4 = b"\x00\x00\x00\x01"
_START_CODE_3 = b"\x00\x00\x01"


def _ensure_annex_b(data: bytes) -> bytes:
    """
    Convert an H.264 NAL unit payload to Annex B format if it isn't already.

    Wyze cameras (via TUTK) may deliver NAL units in either:
      - Annex B (already has start codes) — pass through unchanged
      - AVCC   (4-byte big-endian length prefix per NAL)  — convert
    """
    if not data:
        return data
    if data[:4] == _START_CODE_4 or data[:3] == _START_CODE_3:
        return data  # Already Annex B

    # Attempt AVCC → Annex B conversion
    result = bytearray()
    i = 0
    while i + 4 <= len(data):
        nal_len = struct.unpack(">I", data[i : i + 4])[0]
        i += 4
        if nal_len == 0 or i + nal_len > len(data):
            break
        result += _START_CODE_4
        result += data[i : i + nal_len]
        i += nal_len

    return bytes(result) if result else data


def _build_ffmpeg_cmd(
    stream_config: StreamConfig,
    rtsp_url: str,
    enable_audio: bool,
) -> list[str]:
    """
    Build an FFmpeg command that:
      - Reads raw H.264 from stdin (the TUTK pipe)
      - Optionally reads PCM audio from a second stdin (not used for simplicity;
        audio is handled separately via wyzecam's audio thread)
      - Scales/fps-limits/bitrate-caps the video
      - Pushes the result to mediamtx via RTSP
    """
    scale = stream_config.scale_filter
    fps = stream_config.fps
    bitrate = stream_config.bitrate
    max_bitrate = stream_config.effective_max_bitrate
    buf = stream_config.buffer_size
    preset = stream_config.encoder_preset

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        # ── Video input from stdin ──────────────────────────────────────────
        "-f", "h264",
        "-i", "pipe:0",
    ]

    if enable_audio:
        # Audio input from the named pipe written by the audio thread
        cmd += [
            "-f", "s16le",       # Raw signed 16-bit PCM little-endian
            "-ar", "8000",       # Wyze audio is 8 kHz
            "-ac", "1",          # Mono
            "-i", "pipe:3",      # Passed as fd=3 by the caller
        ]

    # ── Video encoding ────────────────────────────────────────────────────
    cmd += [
        "-c:v", "libx264",
        "-preset", preset,
        "-tune", "zerolatency",  # Minimise encode latency
        "-vf", f"scale={scale}:force_original_aspect_ratio=decrease,fps={fps}",
        "-b:v", bitrate,
        "-maxrate", max_bitrate,
        "-bufsize", buf,
        "-g", str(fps * 2),      # Keyframe every 2 s for fast seeking
        "-sc_threshold", "0",
    ]

    if enable_audio:
        cmd += [
            "-c:a", "aac",
            "-b:a", "32k",
            "-ar", "44100",      # Up-sample for broader compatibility
        ]
    else:
        cmd += ["-an"]

    # ── Output to mediamtx via RTSP ──────────────────────────────────────
    cmd += [
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        rtsp_url,
    ]

    return cmd


class CameraStream:
    """
    Manages the streaming lifecycle for one camera.

    Call .start() to launch the background thread; call .stop() to
    request a clean shutdown.
    """

    def __init__(self, camera: CameraInfo, config: BridgeConfig, account):
        self.camera = camera
        self.config = config
        self.account = account
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ffmpeg: Optional[subprocess.Popen] = None

    @property
    def stream_name(self) -> str:
        return self.camera.stream_name

    @property
    def rtsp_publish_url(self) -> str:
        user = self.config.publish_user
        pwd = self.config.publish_password
        port = self.config.rtsp_port
        name = self.stream_name
        return f"rtsp://{user}:{pwd}@127.0.0.1:{port}/{name}"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run_with_reconnect,
            name=f"stream-{self.stream_name}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Started stream thread for %r", self.camera.name)

    def stop(self) -> None:
        logger.info("Stopping stream for %r", self.camera.name)
        self._stop_event.set()
        self._kill_ffmpeg()
        if self._thread:
            self._thread.join(timeout=10)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal ─────────────────────────────────────────────────────────

    def _run_with_reconnect(self) -> None:
        delay = self.config.reconnect_delay
        attempts = 0

        while not self._stop_event.is_set() and attempts < _MAX_RECONNECTS:
            try:
                self._stream_once()
                # _stream_once() returns normally only when _stop_event is set
                break
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                attempts += 1
                backoff = min(delay * (2 ** min(attempts - 1, 5)), 120)
                logger.warning(
                    "Stream %r failed (attempt %d/%d): %s — retrying in %ds",
                    self.camera.name, attempts, _MAX_RECONNECTS,
                    type(exc).__name__, backoff,
                )
                self._stop_event.wait(backoff)

        if attempts >= _MAX_RECONNECTS:
            logger.error(
                "Stream %r exceeded max reconnect attempts — giving up",
                self.camera.name,
            )

    def _stream_once(self) -> None:
        """
        Open one TUTK session and pump frames into FFmpeg until either
        the stop event fires or the connection drops.
        """
        try:
            import wyzecam
        except ImportError:
            raise RuntimeError("wyzecam is not installed")

        sc = self.config.stream
        enable_audio = sc.audio

        ffmpeg_cmd = _build_ffmpeg_cmd(
            sc,
            self.rtsp_publish_url,
            enable_audio=False,  # Simplified: video-only on first iteration
        )

        logger.debug(
            "FFmpeg command for %r: %s",
            self.camera.name,
            # Mask the RTSP URL credentials in the log
            " ".join(
                arg if "rtsp://" not in arg else "rtsp://***:***@..."
                for arg in ffmpeg_cmd
            ),
        )

        ffmpeg = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._ffmpeg = ffmpeg

        stderr_thread = threading.Thread(
            target=self._log_ffmpeg_stderr,
            args=(ffmpeg,),
            daemon=True,
        )
        stderr_thread.start()

        try:
            logger.info("Connecting to camera %r via TUTK…", self.camera.name)
            with wyzecam.WyzeIOTCam(self.account, self.camera.raw) as cam:
                logger.info("Streaming %r → RTSP /%s", self.camera.name, self.stream_name)
                for _frame_info, frame_data in cam.recv_video_data():
                    if self._stop_event.is_set():
                        return
                    if ffmpeg.poll() is not None:
                        raise RuntimeError(
                            f"FFmpeg exited unexpectedly (rc={ffmpeg.returncode})"
                        )
                    payload = _ensure_annex_b(frame_data)
                    try:
                        ffmpeg.stdin.write(payload)
                        ffmpeg.stdin.flush()
                    except BrokenPipeError:
                        raise RuntimeError("FFmpeg stdin closed (broken pipe)")
        finally:
            self._kill_ffmpeg()

    def _kill_ffmpeg(self) -> None:
        proc = self._ffmpeg
        if proc is None:
            return
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
        self._ffmpeg = None

    def _log_ffmpeg_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    logger.debug("ffmpeg[%s]: %s", self.stream_name, decoded)
        except Exception:
            pass
