"""
Configuration loaded exclusively from environment variables.
No credentials are ever written to disk or logged.
"""

import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Optional


_BITRATE_RE = re.compile(r"^\d+[kKmM]?$")
_RESOLUTION_RE = re.compile(r"^\d{2,4}x\d{2,4}$")


class ConfigError(ValueError):
    pass


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise ConfigError(f"Required environment variable {name!r} is not set")
    return val


def _optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _int_env(name: str, default: int, min_val: int = 1, max_val: int = 65535) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ConfigError(f"Environment variable {name!r} must be an integer, got {raw!r}")
    if not (min_val <= val <= max_val):
        raise ConfigError(
            f"Environment variable {name!r} must be between {min_val} and {max_val}, got {val}"
        )
    return val


@dataclass
class StreamConfig:
    """Controls video quality and network throughput."""

    # Preset: HD (1080p), SD (480p), 360p, or explicit WxH
    quality: str = "HD"

    # FFmpeg bitrate for the output stream (e.g. "2000k", "4M")
    bitrate: str = "2000k"

    # Maximum bitrate cap (defaults to 1.5x bitrate)
    max_bitrate: str = ""

    # Output frames per second (lower = less bandwidth)
    fps: int = 20

    # Enable audio pass-through
    audio: bool = True

    # FFmpeg decode/encode buffer; larger = smoother but higher latency
    buffer_size: str = "4M"

    # FFmpeg preset: ultrafast/superfast/veryfast/faster/fast/medium
    # ultrafast = lowest CPU, highest network; medium = higher CPU, lower network
    encoder_preset: str = "ultrafast"

    @property
    def scale_filter(self) -> str:
        presets = {
            "HD": "1920:1080",
            "FHD": "1920:1080",
            "2K": "2560:1440",
            "4K": "3840:2160",
            "SD": "640:480",
            "360P": "640:360",
            "360p": "640:360",
            "480P": "854:480",
            "480p": "854:480",
            "720P": "1280:720",
            "720p": "1280:720",
            "1080P": "1920:1080",
            "1080p": "1920:1080",
        }
        if self.quality in presets:
            return presets[self.quality]
        # Custom WxH format
        if _RESOLUTION_RE.match(self.quality):
            return self.quality.replace("x", ":")
        return "1920:1080"  # Safe fallback

    @property
    def effective_max_bitrate(self) -> str:
        if self.max_bitrate:
            return self.max_bitrate
        # Default max = 1.5x target
        if self.bitrate.endswith("k") or self.bitrate.endswith("K"):
            base = int(self.bitrate[:-1])
            return f"{int(base * 1.5)}k"
        if self.bitrate.endswith("m") or self.bitrate.endswith("M"):
            base = int(self.bitrate[:-1])
            return f"{int(base * 1.5)}M"
        return self.bitrate


@dataclass
class BridgeConfig:
    # Wyze credentials (never stored or logged)
    wyze_email: str = ""
    wyze_password: str = ""
    wyze_totp_key: str = ""       # Base32 TOTP secret for 2FA-enabled accounts
    wyze_api_key: str = ""        # Optional Wyze API key (newer auth method)
    wyze_key_id: str = ""         # Required when wyze_api_key is set

    # Comma-separated camera names or MACs to include (empty = all cameras)
    camera_filter: str = ""

    # RTSP server settings
    rtsp_port: int = 8554
    hls_port: int = 8888          # HTTP Live Streaming (optional)
    api_port: int = 9997          # mediamtx management API (bind to 127.0.0.1)

    # RTSP read credentials (for Home Assistant / viewers)
    rtsp_user: str = ""
    rtsp_password: str = ""       # If empty, streams are unauthenticated

    # Internal publish credentials (auto-generated; bridge → mediamtx)
    publish_user: str = field(default_factory=lambda: "bridge")
    publish_password: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    # Stream quality settings
    stream: StreamConfig = field(default_factory=StreamConfig)

    # Reconnect delay in seconds on stream failure
    reconnect_delay: int = 5

    # Enable debug-level logging (avoids logging credential values)
    debug: bool = False

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        stream = StreamConfig(
            quality=_optional_env("QUALITY", "HD"),
            bitrate=_optional_env("BITRATE", "2000k"),
            max_bitrate=_optional_env("MAX_BITRATE", ""),
            fps=_int_env("FPS", 20, min_val=1, max_val=60),
            audio=_bool_env("AUDIO", default=True),
            buffer_size=_optional_env("BUFFER_SIZE", "4M"),
            encoder_preset=_optional_env("ENCODER_PRESET", "ultrafast"),
        )

        # Validate bitrate format
        bitrate = stream.bitrate
        if not _BITRATE_RE.match(bitrate):
            raise ConfigError(
                f"BITRATE must be a number optionally followed by k/K/m/M, got {bitrate!r}"
            )

        # Validate quality/resolution
        quality = stream.quality
        valid_presets = {"HD", "FHD", "2K", "4K", "SD", "360P", "360p", "480P", "480p",
                         "720P", "720p", "1080P", "1080p"}
        if quality not in valid_presets and not _RESOLUTION_RE.match(quality):
            raise ConfigError(
                f"QUALITY must be a preset ({', '.join(sorted(valid_presets))}) "
                f"or WxH format (e.g. 1280x720), got {quality!r}"
            )

        # Pick up the publish credentials injected by entrypoint.sh.
        # If running outside Docker, fall back to a freshly generated secret.
        publish_user = _optional_env("BRIDGE_PUBLISH_USER", "bridge")
        publish_pass = _optional_env(
            "BRIDGE_PUBLISH_PASS", secrets.token_urlsafe(32)
        )

        return cls(
            wyze_email=_optional_env("WYZE_EMAIL"),
            wyze_password=_optional_env("WYZE_PASSWORD"),
            wyze_totp_key=_optional_env("WYZE_TOTP_KEY"),
            wyze_api_key=_optional_env("WYZE_API_KEY"),
            wyze_key_id=_optional_env("WYZE_KEY_ID"),
            camera_filter=_optional_env("CAMERAS", ""),
            rtsp_port=_int_env("RTSP_PORT", 8554, min_val=1024, max_val=65535),
            hls_port=_int_env("HLS_PORT", 8888, min_val=1024, max_val=65535),
            api_port=_int_env("API_PORT", 9997, min_val=1024, max_val=65535),
            rtsp_user=_optional_env("RTSP_USER", ""),
            rtsp_password=_optional_env("RTSP_PASSWORD", ""),
            publish_user=publish_user,
            publish_password=publish_pass,
            stream=stream,
            reconnect_delay=_int_env("RECONNECT_DELAY", 5, min_val=1, max_val=300),
            debug=_bool_env("DEBUG", default=False),
        )

    def validate(self) -> None:
        """Raise ConfigError if the configuration is unusable."""
        has_api_key = bool(self.wyze_api_key and self.wyze_key_id)
        has_credentials = bool(self.wyze_email and self.wyze_password)
        if not has_api_key and not has_credentials:
            raise ConfigError(
                "Provide either WYZE_EMAIL+WYZE_PASSWORD "
                "or WYZE_API_KEY+WYZE_KEY_ID"
            )
        if self.wyze_api_key and not self.wyze_key_id:
            raise ConfigError("WYZE_KEY_ID is required when WYZE_API_KEY is set")
        if self.rtsp_password and not self.rtsp_user:
            raise ConfigError("RTSP_USER is required when RTSP_PASSWORD is set")

    @property
    def camera_filter_list(self) -> list[str]:
        if not self.camera_filter:
            return []
        return [c.strip() for c in self.camera_filter.split(",") if c.strip()]

    def masked_repr(self) -> str:
        """Return a safe string representation that masks all secrets."""
        return (
            f"BridgeConfig("
            f"wyze_email={'***' if self.wyze_email else '<unset>'}, "
            f"wyze_password={'***' if self.wyze_password else '<unset>'}, "
            f"wyze_totp_key={'***' if self.wyze_totp_key else '<unset>'}, "
            f"wyze_api_key={'***' if self.wyze_api_key else '<unset>'}, "
            f"rtsp_user={self.rtsp_user!r}, "
            f"rtsp_password={'***' if self.rtsp_password else '<unset>'}, "
            f"quality={self.stream.quality!r}, "
            f"bitrate={self.stream.bitrate!r}, "
            f"fps={self.stream.fps}, "
            f"audio={self.stream.audio})"
        )
