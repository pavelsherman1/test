"""
Multi-camera orchestrator.

Authenticates once, discovers cameras, and manages one CameraStream
per camera.  Watches for dead streams and restarts them.  Also handles
periodic Wyze credential refresh (tokens expire after ~1 hour).
"""

import logging
import threading
import time
from typing import Optional

from .auth import login, refresh_credential, AuthError
from .cameras import get_cameras, log_camera_summary, CameraInfo
from .config import BridgeConfig
from .stream import CameraStream

logger = logging.getLogger(__name__)

# Refresh Wyze auth tokens before they expire (55 min < 60 min lifetime)
_TOKEN_REFRESH_INTERVAL = 55 * 60


class Bridge:
    """
    Lifecycle controller for all camera streams.

    Usage:
        bridge = Bridge(config)
        bridge.start()          # blocks until bridge.stop() is called
    """

    def __init__(self, config: BridgeConfig):
        self.config = config
        self._streams: dict[str, CameraStream] = {}
        self._credential = None
        self._account = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Authenticate, start all streams, then block until stop() is called."""
        self._authenticate()
        cameras = self._discover_cameras()

        if not cameras:
            logger.warning(
                "No cameras found (or all are offline). "
                "Streams will not start until cameras come online."
            )

        self._start_streams(cameras)
        self._watch_loop()

    def stop(self) -> None:
        logger.info("Stopping bridge…")
        self._stop_event.set()
        with self._lock:
            for stream in self._streams.values():
                stream.stop()

    def stream_paths(self) -> list[str]:
        """Return the RTSP path components for all active streams."""
        with self._lock:
            return [s.stream_name for s in self._streams.values()]

    # ── Internals ─────────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        cfg = self.config
        credential, account = login(
            cfg.wyze_email,
            cfg.wyze_password,
            cfg.wyze_totp_key,
        )
        self._credential = credential
        self._account = account

    def _discover_cameras(self) -> list[CameraInfo]:
        cameras = get_cameras(
            self._credential,
            filter_list=self.config.camera_filter_list or None,
        )
        log_camera_summary(cameras)
        # Only start streams for online cameras
        return [c for c in cameras if c.is_online]

    def _start_streams(self, cameras: list[CameraInfo]) -> None:
        with self._lock:
            for cam in cameras:
                self._launch_stream(cam)

    def _launch_stream(self, cam: CameraInfo) -> None:
        """Create and start a CameraStream (must be called under self._lock)."""
        stream = CameraStream(cam, self.config, self._account)
        stream.start()
        self._streams[cam.mac] = stream

    def _watch_loop(self) -> None:
        """
        Periodic maintenance loop:
          - Detect dead stream threads and restart them
          - Refresh Wyze credentials before they expire
          - Re-discover cameras that came online after initial startup
        """
        last_refresh = time.monotonic()
        last_rediscover = time.monotonic()
        rediscover_interval = 300  # Re-check camera list every 5 minutes

        logger.info("Bridge is running. RTSP paths: %s", self.stream_paths())

        while not self._stop_event.is_set():
            self._stop_event.wait(30)  # Check every 30 s

            if self._stop_event.is_set():
                break

            now = time.monotonic()

            # ── Refresh credentials ──────────────────────────────────────
            if now - last_refresh >= _TOKEN_REFRESH_INTERVAL:
                try:
                    cfg = self.config
                    self._credential, self._account = refresh_credential(
                        self._credential,
                        cfg.wyze_email,
                        cfg.wyze_password,
                        cfg.wyze_totp_key,
                    )
                    last_refresh = now
                except AuthError as exc:
                    logger.error("Credential refresh failed: %s", exc)

            # ── Re-discover newly online cameras ──────────────────────────
            if now - last_rediscover >= rediscover_interval:
                self._rediscover_cameras()
                last_rediscover = now

            # ── Restart dead stream threads ───────────────────────────────
            self._restart_dead_streams()

    def _restart_dead_streams(self) -> None:
        with self._lock:
            for mac, stream in list(self._streams.items()):
                if not stream.is_alive():
                    logger.warning(
                        "Stream thread for %r died — restarting",
                        stream.camera.name,
                    )
                    new_stream = CameraStream(
                        stream.camera, self.config, self._account
                    )
                    new_stream.start()
                    self._streams[mac] = new_stream

    def _rediscover_cameras(self) -> None:
        """Start streams for cameras that came online since last check."""
        try:
            cameras = get_cameras(
                self._credential,
                filter_list=self.config.camera_filter_list or None,
            )
        except Exception as exc:
            logger.warning("Camera re-discovery failed: %s", exc)
            return

        with self._lock:
            known_macs = set(self._streams.keys())
            for cam in cameras:
                if cam.mac not in known_macs and cam.is_online:
                    logger.info(
                        "New camera came online: %r — starting stream", cam.name
                    )
                    self._launch_stream(cam)
