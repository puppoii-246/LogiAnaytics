"""
Network Client

TCP client that connects out to the queue management device and delivers
complete raw messages via a callback. No protocol knowledge — framing only.
Reconnects automatically (with exponential backoff) if the connection is
lost or cannot be established.
"""

from __future__ import annotations

import socket
import threading
import time
from enum import Enum
from typing import Callable

from config_manager import NetworkConfig
from logger import get_logger

OnMessage = Callable[[bytes], None]


class ConnectionStatus(str, Enum):
    """Reported via NetworkClient's on_status_change callback.

    Two states only: CONNECTING covers both "never connected yet" and "was
    connected, currently retrying". How urgently a prolonged CONNECTING
    episode should be communicated to the user is a presentation-layer
    concern, not this module's.
    """

    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


OnStatusChange = Callable[[ConnectionStatus], None]

# Reconnect backoff: start fast, double on each failure, cap at the ceiling.
_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 5.0
_RECONNECT_BACKOFF_MULTIPLIER = 2.0

# A connection must stay up at least this long to be considered "stable" and
# reset the backoff delay. Prevents a connect-then-immediately-drop device
# from causing a tight reconnect loop.
_MIN_STABLE_CONNECTION_S = 3.0

# Defensive cap on a single message's size, expressed as a multiple of the
# configured receive buffer size. Guards against unbounded buffer growth if
# a device streams continuously without a clean idle gap.
_MAX_MESSAGE_SIZE_MULTIPLIER = 64


class NetworkClient:
    """Background TCP client. Call start() then stop() when finished."""

    def __init__(
        self,
        config: NetworkConfig,
        on_message: OnMessage,
        on_status_change: OnStatusChange | None = None,
    ) -> None:
        self._config = config
        self._on_message = on_message
        self._on_status_change = on_status_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Network client is already running")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="network-client",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                # Wake any thread blocked in recv()/send()
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                # Socket may already be closed or disconnected.
                pass

            try:
                sock.close()
            except OSError:
                pass

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                get_logger().error(
                    "Network thread did not stop within %.1fs; not clearing thread reference",
                    timeout,
                )
            else:
                self._thread = None

    def _run(self) -> None:
        logger = get_logger()
        cfg = self._config
        delay = _INITIAL_RECONNECT_DELAY_S

        while not self._stop.is_set():
            self._notify_status(ConnectionStatus.CONNECTING)
            sock = self._connect(cfg, logger)
            if sock is None:
                if self._stop.wait(delay):
                    break
                delay = min(delay * _RECONNECT_BACKOFF_MULTIPLIER, _MAX_RECONNECT_DELAY_S)
                continue

            self._sock = sock
            logger.info("Connected to device at %s:%s", cfg.ip, cfg.port)
            self._notify_status(ConnectionStatus.CONNECTED)
            connected_at = time.monotonic()
            try:
                self._handle_connection(sock)
            except Exception:
                logger.exception("Error handling device connection")
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
                self._sock = None
                logger.info("Disconnected from device")

            if time.monotonic() - connected_at >= _MIN_STABLE_CONNECTION_S:
                # Connection was up long enough to be considered stable — reset backoff.
                delay = _INITIAL_RECONNECT_DELAY_S
            elif self._stop.wait(delay):
                break
            else:
                delay = min(delay * _RECONNECT_BACKOFF_MULTIPLIER, _MAX_RECONNECT_DELAY_S)

        logger.info("Network client stopped")

    def _connect(self, cfg: NetworkConfig, logger) -> socket.socket | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(cfg.socket_timeout)
        try:
            sock.connect((cfg.ip, cfg.port))
        except OSError as exc:
            logger.warning("Connect to %s:%s failed: %s", cfg.ip, cfg.port, exc)
            sock.close()
            return None
        return sock

    def _handle_connection(self, sock: socket.socket) -> None:
        """
        Wait for the start of a message with socket_timeout; once bytes
        arrive, drain with a short quiet period (message_idle_ms) — some
        devices/gateways split one logical message across more than one
        TCP write, so we wait for real silence before treating it as
        complete — then deliver. Connection stays open for more messages
        until the device closes it.
        """
        logger = get_logger()
        buf_size = self._config.receive_buffer_size
        idle_s = self._config.message_idle_ms / 1000.0

        while not self._stop.is_set():
            sock.settimeout(self._config.socket_timeout)
            try:
                data = sock.recv(buf_size)
            except socket.timeout:
                continue
            except OSError:
                logger.exception("Recv error from device")
                return

            if not data:
                return  # device closed the connection

            buffer = bytearray(data)

            # Drain remaining fragments until short idle marks end of message.
            while not self._stop.is_set():
                sock.settimeout(idle_s)
                try:
                    more = sock.recv(buf_size)
                except socket.timeout:
                    break
                except OSError:
                    logger.exception("Recv error from device")
                    self._deliver(buffer)
                    return

                if not more:
                    self._deliver(buffer)
                    return

                buffer.extend(more)

                max_size = buf_size * _MAX_MESSAGE_SIZE_MULTIPLIER
                if len(buffer) > max_size:
                    logger.error(
                        "Message exceeded max size (%d bytes > %d); discarding",
                        len(buffer),
                        max_size,
                    )
                    return

            self._deliver(buffer)

    def _deliver(self, buffer: bytearray) -> None:
        if not buffer:
            return
        message = bytes(buffer)
        get_logger().debug("Delivering message (%d bytes) from device: %r", len(message), message)
        self._safe_callback(message)

    def _safe_callback(self, message: bytes) -> None:
        logger = get_logger()
        try:
            self._on_message(message)
        except Exception:
            logger.exception("on_message callback failed")

    def _notify_status(self, status: ConnectionStatus) -> None:
        if self._on_status_change is None:
            return
        try:
            self._on_status_change(status)
        except Exception:
            get_logger().exception("on_status_change callback failed")