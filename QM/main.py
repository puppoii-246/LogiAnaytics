"""
QMDS entry point.

Loads configuration, wires modules, starts the TCP server, and launches the
PyQt6 kiosk-mode display. ApplicationState's change listeners are registered
directly as Qt signal emitters, so MainWindow updates only the counter(s)
that actually changed instead of rebuilding the whole display on every event.
"""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app_state import ApplicationState
from config_manager import load_config
from event_manager import handle_raw
from logger import get_logger, setup_logger, shutdown_logger
from main_window import MainWindow
from network_client import NetworkClient

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built executable: __file__ resolves into the
    # internal bundle, which may be read-only and is recreated on every
    # launch in --onefile mode. sys.executable always points at the real
    # exe's location, so config.json stays next to it and persists correctly.
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"

# Default per-thread stack size for this app's background threads (network
# client, log queue listener). None of them need deep call stacks, so a much
# smaller reservation than the platform default (~8 MB) is sufficient and
# saves memory on constrained devices. Must be set before any thread starts.
_THREAD_STACK_SIZE_BYTES = 65536  # 64 KiB


def _reduce_thread_stack_size() -> None:
    """Best-effort: not all platforms support setting the thread stack size."""
    try:
        threading.stack_size(_THREAD_STACK_SIZE_BYTES)
    except (ValueError, RuntimeError):
        pass


def main() -> int:
    _reduce_thread_stack_size()

    config = load_config(CONFIG_PATH)
    setup_logger(config.logging, BASE_DIR)
    logger = get_logger()

    logger.info("QMDS starting (backend)")
    logger.info(
        "Config loaded: device=%s:%s",
        config.network.ip,
        config.network.port,
    )

    state = ApplicationState(config.display)

    app = QApplication(sys.argv)
    window = MainWindow(config.display, state, BASE_DIR)
    state.add_counter_listener(window.counter_changed.emit)
    state.add_group_reset_listener(window.group_reset_signal.emit)

    def on_message(data: bytes) -> None:
        handle_raw(data, state)

    client = NetworkClient(
        config.network,
        on_message=on_message,
        on_status_change=window.connection_status_changed.emit,
    )
    client.start()

    def _shutdown() -> None:
        logger.info("Shutdown requested")
        client.stop()
        logger.info("QMDS stopped")
        shutdown_logger()

    app.aboutToQuit.connect(_shutdown)

    # Qt's C++ event loop doesn't hand control back to the Python
    # interpreter on its own, so Ctrl+C/SIGTERM would otherwise be ignored
    # until the next GUI event. A short-interval timer gives Python a
    # regular chance to run its signal handlers.
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_args: app.quit())
    _signal_pump = QTimer()
    _signal_pump.timeout.connect(lambda: None)
    _signal_pump.start(200)

    logger.info("Ready — waiting for device messages (Esc or Ctrl+C to stop)")
    window.show_configured()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())