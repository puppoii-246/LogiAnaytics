"""
Main Window (PyQt6 frontend)

Builds the kiosk-mode display window from DisplayConfig + ApplicationState.
ApplicationState remains the single source of truth; this module only reads
it (via display_controller) and reacts to its change listeners through Qt
signals. No socket or protocol knowledge lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_state import ApplicationState, CounterState
from config_manager import DisplayConfig
from display_controller import CounterDisplay, build_display_model, format_token
from logger import get_logger
from network_client import ConnectionStatus

# Layout is designed against this reference resolution; fonts and spacing
# scale proportionally to whatever screen the app actually launches on
# (laptop panel, desktop monitor, or a TV attached to a Raspberry Pi).
_REFERENCE_WIDTH = 1920
_REFERENCE_HEIGHT = 1080
_MIN_SCALE = 0.6
_MAX_SCALE = 2.5
_HEADER_HEIGHT_BASE = 100  # px at reference resolution — the "upper area" band

# How long a CONNECTING episode (initial or after a drop) is shown with the
# plain "connecting/reconnecting" wording before it escalates to a more
# pointed message telling the user to check the network.
_STATUS_ESCALATION_MS = 15_000

_BADGE_COLOR_CONNECTED = "#4fd1c5"   # matches the counterValue accent
_BADGE_COLOR_CONNECTING = "#e0a530"  # amber — retrying / needs attention


def _compute_scale(screen_width: int, screen_height: int) -> float:
    raw = min(screen_width / _REFERENCE_WIDTH, screen_height / _REFERENCE_HEIGHT)
    return max(_MIN_SCALE, min(raw, _MAX_SCALE))


class CounterTile(QFrame):
    """A single counter's tile: name flush left, current token centered in the remaining space."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.setObjectName("counterTile")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._name_label = QLabel(f"{name} :")
        self._name_label.setObjectName("counterName")
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._name_label.setWordWrap(True)

        self._value_label = QLabel(format_token(None))
        self._value_label.setObjectName("counterValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.addWidget(self._name_label)
        layout.addWidget(self._value_label, stretch=1)

    def set_value(self, token_text: str) -> None:
        self._value_label.setText(token_text)


class ConnectionBadge(QLabel):
    """Small persistent 'dot + label' indicator of the device connection state."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("connectionBadge")
        self.setTextFormat(Qt.TextFormat.RichText)

    def set_status(self, dot_color: str, text: str) -> None:
        self.setText(f'<span style="color:{dot_color};">\u25cf</span>&nbsp;{text}')


class ConnectingPage(QWidget):
    """Shown in place of the counter grid until the first successful device connection."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("connectingPage")
        self._label = QLabel()
        self._label.setObjectName("connectingLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)


class MainWindow(QMainWindow):
    """Kiosk-mode display window. Reflects ApplicationState; never mutates it."""

    # Registered directly as ApplicationState listeners (see main.py). Qt
    # automatically queues these onto this widget's thread since the
    # listeners fire from the network/event thread, not the GUI thread.
    counter_changed = pyqtSignal(int, int, object)  # group_id, counter_id, CounterState
    group_reset_signal = pyqtSignal(int)  # group_id
    connection_status_changed = pyqtSignal(object)  # ConnectionStatus, from NetworkClient

    def __init__(
        self, display_config: DisplayConfig, state: ApplicationState, base_dir: Path
    ) -> None:
        super().__init__()
        self._display_config = display_config
        self._base_dir = base_dir
        self._tiles: Dict[Tuple[int, int], CounterTile] = {}
        self._ever_connected = False

        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.geometry()
        self._scale = _compute_scale(geometry.width(), geometry.height())

        self.setWindowTitle(display_config.branding.company_name)
        self.setStyleSheet(self._build_stylesheet())

        self._connecting_page = ConnectingPage()
        self._connecting_page.set_text("Connecting to device…")

        self._badge = ConnectionBadge()
        self._badge.set_status(_BADGE_COLOR_CONNECTING, "Connecting…")

        main_page = QWidget()
        main_page.setObjectName("centralWidget")
        root_layout = QVBoxLayout(main_page)
        margin = int(24 * self._scale)
        root_layout.setContentsMargins(margin, margin, margin, margin)
        root_layout.setSpacing(margin)

        root_layout.addWidget(self._build_header())
        root_layout.addLayout(self._build_counter_grid(state), stretch=1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._connecting_page)  # index 0 — shown until first connect
        self._stack.addWidget(main_page)  # index 1
        self._stack.setCurrentIndex(0)
        self.setCentralWidget(self._stack)

        self._escalation_timer = QTimer(self)
        self._escalation_timer.setSingleShot(True)
        self._escalation_timer.timeout.connect(self._on_status_escalate)

        self.counter_changed.connect(self._on_counter_changed)
        self.group_reset_signal.connect(self._on_group_reset)
        self.connection_status_changed.connect(self._on_connection_status_changed)

    def show_configured(self) -> None:
        """Enter fullscreen kiosk mode if configured, otherwise a normal window."""
        if self._display_config.fullscreen:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.showFullScreen()
        else:
            self.showMaximized()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        branding = self._display_config.branding
        header = QWidget()
        header.setObjectName("header")
        header_height = int(_HEADER_HEIGHT_BASE * self._scale)
        header.setFixedHeight(header_height)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(16 * self._scale))

        has_logo = bool(branding.logo_path.strip())
        has_name = bool(branding.company_name.strip())

        pixmap = None
        if has_logo:
            # A lone logo can use almost the whole header height; paired
            # with the company name it's kept smaller so the text has
            # room to breathe next to it.
            fill_ratio = 0.9 if not has_name else 0.75
            pixmap = self._load_logo(branding.logo_path, int(header_height * fill_ratio))

        if pixmap is not None:
            logo_label = QLabel()
            logo_label.setPixmap(pixmap)
            layout.addWidget(
                logo_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        if has_name:
            name_label = QLabel(branding.company_name)
            name_label.setObjectName("companyName")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(name_label, stretch=1)
        else:
            layout.addStretch(1)

        layout.addWidget(
            self._badge, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        return header

    def _load_logo(self, logo_path: str, target_height: int) -> QPixmap | None:
        path = self._base_dir / logo_path
        if not path.is_file():
            get_logger().warning("Logo file not found, skipping: %s", logo_path)
            return None
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            get_logger().warning("Logo file could not be loaded, skipping: %s", logo_path)
            return None
        return pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)

    def _build_counter_grid(self, state: ApplicationState) -> QGridLayout:
        grid = QGridLayout()
        gap = int(20 * self._scale)
        grid.setHorizontalSpacing(gap)
        grid.setVerticalSpacing(gap)

        for group in build_display_model(state):
            counters = group.counters
            half = (len(counters) + 1) // 2
            left, right = counters[:half], counters[half:]
            for row, counter in enumerate(left):
                self._place_tile(grid, group.id, counter, row, 0)
            for row, counter in enumerate(right):
                self._place_tile(grid, group.id, counter, row, 1)

        for col in (0, 1):
            grid.setColumnStretch(col, 1)
        for row in range(grid.rowCount()):
            grid.setRowStretch(row, 1)

        return grid

    def _place_tile(
        self, grid: QGridLayout, group_id: int, counter: CounterDisplay, row: int, col: int
    ) -> None:
        tile = CounterTile(counter.name)
        tile.set_value(counter.token)
        grid.addWidget(tile, row, col)
        self._tiles[(group_id, counter.id)] = tile

    # ------------------------------------------------------------------
    # ApplicationState change listener slots
    # ------------------------------------------------------------------

    def _on_counter_changed(self, group_id: int, counter_id: int, counter: CounterState) -> None:
        tile = self._tiles.get((group_id, counter_id))
        if tile is None:
            return
        tile.set_value(format_token(counter.current_token))

    def _on_group_reset(self, group_id: int) -> None:
        for (g_id, _counter_id), tile in self._tiles.items():
            if g_id == group_id:
                tile.set_value(format_token(None))

    # ------------------------------------------------------------------
    # NetworkClient connection-status listener slot
    # ------------------------------------------------------------------

    def _on_connection_status_changed(self, status: ConnectionStatus) -> None:
        if status == ConnectionStatus.CONNECTED:
            self._escalation_timer.stop()
            if not self._ever_connected:
                self._ever_connected = True
                self._stack.setCurrentIndex(1)
            self._badge.set_status(_BADGE_COLOR_CONNECTED, "Connected")
            return

        # CONNECTING — either the initial connect or a retry after a drop.
        # Only (re)start the escalation timer at the start of an episode;
        # repeated CONNECTING notifications during backoff retries must not
        # keep resetting it.
        if not self._escalation_timer.isActive():
            self._escalation_timer.start(_STATUS_ESCALATION_MS)
        if not self._ever_connected:
            self._connecting_page.set_text("Connecting to device…")
        else:
            self._badge.set_status(_BADGE_COLOR_CONNECTING, "Reconnecting…")

    def _on_status_escalate(self) -> None:
        if not self._ever_connected:
            self._connecting_page.set_text("Unable to connect — check network")
        else:
            self._badge.set_status(_BADGE_COLOR_CONNECTING, "Connection lost — check network")

    # ------------------------------------------------------------------
    # Kiosk behaviour
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _build_stylesheet(self) -> str:
        fonts = self._display_config.fonts
        s = self._scale
        company_px = int(fonts.company_name * s)
        counter_name_px = int(fonts.counter_title * s)
        counter_value_px = int(fonts.token * s)
        border_radius = int(10 * s)
        border_width = max(1, int(2 * s))
        connecting_px = int(32 * s)
        badge_px = int(16 * s)

        return f"""
            #centralWidget {{ background-color: #14181f; }}
            #connectingPage {{ background-color: #14181f; }}
            #connectingLabel {{
                color: #9aa5b8;
                font-size: {connecting_px}px;
                font-weight: 500;
            }}
            #connectionBadge {{
                color: #9aa5b8;
                font-size: {badge_px}px;
            }}
            #companyName {{
                color: #f2f4f8;
                font-size: {company_px}px;
                font-weight: 600;
            }}
            #counterTile {{
                background-color: #1d2330;
                border: {border_width}px solid #3a4256;
                border-radius: {border_radius}px;
            }}
            #counterName {{
                color: #9aa5b8;
                font-size: {counter_name_px}px;
                font-weight: 500;
            }}
            #counterValue {{
                color: #4fd1c5;
                font-size: {counter_value_px}px;
                font-weight: 700;
            }}
        """