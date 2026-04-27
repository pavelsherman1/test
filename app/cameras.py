"""
Camera discovery and filtering.

Fetches the list of cameras from the Wyze account and applies the
configured filter (by friendly name or MAC address).
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


@dataclass
class CameraInfo:
    """Simplified representation of a Wyze camera."""

    mac: str
    name: str
    model: str
    is_online: bool
    raw: Any  # Original wyzecam WyzeCamera object

    @property
    def stream_name(self) -> str:
        """URL-safe stream path component derived from the camera name."""
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", self.name)
        return safe.strip("_") or self.mac.replace(":", "")

    def __str__(self) -> str:
        status = "online" if self.is_online else "offline"
        return f"{self.name!r} ({self.mac}) [{self.model}] — {status}"


def get_cameras(credential, filter_list: list[str] = None) -> list[CameraInfo]:
    """
    Return all (or filtered) cameras from the Wyze account.

    filter_list items are matched case-insensitively against camera names
    and exact-matched against MAC addresses.  An empty or None list means
    all cameras.
    """
    try:
        import wyzecam
    except ImportError:
        raise RuntimeError("wyzecam is not installed")

    raw_cameras = wyzecam.get_camera_list(credential)
    logger.info("Found %d camera(s) on account", len(raw_cameras))

    cameras = [_to_camera_info(c) for c in raw_cameras]

    if filter_list:
        cameras = _apply_filter(cameras, filter_list)
        logger.info("%d camera(s) after applying filter", len(cameras))

    for cam in cameras:
        logger.info("  Camera: %s", cam)

    return cameras


def _to_camera_info(raw) -> CameraInfo:
    mac = getattr(raw, "mac", "") or ""
    name = getattr(raw, "nickname", "") or getattr(raw, "name", "") or mac
    model = getattr(raw, "product_model", "") or getattr(raw, "model", "") or "unknown"
    is_online = bool(getattr(raw, "is_online", False))
    return CameraInfo(mac=mac, name=name, model=model, is_online=is_online, raw=raw)


def _apply_filter(cameras: list[CameraInfo], filter_list: list[str]) -> list[CameraInfo]:
    """Keep only cameras whose name (case-insensitive) or MAC is in filter_list."""
    normalized = [f.lower() for f in filter_list]
    result = []
    for cam in cameras:
        name_lower = cam.name.lower()
        mac_lower = cam.mac.lower()
        if name_lower in normalized or mac_lower in normalized:
            result.append(cam)
        else:
            logger.debug("Skipping camera %r (not in CAMERAS filter)", cam.name)
    return result


def log_camera_summary(cameras: list[CameraInfo]) -> None:
    online = [c for c in cameras if c.is_online]
    offline = [c for c in cameras if not c.is_online]
    logger.info(
        "Camera summary: %d total, %d online, %d offline",
        len(cameras), len(online), len(offline),
    )
    if offline:
        names = ", ".join(repr(c.name) for c in offline)
        logger.warning("Offline cameras will be skipped: %s", names)
