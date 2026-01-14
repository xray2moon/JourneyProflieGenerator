from __future__ import annotations

from pathlib import Path
from typing import Optional
from collections.abc import Callable

from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QBrush, QPainter
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGraphicsView,
    QGraphicsScene,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
)


class TimingConstraintDialog(QDialog):
    """
    Minimal dialog: arrival/departure time and point type.
    Times are free-form strings (e.g., '12:34:56').
    """

    def __init__(self, parent: QWidget, tp_id: int, existing: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Timing constraint for TP {tp_id}")

        self._arrival = QLineEdit()
        self._departure = QLineEdit()
        self._ptype = QComboBox()
        self._ptype.addItems(["STOP", "PASS"])

        if existing:
            self._arrival.setText(existing.get("arrivalTime", ""))
            self._departure.setText(existing.get("departureTime", ""))
            self._ptype.setCurrentText(existing.get("pointType", "STOP"))

        form = QFormLayout()
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)
        form.addRow("Point type", self._ptype)
        form.addRow("Arrival time", self._arrival)
        form.addRow("Departure time", self._departure)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 16)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def result_constraint(self) -> dict:
        return {
            "pointType": self._ptype.currentText(),
            "arrivalTime": self._arrival.text().strip(),
            "departureTime": self._departure.text().strip(),
        }


class ParameterView(QWidget):
    infrastructureLoadRequested = pyqtSignal(str)
    parametersChanged = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Infrastructure loader
        self._infra_path = QLineEdit()
        self._infra_path.setPlaceholderText("Select an infrastructure JSON file...")
        self._infra_browse = QPushButton("Browse…")
        self._infra_load = QPushButton("Load")
        self._infra_status = QLabel("No infrastructure loaded.")
        self._infra_status.setWordWrap(True)
        self._infra_status.setStyleSheet("color: #8e8e93; font-style: italic;")

        infra_path_row = QHBoxLayout()
        infra_path_row.setSpacing(8)
        infra_path_row.addWidget(self._infra_path, 1)
        infra_path_row.addWidget(self._infra_browse)
        infra_path_row.addWidget(self._infra_load)

        infra_box = QGroupBox("Infrastructure")
        infra_layout = QVBoxLayout(infra_box)
        infra_layout.setContentsMargins(12, 20, 12, 12)
        infra_layout.setSpacing(10)
        infra_layout.addLayout(infra_path_row)
        infra_layout.addWidget(self._infra_status)

        # Train and strategy parameters
        self._train_number = QLineEdit()
        self._train_number.setPlaceholderText("e.g. ICE 1234")

        self._train_type = QComboBox()
        self._train_type.addItems(["S1", "S2", "IC100", "RB20", "RB40", "RE50"])

        self._driving_strategy = QComboBox()
        self._driving_strategy.addItems(["Fastest", "Energy-efficient", "Coasting"])

        params_box = QGroupBox("Parameters")
        params_form = QFormLayout(params_box)
        params_form.setContentsMargins(12, 20, 12, 12)
        params_form.setSpacing(12)
        params_form.addRow("Train number", self._train_number)
        params_form.addRow("Train type", self._train_type)
        params_form.addRow("Driving strategy", self._driving_strategy)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addWidget(infra_box)
        layout.addWidget(params_box)
        layout.addStretch(1)
        self.setLayout(layout)

        self._infra_browse.clicked.connect(self._browse_infra_json)
        self._infra_load.clicked.connect(self._request_load)

        self._train_number.textChanged.connect(self._emit_parameters_changed)
        self._train_type.currentTextChanged.connect(self._emit_parameters_changed)
        self._driving_strategy.currentTextChanged.connect(self._emit_parameters_changed)

    def set_infrastructure_summary(
        self,
        json_path: str,
        *,
        nodes: int,
        tracks: int,
        timing_points: int,
        stopping_locations: int,
    ) -> None:
        self._infra_path.setText(json_path)
        self._infra_status.setText(
            f"Loaded: {json_path}\n"
            f"Nodes: {nodes} | Tracks: {tracks} | Timing points: {timing_points} | Stopping locations: {stopping_locations}"
        )

    def set_infrastructure_error(self, json_path: str, message: str) -> None:
        self._infra_path.setText(json_path)
        self._infra_status.setText(f"Failed to load: {json_path}\n{message}")

    def parameters(self) -> dict:
        return {
            "trainNumber": self._train_number.text().strip(),
            "trainType": self._train_type.currentText(),
            "drivingStrategy": self._driving_strategy.currentText(),
        }

    def _emit_parameters_changed(self) -> None:
        self.parametersChanged.emit(self.parameters())

    def _browse_infra_json(self) -> None:
        current = self._infra_path.text().strip()
        start_dir = str(Path(current).expanduser().parent) if current else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open infrastructure JSON",
            start_dir,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        self._infra_path.setText(path)

    def _request_load(self) -> None:
        path = self._infra_path.text().strip()
        if not path:
            QMessageBox.information(self, "No file selected", "Please select an infrastructure JSON file.")
            return
        self.infrastructureLoadRequested.emit(path)


class SettingsView(QWidget):
    themeChanged = pyqtSignal(str)  # "light" or "dark"
    showAllTimingPointsChanged = pyqtSignal(bool)
    keepSelectionChanged = pyqtSignal(bool)
    showLegendChanged = pyqtSignal(bool)
    defaultViewChanged = pyqtSignal(str)  # "Geographic", "Schematic"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Light", "Dark"])
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)

        from PyQt6.QtWidgets import QCheckBox
        self._show_all_tp_check = QCheckBox("Show all timing points")
        self._show_all_tp_check.toggled.connect(self.showAllTimingPointsChanged.emit)

        self._keep_selection_check = QCheckBox("Keep timing points visible on selection")
        self._keep_selection_check.toggled.connect(self.keepSelectionChanged.emit)

        self._show_legend_check = QCheckBox("Show Legend")
        self._show_legend_check.setChecked(True)
        self._show_legend_check.toggled.connect(self.showLegendChanged.emit)

        self._default_view_combo = QComboBox()
        self._default_view_combo.addItems(["Geographic", "Schematic"])
        self._default_view_combo.currentTextChanged.connect(self.defaultViewChanged.emit)

        layout = QFormLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.addRow("Theme", self._theme_combo)
        layout.addRow("", self._show_all_tp_check)
        layout.addRow("", self._keep_selection_check)
        layout.addRow("", self._show_legend_check)
        layout.addRow("Default View", self._default_view_combo)

        # Add some stretch to push it to the top
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(layout)
        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def _on_theme_changed(self, text: str):
        self.themeChanged.emit(text.lower())


class PanZoomGraphicsView(QGraphicsView):
    """QGraphicsView with mouse-wheel zoom and two pan modes:
    - Middle mouse button drag
    - Hold Space and drag with left mouse (hand tool)
    - Left mouse drag on empty background
    """

    def __init__(self, scene: QGraphicsScene, parent: Optional[QWidget] = None):
        super().__init__(scene, parent)

        # Professional look
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        # Nicer zoom behavior
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Middle-button panning state
        self._panning_middle = False
        self._panning_left_background = False
        self._last_mouse_pos = None
        self._can_start_background_pan: Optional[Callable[[QPointF], bool]] = None

        # Space-to-pan state (Space is NOT a Qt "modifier", we track it ourselves)
        self._space_pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = 1.0015 ** angle
        self.scale(factor, factor)

    def set_can_start_background_pan(self, predicate: Optional[Callable[[QPointF], bool]]) -> None:
        self._can_start_background_pan = predicate

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self._space_pressed:
            self._space_pressed = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self._space_pressed:
            self._space_pressed = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning_middle = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._space_pressed
        ):
            can_pan = self.itemAt(event.pos()) is None
            if self._can_start_background_pan is not None:
                can_pan = self._can_start_background_pan(self.mapToScene(event.pos()))
            if can_pan:
                self._panning_left_background = True
                self._last_mouse_pos = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._panning_middle or self._panning_left_background) and self._last_mouse_pos is not None:
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning_middle and event.button() == Qt.MouseButton.MiddleButton:
            self._panning_middle = False
            self._last_mouse_pos = None
            # If space is currently held, go back to open hand; otherwise arrow.
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space_pressed else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._panning_left_background and event.button() == Qt.MouseButton.LeftButton:
            self._panning_left_background = False
            self._last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
