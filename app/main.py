"""
Entry point for the Wyze RTSP Bridge.

Start order:
  1. Load and validate configuration from environment
  2. mediamtx is already running (started by entrypoint.sh)
  3. Authenticate with Wyze
  4. Start camera streams
  5. Run until SIGTERM / SIGINT
"""

import logging
import signal
import sys
import time

from .bridge import Bridge
from .config import BridgeConfig, ConfigError

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, level=level)
    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "requests", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    # Minimal bootstrap logging before we have the config
    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, level=logging.INFO)
    log = logging.getLogger("wyze-bridge")

    log.info("Wyze RTSP Bridge starting")

    # ── Load config ───────────────────────────────────────────────────────
    try:
        config = BridgeConfig.from_env()
        config.validate()
    except ConfigError as exc:
        log.critical("Configuration error: %s", exc)
        return 1

    _configure_logging(config.debug)
    log = logging.getLogger("wyze-bridge")  # Re-acquire after reconfiguring
    log.info("Configuration loaded: %s", config.masked_repr())

    # ── Set up graceful shutdown ──────────────────────────────────────────
    bridge = Bridge(config)

    def _handle_signal(signum, _frame):
        sig_name = signal.Signals(signum).name
        log.info("Received %s — shutting down", sig_name)
        bridge.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ── Run ───────────────────────────────────────────────────────────────
    try:
        bridge.start()  # Blocks until stop() is called
    except ConfigError as exc:
        log.critical("Fatal configuration error: %s", exc)
        return 1
    except Exception as exc:
        log.critical("Unhandled exception: %s", exc, exc_info=True)
        return 1

    log.info("Bridge stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
