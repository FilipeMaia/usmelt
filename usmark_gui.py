import sys
import math
import copy
import configparser
from pathlib import Path

import winsound

from PIL import Image, ImageDraw, ImageFont

from PySide6.QtCore import Qt, QRectF, QPoint, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

# ----------------------------------------------------------------------
# USMELT / TG5012A
# ----------------------------------------------------------------------

import usmelt


# ----------------------------------------------------------------------
# Marker data
# ----------------------------------------------------------------------

class Marker:
    def __init__(self, x, y, size=15, voltage=0.0, is_test=False):
        self.x = float(x)
        self.y = float(y)
        self.size = int(size)
        self.voltage = float(voltage)
        self.is_test = bool(is_test)


# ----------------------------------------------------------------------
# Image canvas
# ----------------------------------------------------------------------

class ImageCanvas(QWidget):
    marker_added = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumSize(500, 500)
        self.setMouseTracking(True)

        self.base_image = None
        self.display_image = None
        self.display_pixmap = QPixmap()
        self.display_rect = QRectF()

        self.zoom = 1.0
        self.rotation = 0.0

        self.pan_x = 0.0
        self.pan_y = 0.0

        self.markers = []

        self.middle_dragging = False
        self.last_mouse_pos = QPoint()

    # ------------------------------------------------------------------

    def set_image(self, image):
        self.base_image = image.copy()
        self.zoom = 1.0
        self.rotation = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.markers = []
        self.render_image()

    # ------------------------------------------------------------------

    def set_markers(self, markers):
        self.markers = markers
        self.render_image()

    # ------------------------------------------------------------------

    def set_rotation(self, angle):
        self.rotation = float(angle)
        self.render_image()

    # ------------------------------------------------------------------

    def reset_view(self):
        self.zoom = 1.0
        self.rotation = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.render_image()

    # ------------------------------------------------------------------

    def zoom_by(self, factor, center=None):
        old_zoom = self.zoom
        self.zoom *= factor
        self.zoom = max(0.05, min(self.zoom, 20.0))

        if center is None:
            center = QPoint(self.width() // 2, self.height() // 2)

        if old_zoom != self.zoom:
            scale = self.zoom / old_zoom

            cx = center.x()
            cy = center.y()

            self.pan_x = cx - (cx - self.pan_x) * scale
            self.pan_y = cy - (cy - self.pan_y) * scale

        self.render_image()

    # ------------------------------------------------------------------

    def pil_to_qpixmap(self, image):
        rgb = image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")

        qimage = QImage(
            data,
            rgb.width,
            rgb.height,
            rgb.width * 3,
            QImage.Format_RGB888,
        ).copy()

        return QPixmap.fromImage(qimage)

    # ------------------------------------------------------------------

    def render_image(self):
        if self.base_image is None:
            self.display_image = None
            self.display_pixmap = QPixmap()
            self.update()
            return

        image = self.base_image.copy()

        # Draw markers on the unrotated base image.
        draw = ImageDraw.Draw(image)

        for marker in self.markers:
            if marker.is_test:
                fill = (255, 0, 0)
            else:
                fill = self.voltage_to_color(marker.voltage)

            r = marker.size / 2.0

            bbox = [
                marker.x - r,
                marker.y - r,
                marker.x + r,
                marker.y + r,
            ]

            draw.ellipse(
                bbox,
                fill=fill,
                outline=(0, 0, 0),
                width=max(1, int(marker.size / 8)),
            )

        if abs(self.rotation) > 1e-9:
            image = image.rotate(
                self.rotation,
                expand=True,
                fillcolor=(30, 30, 30),
            )

        self.display_image = image
        self.display_pixmap = self.pil_to_qpixmap(image)

        self.update_display_rect()

    # ------------------------------------------------------------------

    def voltage_to_color(self, voltage):
        parent = self.parent()

        if parent is None or not hasattr(parent, "color_min"):
            return (0, 120, 255)

        app = parent

        vmin = app.color_min
        vmax = app.color_max

        if vmax <= vmin:
            return (0, 120, 255)

        t = (voltage - vmin) / (vmax - vmin)
        t = max(0.0, min(1.0, t))

        # Blue -> green -> yellow -> orange.
        if t < 1 / 3:
            u = t * 3
            r = 0
            g = int(255 * u)
            b = int(255 * (1 - u))

        elif t < 2 / 3:
            u = (t - 1 / 3) * 3
            r = int(255 * u)
            g = 255
            b = 0

        else:
            u = (t - 2 / 3) * 3
            r = 255
            g = int(255 * (1 - u))
            b = 0

        return (r, g, b)

    # ------------------------------------------------------------------

    def update_display_rect(self):
        if self.display_pixmap.isNull():
            self.display_rect = QRectF()
            self.update()
            return

        iw = self.display_pixmap.width()
        ih = self.display_pixmap.height()

        available_w = self.width()
        available_h = self.height()

        scale = min(
            available_w / iw,
            available_h / ih,
        )

        scale *= self.zoom

        w = iw * scale
        h = ih * scale

        x = (available_w - w) / 2.0 + self.pan_x
        y = (available_h - h) / 2.0 + self.pan_y

        self.display_rect = QRectF(x, y, w, h)

        self.update()

    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        self.update_display_rect()
        super().resizeEvent(event)

    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(
            self.rect(),
            QColor(25, 25, 25),
        )

        if self.display_pixmap.isNull():
            painter.setPen(Qt.white)

            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "Open an image",
            )

            return

        source_rect = QRectF(
            0,
            0,
            self.display_pixmap.width(),
            self.display_pixmap.height(),
        )

        painter.drawPixmap(
            self.display_rect,
            self.display_pixmap,
            source_rect,
        )

    # ------------------------------------------------------------------

    def widget_to_rotated_image(self, pos):
        if self.display_pixmap.isNull():
            return None

        if (
            self.display_rect.width() <= 0
            or self.display_rect.height() <= 0
        ):
            return None

        x = (
            (pos.x() - self.display_rect.left())
            * self.display_pixmap.width()
            / self.display_rect.width()
        )

        y = (
            (pos.y() - self.display_rect.top())
            * self.display_pixmap.height()
            / self.display_rect.height()
        )

        return x, y

    # ------------------------------------------------------------------

    def rotated_to_base_image(self, x, y):
        if self.base_image is None or self.display_image is None:
            return None

        cx_rotated = self.display_image.width / 2.0
        cy_rotated = self.display_image.height / 2.0

        cx_base = self.base_image.width / 2.0
        cy_base = self.base_image.height / 2.0

        dx = x - cx_rotated
        dy = y - cy_rotated

        theta = math.radians(self.rotation)

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        base_dx = dx * cos_t - dy * sin_t
        base_dy = dx * sin_t + dy * cos_t

        bx = base_dx + cx_base
        by = base_dy + cy_base

        return bx, by

    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.middle_dragging = True
            self.last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.LeftButton:
            rotated = self.widget_to_rotated_image(
                event.position().toPoint()
            )

            if rotated is None:
                return

            base = self.rotated_to_base_image(
                *rotated
            )

            if base is None:
                return

            bx, by = base

            if (
                self.base_image is not None
                and 0 <= bx < self.base_image.width
                and 0 <= by < self.base_image.height
            ):
                self.marker_added.emit(bx, by)

    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event):
        if self.middle_dragging:
            current = event.position().toPoint()

            delta = current - self.last_mouse_pos

            self.pan_x += delta.x()
            self.pan_y += delta.y()

            self.last_mouse_pos = current

            self.update_display_rect()

    # ------------------------------------------------------------------

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.middle_dragging = False
            self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        delta = event.angleDelta().y()

        if delta > 0:
            self.zoom_by(
                1.15,
                event.position().toPoint(),
            )

        elif delta < 0:
            self.zoom_by(
                1 / 1.15,
                event.position().toPoint(),
            )


# ----------------------------------------------------------------------
# USMELT waveform preview
# ----------------------------------------------------------------------

class WaveformPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.v1 = 1.0
        self.t1 = 10.0
        self.v2 = 2.0
        self.t2 = 10.0
        self.delay = 0.0

        self.setMinimumSize(400, 250)

    # ------------------------------------------------------------------

    def set_values(self, v1, t1, v2, t2, delay):
        self.v1 = v1
        self.t1 = t1
        self.v2 = v2
        self.t2 = t2
        self.delay = delay

        self.update()

    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(
            self.rect(),
            Qt.white,
        )

        width = self.width()
        height = self.height()

        left = 55
        right = 20
        top = 20
        bottom = 45

        plot_w = width - left - right
        plot_h = height - top - bottom

        if plot_w <= 0 or plot_h <= 0:
            return

        total_time = (
            max(0.0, self.delay)
            + max(0.0, self.t1)
            + max(0.0, self.t2)
            + 10.0
        )

        if total_time <= 0:
            total_time = 1.0

        max_voltage = max(
            abs(self.v1),
            abs(self.v2),
            1.0,
        )

        # Grid.
        painter.setPen(
            QPen(
                QColor(220, 220, 220),
                1,
            )
        )

        for i in range(6):
            x = left + plot_w * i / 5

            painter.drawLine(
                int(x),
                top,
                int(x),
                top + plot_h,
            )

        for i in range(5):
            y = top + plot_h * i / 4

            painter.drawLine(
                left,
                int(y),
                left + plot_w,
                int(y),
            )

        # Axes.
        painter.setPen(
            QPen(
                Qt.black,
                1,
            )
        )

        painter.drawLine(
            left,
            top,
            left,
            top + plot_h,
        )

        painter.drawLine(
            left,
            top + plot_h,
            left + plot_w,
            top + plot_h,
        )

        def tx(t):
            return left + (t / total_time) * plot_w

        def ty(v):
            return (
                top
                + plot_h / 2
                - (v / max_voltage)
                * (plot_h / 2)
            )

        points = []

        t = 0.0

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        # Delay.
        t += max(
            0.0,
            self.delay,
        )

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        # V1.
        points.append(
            (
                tx(t),
                ty(self.v1),
            )
        )

        t += max(
            0.0,
            self.t1,
        )

        points.append(
            (
                tx(t),
                ty(self.v1),
            )
        )

        # V2.
        points.append(
            (
                tx(t),
                ty(self.v2),
            )
        )

        t += max(
            0.0,
            self.t2,
        )

        points.append(
            (
                tx(t),
                ty(self.v2),
            )
        )

        # 10 us tail.
        t += 10.0

        points.append(
            (
                tx(t),
                ty(0.0),
            )
        )

        polygon = QPolygonF(
            [
                QPoint(
                    int(x),
                    int(y),
                )
                for x, y in points
            ]
        )

        # Filled waveform.
        fill_path = QPainterPath()

        fill_path.moveTo(
            points[0][0],
            top + plot_h / 2,
        )

        for x, y in points:
            fill_path.lineTo(
                x,
                y,
            )

        fill_path.lineTo(
            points[-1][0],
            top + plot_h / 2,
        )

        fill_path.closeSubpath()

        painter.fillPath(
            fill_path,
            QColor(220, 235, 255),
        )

        # Waveform line.
        painter.setPen(
            QPen(
                QColor(0, 90, 200),
                2,
            )
        )

        painter.drawPolyline(
            polygon
        )

        # Labels.
        painter.setPen(Qt.black)

        painter.setFont(
            QFont(
                "Helvetica",
                8,
            )
        )

        painter.drawText(
            5,
            top + 5,
            f"{max_voltage:.2f} V",
        )

        painter.drawText(
            5,
            top + plot_h - 2,
            f"{-max_voltage:.2f} V",
        )

        painter.drawText(
            left + plot_w // 2 - 25,
            height - 8,
            "time (us)",
        )

        painter.drawText(
            8,
            top + plot_h // 2,
            "0 V",
        )


# ----------------------------------------------------------------------
# USMELT controller
# ----------------------------------------------------------------------

class MelterPanel(QGroupBox):
    voltage_high1_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(
            "USMELT",
            parent,
        )

        self.pg = None
        self.device_name = ""

        self.config_path = Path(
            "usmelt.ini"
        )

        self.config = configparser.ConfigParser()

        if self.config_path.exists():
            self.config.read(
                self.config_path
            )

        self.melt_sound = self.config.getboolean(
            "General",
            "MeltSound",
            fallback=True,
        )

        self.use_shaping_value = self.config.getboolean(
            "PulseShaping",
            "UseShaping",
            fallback=False,
        )

        self.shaping_v1 = self.config.getfloat(
            "PulseShaping",
            "V1",
            fallback=5.0,
        )

        self.shaping_t1 = self.config.getfloat(
            "PulseShaping",
            "T1",
            fallback=10.0,
        )

        self.shaping_v2 = self.config.getfloat(
            "PulseShaping",
            "V2",
            fallback=2.5,
        )

        self.shaping_t2 = self.config.getfloat(
            "PulseShaping",
            "T2",
            fallback=10.0,
        )

        self.build_ui()

        # IMPORTANT:
        # Use the original USMELT discovery and initialization path.
        self.find_and_init_pg()

        self.update_channel_states()

    # ------------------------------------------------------------------

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        channels = QGridLayout()

        channels.setHorizontalSpacing(8)
        channels.setVerticalSpacing(5)

        # --------------------------------------------------------------
        # Channel 1
        # --------------------------------------------------------------

        ch1_group = QGroupBox(
            "Channel 1"
        )

        ch1_layout = QGridLayout(
            ch1_group
        )

        self.enable_ch1 = QCheckBox(
            "Enable"
        )

        self.enable_ch1.toggled.connect(
            self.toggle_ch1_elements
        )

        self.pulse_length1_entry = QLineEdit(
            "20"
        )

        self.voltage_high1_entry = QLineEdit(
            "5"
        )

        self.delay1_entry = QLineEdit(
            "0"
        )

        ch1_layout.addWidget(
            self.enable_ch1,
            0,
            0,
            1,
            2,
        )

        ch1_layout.addWidget(
            QLabel("Pulse Length (us)"),
            1,
            0,
        )

        ch1_layout.addWidget(
            self.pulse_length1_entry,
            1,
            1,
        )

        ch1_layout.addWidget(
            QLabel("Voltage High (V)"),
            2,
            0,
        )

        ch1_layout.addWidget(
            self.voltage_high1_entry,
            2,
            1,
        )

        ch1_layout.addWidget(
            QLabel("Delay (us)"),
            3,
            0,
        )

        ch1_layout.addWidget(
            self.delay1_entry,
            3,
            1,
        )

        self.use_shaping = QCheckBox(
            "Use Shaping"
        )

        self.use_shaping.setChecked(
            self.use_shaping_value
        )

        self.use_shaping.toggled.connect(
            self.on_shaping_toggled
        )

        self.setup_shaping_button = QPushButton(
            "Setup Shaping"
        )

        self.setup_shaping_button.clicked.connect(
            self.open_shaping_dialog
        )

        ch1_layout.addWidget(
            self.use_shaping,
            4,
            0,
            1,
            2,
        )

        ch1_layout.addWidget(
            self.setup_shaping_button,
            5,
            0,
            1,
            2,
        )

        # --------------------------------------------------------------
        # Channel 2
        # --------------------------------------------------------------

        ch2_group = QGroupBox(
            "Channel 2"
        )

        ch2_layout = QGridLayout(
            ch2_group
        )

        self.enable_ch2 = QCheckBox(
            "Enable"
        )

        self.enable_ch2.toggled.connect(
            self.toggle_ch2_elements
        )

        self.pulse_length2_entry = QLineEdit(
            "20"
        )

        self.voltage_high2_entry = QLineEdit(
            "5"
        )

        self.delay2_entry = QLineEdit(
            "0"
        )

        ch2_layout.addWidget(
            self.enable_ch2,
            0,
            0,
            1,
            2,
        )

        ch2_layout.addWidget(
            QLabel("Pulse Length (us)"),
            1,
            0,
        )

        ch2_layout.addWidget(
            self.pulse_length2_entry,
            1,
            1,
        )

        ch2_layout.addWidget(
            QLabel("Voltage High (V)"),
            2,
            0,
        )

        ch2_layout.addWidget(
            self.voltage_high2_entry,
            2,
            1,
        )

        ch2_layout.addWidget(
            QLabel("Delay (us)"),
            3,
            0,
        )

        ch2_layout.addWidget(
            self.delay2_entry,
            3,
            1,
        )

        channels.addWidget(
            ch1_group,
            0,
            0,
        )

        channels.addWidget(
            ch2_group,
            0,
            1,
        )

        main_layout.addLayout(
            channels
        )

        # --------------------------------------------------------------
        # Melt button
        # --------------------------------------------------------------

        self.melt_button = QPushButton(
            "Melt"
        )

        self.melt_button.setMinimumHeight(
            36
        )

        self.melt_button.clicked.connect(
            self.melt
        )

        main_layout.addWidget(
            self.melt_button
        )

        # Monitor current CH1 voltage field.
        self.voltage_high1_entry.textChanged.connect(
            self.on_voltage_high1_changed
        )

    # ------------------------------------------------------------------

    def find_and_init_pg(self):
        """
        Original USMELT device discovery and initialization.

        IMPORTANT:
        usmelt.discover() returns a dictionary keyed by device type.
        """

        self.device_name = ""

        # First find the USB device that corresponds
        # to the pulse generator.
        device = usmelt.discover(
            ["TG5012A"]
        )

        self.device_name = device[
            "TG5012A"
        ].device

        self.pg = usmelt.TG5012A(
            serial_port=self.device_name
        )

        self.init_pg()

    # ------------------------------------------------------------------

    def init_pg(self):
        """
        Original TG5012A initialization.
        """

        # --- Channel 1 settings ---
        self.pg.channel(1)
        self.pg.wave("PULSE")
        self.pg.pulse_period(
            10e-3
        )
        self.pg.high(1)
        self.pg.low(0)
        self.pg.pulse_rise(
            10e-9
        )
        self.pg.pulse_fall(
            10e-9
        )
        self.pg.pulse_delay(0)
        self.pg.burst("OFF")
        self.pg.burst_count(1)
        self.pg.trigger_src("MAN")
        self.pg.output("OFF")

        # --- Channel 2 settings ---
        self.pg.channel(2)
        self.pg.wave("PULSE")
        self.pg.pulse_period(
            10e-3
        )
        self.pg.high(1)
        self.pg.low(0)
        self.pg.pulse_rise(
            10e-9
        )
        self.pg.pulse_fall(
            10e-9
        )
        self.pg.pulse_delay(0)
        self.pg.burst("OFF")
        self.pg.burst_count(1)

        # Take trigger from channel 1.
        self.pg.trigger_src("CRC")
        self.pg.output("OFF")

    # ------------------------------------------------------------------

    def on_voltage_high1_changed(self):
        self.voltage_high1_changed.emit()

    # ------------------------------------------------------------------

    def get_voltage_high1(self):
        try:
            return float(
                self.voltage_high1_entry.text().strip()
            )
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------

    def toggle_ch1_elements(self):
        enabled = self.enable_ch1.isChecked()
        shaping = self.use_shaping.isChecked()

        # Delay is available whenever CH1 is enabled.
        self.delay1_entry.setEnabled(
            enabled
        )

        # Standard pulse length is disabled during shaping.
        self.pulse_length1_entry.setEnabled(
            enabled and not shaping
        )

        # Voltage remains available because the marker software
        # monitors it continuously.
        self.voltage_high1_entry.setEnabled(
            enabled
        )

        self.use_shaping.setEnabled(
            enabled
        )

        self.setup_shaping_button.setEnabled(
            enabled
        )

    # ------------------------------------------------------------------

    def toggle_ch2_elements(self):
        enabled = self.enable_ch2.isChecked()

        self.pulse_length2_entry.setEnabled(
            enabled
        )

        self.voltage_high2_entry.setEnabled(
            enabled
        )

        self.delay2_entry.setEnabled(
            enabled
        )

    # ------------------------------------------------------------------

    def update_channel_states(self):
        self.toggle_ch1_elements()
        self.toggle_ch2_elements()

    # ------------------------------------------------------------------

    def on_shaping_toggled(self, checked):
        self.use_shaping_value = checked

        self.toggle_ch1_elements()
        self.save_settings()

    # ------------------------------------------------------------------

    def save_settings(self):
        if not self.config.has_section(
            "General"
        ):
            self.config.add_section(
                "General"
            )

        if not self.config.has_section(
            "PulseShaping"
        ):
            self.config.add_section(
                "PulseShaping"
            )

        self.config.set(
            "General",
            "MeltSound",
            str(self.melt_sound),
        )

        self.config.set(
            "PulseShaping",
            "UseShaping",
            str(
                self.use_shaping.isChecked()
            ),
        )

        self.config.set(
            "PulseShaping",
            "V1",
            str(self.shaping_v1),
        )

        self.config.set(
            "PulseShaping",
            "T1",
            str(self.shaping_t1),
        )

        self.config.set(
            "PulseShaping",
            "V2",
            str(self.shaping_v2),
        )

        self.config.set(
            "PulseShaping",
            "T2",
            str(self.shaping_t2),
        )

        try:
            with self.config_path.open(
                "w",
                encoding="utf-8",
            ) as f:
                self.config.write(f)

        except Exception as exc:
            QMessageBox.warning(
                self,
                "USMELT",
                f"Could not save settings:\n\n{exc}",
            )

    # ------------------------------------------------------------------

    def validate_float(self, widget, name):
        text = widget.text().strip()

        try:
            return float(text)

        except ValueError:
            raise ValueError(
                f"{name} must be a valid number."
            )

    # ------------------------------------------------------------------

    def validate_inputs(self):
        try:
            # ==========================================================
            # CH1
            # ==========================================================

            delay1 = self.validate_float(
                self.delay1_entry,
                "Channel 1 delay",
            )

            if delay1 < 0:
                raise ValueError(
                    "Channel 1 delay must be >= 0."
                )

            if self.enable_ch1.isChecked():

                if self.use_shaping.isChecked():
                    pulse_length1 = 0.0
                    voltage_high1 = 0.0

                else:
                    # Read CURRENT GUI values.
                    pulse_length1 = self.validate_float(
                        self.pulse_length1_entry,
                        "Channel 1 pulse length",
                    )

                    voltage_high1 = self.validate_float(
                        self.voltage_high1_entry,
                        "Channel 1 voltage high",
                    )

                    if pulse_length1 <= 0:
                        raise ValueError(
                            "Channel 1 pulse length must be > 0."
                        )

                    if voltage_high1 <= 0:
                        raise ValueError(
                            "Channel 1 voltage high must be > 0."
                        )

            else:
                pulse_length1 = 0.0
                voltage_high1 = 0.0

            # ==========================================================
            # CH2
            # ==========================================================

            if self.enable_ch2.isChecked():

                # Read CURRENT GUI values.
                pulse_length2 = self.validate_float(
                    self.pulse_length2_entry,
                    "Channel 2 pulse length",
                )

                voltage_high2 = self.validate_float(
                    self.voltage_high2_entry,
                    "Channel 2 voltage high",
                )

                delay2 = self.validate_float(
                    self.delay2_entry,
                    "Channel 2 delay",
                )

                if pulse_length2 <= 0:
                    raise ValueError(
                        "Channel 2 pulse length must be > 0."
                    )

                if voltage_high2 <= 0:
                    raise ValueError(
                        "Channel 2 voltage high must be > 0."
                    )

                if delay2 < 0:
                    raise ValueError(
                        "Channel 2 delay must be >= 0."
                    )

            else:
                pulse_length2 = 0.0
                voltage_high2 = 0.0
                delay2 = 0.0

            return {
                "pulse_length1": pulse_length1,
                "voltage_high1": voltage_high1,
                "delay1": delay1,
                "pulse_length2": pulse_length2,
                "voltage_high2": voltage_high2,
                "delay2": delay2,
            }

        except ValueError as exc:
            QMessageBox.critical(
                self,
                "Invalid Input",
                str(exc),
            )

            return None

    # ------------------------------------------------------------------

    def read_shaping_parameters(self):
        try:
            v1 = float(
                self.shaping_v1
            )

            t1 = float(
                self.shaping_t1
            )

            v2 = float(
                self.shaping_v2
            )

            t2 = float(
                self.shaping_t2
            )

            if v1 < 0 or v2 < 0:
                raise ValueError(
                    "Shaping voltages must be >= 0."
                )

            if t1 <= 0:
                raise ValueError(
                    "T1 must be > 0."
                )

            if t2 <= 0:
                raise ValueError(
                    "T2 must be > 0."
                )

            return v1, t1, v2, t2

        except (TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Invalid Shaping Parameters",
                str(exc),
            )

            return None

    # ------------------------------------------------------------------

    def melt(self):
        """
        Program TG5012A using CURRENT GUI values.

        The hardware API calls follow the original USMELT code.
        """

        if self.pg is None:
            QMessageBox.critical(
                self,
                "Device Error",
                "Pulse generator not initialized.",
            )
            return

        ch1_params, ch2_params = (
            None,
            None,
        )

        params = self.validate_inputs()

        if params is None:
            return

        pulse_length1 = params[
            "pulse_length1"
        ]

        voltage_high1 = params[
            "voltage_high1"
        ]

        delay1 = params[
            "delay1"
        ]

        pulse_length2 = params[
            "pulse_length2"
        ]

        voltage_high2 = params[
            "voltage_high2"
        ]

        delay2 = params[
            "delay2"
        ]

        try:
            # ==========================================================
            # CHANNEL 1
            # ==========================================================

            if self.enable_ch1.isChecked():

                if self.use_shaping.isChecked():

                    shaping = (
                        self.read_shaping_parameters()
                    )

                    if shaping is None:
                        return

                    v1, t1, v2, t2 = shaping

                    t_tail = 10.0

                    t_total = (
                        delay1
                        + t1
                        + t2
                        + t_tail
                    )

                    num_points = 10000

                    n_delay = int(
                        round(
                            num_points
                            * delay1
                            / t_total
                        )
                    )

                    n_t1 = int(
                        round(
                            num_points
                            * t1
                            / t_total
                        )
                    )

                    n_t2 = int(
                        round(
                            num_points
                            * t2
                            / t_total
                        )
                    )

                    n_tail = (
                        num_points
                        - n_delay
                        - n_t1
                        - n_t2
                    )

                    # Keep the original waveform construction.
                    voltages = (
                        [0.0]
                        + [0.0] * n_delay
                        + [v1] * n_t1
                        + [v2] * n_t2
                        + [0.0] * n_tail
                    )

                    vmin = min(
                        0.0,
                        v1,
                        v2,
                    )

                    vmax = max(
                        0.0,
                        v1,
                        v2,
                    )

                    vpp = vmax - vmin

                    if vpp < 0.01:
                        vpp = 0.01

                    voffset = (
                        vmax + vmin
                    ) / 2.0

                    # Scale to 14-bit.
                    points = []

                    for v in voltages:
                        y = int(
                            round(
                                (2**14 - 1)
                                * (
                                    v / vpp
                                )
                            )
                        )

                        y = max(
                            0,
                            min(
                                2**14 - 1,
                                y,
                            ),
                        )

                        points.append(y)

                    print(
                        f"CH1 (Shaping): "
                        f"V1: {v1}V for {t1}us, "
                        f"V2: {v2}V for {t2}us, "
                        f"Delay: {delay1}us, "
                        f"Vpp: {vpp:.3f}V, "
                        f"Voffset: {voffset:.3f}V"
                    )

                    # Original TG5012A programming.
                    self.pg.channel(1)
                    self.pg.output_load(50)

                    self.pg.upload_arb(
                        "ARB1",
                        points,
                        interpolation="OFF",
                    )

                    self.pg.set(
                        "ARBLOAD",
                        "ARB1",
                    )

                    self.pg.wave(
                        "ARB"
                    )

                    self.pg.offset(
                        voffset
                    )

                    self.pg.amplitude(
                        vpp
                    )

                    self.pg.period(
                        t_total * 1e-6
                    )

                    self.pg.burst(
                        "NCYC"
                    )

                    self.pg.burst_count(1)

                    self.pg.trigger_src(
                        "MAN"
                    )

                    self.pg.output(
                        "ON"
                    )

                else:
                    # --------------------------------------------------
                    # STANDARD CH1
                    #
                    # These values are read immediately from the
                    # current GUI contents by validate_inputs().
                    # --------------------------------------------------

                    print(
                        f"CH1: "
                        f"Pulse: {pulse_length1}us, "
                        f"Voltage: {voltage_high1}V, "
                        f"Delay: {delay1}us"
                    )

                    self.pg.channel(1)
                    self.pg.output_load(50)
                    self.pg.wave("PULSE")
                    self.pg.burst("NCYC")
                    self.pg.burst_count(1)
                    self.pg.trigger_src("MAN")

                    self.pg.pulse_width(
                        pulse_length1 * 1e-6
                    )

                    # The order between low and high matters.
                    self.pg.low(0.0)

                    self.pg.high(
                        voltage_high1
                    )

                    self.pg.pulse_delay(
                        delay1 * 1e-6
                    )

                    self.pg.output("ON")

            else:
                self.pg.channel(1)
                self.pg.output("OFF")

            # ==========================================================
            # CHANNEL 2
            # ==========================================================

            if self.enable_ch2.isChecked():

                print(
                    f"CH2: "
                    f"Pulse: {pulse_length2}us, "
                    f"Voltage: {voltage_high2}V, "
                    f"Delay: {delay2}us"
                )

                self.pg.channel(2)
                self.pg.output_load(50)
                self.pg.wave("PULSE")
                self.pg.burst("NCYC")
                self.pg.burst_count(1)
                self.pg.trigger_src("CRC")

                self.pg.pulse_width(
                    pulse_length2 * 1e-6
                )

                # The order between low and high matters.
                self.pg.low(0.0)

                self.pg.high(
                    voltage_high2
                )

                self.pg.pulse_delay(
                    delay2 * 1e-6
                )

                self.pg.output("ON")

            else:
                self.pg.channel(2)
                self.pg.output("OFF")

            # ==========================================================
            # SOUND + TRIGGER
            # ==========================================================

            if (
                self.enable_ch1.isChecked()
                or self.enable_ch2.isChecked()
            ):

                if self.melt_sound:
                    sound_effect_path = (
                        Path(__file__).parent
                        / "sounds"
                        / "short-laser-sfx.wav"
                    )

                    winsound.PlaySound(
                        str(sound_effect_path),
                        winsound.SND_FILENAME,
                    )

                self.pg.channel(1)

                self.pg.trigger()

                # Disable both outputs after the pulse.
                self.pg.channel(1)
                self.pg.output("OFF")

                self.pg.channel(2)
                self.pg.output("OFF")

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Melt Error",
                f"Could not execute melt:\n\n{exc}",
            )

            try:
                if self.pg is not None:
                    self.pg.channel(1)
                    self.pg.output("OFF")

                    self.pg.channel(2)
                    self.pg.output("OFF")

            except Exception:
                pass

    # ------------------------------------------------------------------

    def open_shaping_dialog(self):
        dialog = QDialog(
            self
        )

        dialog.setWindowTitle(
            "Pulse Shaping"
        )

        dialog.setModal(True)

        layout = QVBoxLayout(
            dialog
        )

        content = QHBoxLayout()

        # --------------------------------------------------------------
        # Parameters
        # --------------------------------------------------------------

        parameter_group = QGroupBox(
            "Pulse Parameters"
        )

        form = QFormLayout(
            parameter_group
        )

        v1_entry = QLineEdit(
            str(self.shaping_v1)
        )

        t1_entry = QLineEdit(
            str(self.shaping_t1)
        )

        v2_entry = QLineEdit(
            str(self.shaping_v2)
        )

        t2_entry = QLineEdit(
            str(self.shaping_t2)
        )

        form.addRow(
            "V1 (V)",
            v1_entry,
        )

        form.addRow(
            "T1 (us)",
            t1_entry,
        )

        form.addRow(
            "V2 (V)",
            v2_entry,
        )

        form.addRow(
            "T2 (us)",
            t2_entry,
        )

        content.addWidget(
            parameter_group
        )

        # --------------------------------------------------------------
        # Preview
        # --------------------------------------------------------------

        preview_group = QGroupBox(
            "Waveform Preview"
        )

        preview_layout = QVBoxLayout(
            preview_group
        )

        preview = WaveformPreview()

        preview_layout.addWidget(
            preview
        )

        content.addWidget(
            preview_group
        )

        layout.addLayout(
            content
        )

        # --------------------------------------------------------------
        # Live preview
        # --------------------------------------------------------------

        def update_preview():
            try:
                v1 = float(
                    v1_entry.text()
                )

                t1 = float(
                    t1_entry.text()
                )

                v2 = float(
                    v2_entry.text()
                )

                t2 = float(
                    t2_entry.text()
                )

            except ValueError:
                return

            delay = 0.0

            try:
                delay = float(
                    self.delay1_entry.text()
                )

            except ValueError:
                pass

            preview.set_values(
                v1,
                t1,
                v2,
                t2,
                delay,
            )

        v1_entry.textChanged.connect(
            update_preview
        )

        t1_entry.textChanged.connect(
            update_preview
        )

        v2_entry.textChanged.connect(
            update_preview
        )

        t2_entry.textChanged.connect(
            update_preview
        )

        self.delay1_entry.textChanged.connect(
            update_preview
        )

        update_preview()

        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------

        buttons = QHBoxLayout()

        ok_button = QPushButton(
            "OK"
        )

        cancel_button = QPushButton(
            "Cancel"
        )

        buttons.addStretch()

        buttons.addWidget(
            ok_button
        )

        buttons.addWidget(
            cancel_button
        )

        layout.addLayout(
            buttons
        )

        def accept():
            try:
                v1 = float(
                    v1_entry.text()
                )

                t1 = float(
                    t1_entry.text()
                )

                v2 = float(
                    v2_entry.text()
                )

                t2 = float(
                    t2_entry.text()
                )

                if v1 < 0 or v2 < 0:
                    raise ValueError(
                        "Voltages must be >= 0."
                    )

                if t1 <= 0:
                    raise ValueError(
                        "T1 must be greater than 0."
                    )

                if t2 <= 0:
                    raise ValueError(
                        "T2 must be greater than 0."
                    )

            except ValueError as exc:
                QMessageBox.critical(
                    dialog,
                    "Invalid Input",
                    str(exc),
                )

                return

            self.shaping_v1 = v1
            self.shaping_t1 = t1
            self.shaping_v2 = v2
            self.shaping_t2 = t2

            self.save_settings()

            dialog.accept()

        ok_button.clicked.connect(
            accept
        )

        cancel_button.clicked.connect(
            dialog.reject
        )

        dialog.resize(
            850,
            350,
        )

        dialog.exec()

    # ------------------------------------------------------------------

    def set_device(self):
        """
        Original USMELT Set Device behavior.
        """

        serial_port, ok = QInputDialog.getText(
            self,
            "Set Device",
            "Enter device name:",
            text=self.device_name,
        )

        if not ok:
            return

        new_device = serial_port.strip()

        if not new_device:
            return

        self.device_name = new_device

        try:
            self.pg = usmelt.TG5012A(
                serial_port=self.device_name
            )

            self.init_pg()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Device Error",
                f"Could not connect to device: {exc}",
            )

            self.pg = None


# ----------------------------------------------------------------------
# Main Image Marker application
# ----------------------------------------------------------------------

class ImageMarkerApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "USMELT + Image Marker"
        )

        self.resize(
            1500,
            900,
        )

        self.markers = []

        self.undo_stack = []
        self.redo_stack = []

        self.marker_size = 15

        self.color_min = 1.0
        self.color_max = 2.0

        self.current_voltage = None
        self.current_is_test = False

        self.build_menu()
        self.build_ui()

    # ------------------------------------------------------------------

    def build_menu(self):
        settings_menu = (
            self.menuBar().addMenu(
                "Settings"
            )
        )

        set_device_action = QAction(
            "Set Device",
            self,
        )

        set_device_action.triggered.connect(
            self.set_device
        )

        settings_menu.addAction(
            set_device_action
        )

        self.melt_sound_action = QAction(
            "Melt sound",
            self,
        )

        self.melt_sound_action.setCheckable(
            True
        )

        settings_menu.addAction(
            self.melt_sound_action
        )

        settings_menu.addSeparator()

        exit_action = QAction(
            "Exit",
            self,
        )

        exit_action.triggered.connect(
            self.close
        )

        settings_menu.addAction(
            exit_action
        )

    # ------------------------------------------------------------------

    def build_ui(self):
        central = QWidget()

        self.setCentralWidget(
            central
        )

        main_layout = QHBoxLayout(
            central
        )

        main_layout.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        # ==============================================================
        # LEFT TASK BAR
        # ==============================================================

        scroll = QScrollArea()

        scroll.setWidgetResizable(
            True
        )

        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        scroll.setFixedWidth(
            400
        )

        left_widget = QWidget()

        left_layout = QVBoxLayout(
            left_widget
        )

        left_layout.setAlignment(
            Qt.AlignTop
        )

        scroll.setWidget(
            left_widget
        )

        # --------------------------------------------------------------
        # USMELT
        # --------------------------------------------------------------

        self.melter = MelterPanel()

        left_layout.addWidget(
            self.melter
        )

        self.melt_sound_action.setChecked(
            self.melter.melt_sound
        )

        self.melt_sound_action.toggled.connect(
            self.on_melt_sound_toggled
        )

        # --------------------------------------------------------------
        # MARKER CONTROLS
        # --------------------------------------------------------------

        marker_group = QGroupBox(
            "Image Marking"
        )

        marker_layout = QVBoxLayout(
            marker_group
        )

        open_button = QPushButton(
            "Open Image"
        )

        open_button.clicked.connect(
            self.open_image
        )

        marker_layout.addWidget(
            open_button
        )

        # Marker size.
        size_row = QHBoxLayout()

        size_row.addWidget(
            QLabel("Marker Size")
        )

        self.marker_size_slider = QSlider(
            Qt.Horizontal
        )

        self.marker_size_slider.setMinimum(
            2
        )

        self.marker_size_slider.setMaximum(
            100
        )

        self.marker_size_slider.setValue(
            15
        )

        self.marker_size_slider.valueChanged.connect(
            self.marker_size_changed
        )

        self.marker_size_label = QLabel(
            "15 px"
        )

        self.marker_size_label.setFixedWidth(
            45
        )

        size_row.addWidget(
            self.marker_size_slider
        )

        size_row.addWidget(
            self.marker_size_label
        )

        marker_layout.addLayout(
            size_row
        )

        # --------------------------------------------------------------
        # Voltage / Test status
        # --------------------------------------------------------------

        voltage_row = QHBoxLayout()

        self.voltage_status_label = QLabel(
            "Voltage: —"
        )

        self.test_checkbox = QCheckBox(
            "Test"
        )

        self.test_checkbox.setEnabled(
            False
        )

        self.test_checkbox.setToolTip(
            "Automatically active when Channel 1 "
            "Voltage High is exactly 5.0 V."
        )

        voltage_row.addWidget(
            self.voltage_status_label
        )

        voltage_row.addStretch()

        voltage_row.addWidget(
            self.test_checkbox
        )

        marker_layout.addLayout(
            voltage_row
        )

        # --------------------------------------------------------------
        # Color scale
        # --------------------------------------------------------------

        color_group = QGroupBox(
            "Voltage Color Scale"
        )

        color_layout = QGridLayout(
            color_group
        )

        self.color_min_spin = QDoubleSpinBox()

        self.color_min_spin.setRange(
            0.0,
            100.0,
        )

        self.color_min_spin.setDecimals(
            2
        )

        self.color_min_spin.setSingleStep(
            0.05
        )

        self.color_min_spin.setValue(
            self.color_min
        )

        self.color_max_spin = QDoubleSpinBox()

        self.color_max_spin.setRange(
            0.0,
            100.0,
        )

        self.color_max_spin.setDecimals(
            2
        )

        self.color_max_spin.setSingleStep(
            0.05
        )

        self.color_max_spin.setValue(
            self.color_max
        )

        self.color_min_spin.valueChanged.connect(
            self.color_range_changed
        )

        self.color_max_spin.valueChanged.connect(
            self.color_range_changed
        )

        color_layout.addWidget(
            QLabel("Min"),
            0,
            0,
        )

        color_layout.addWidget(
            self.color_min_spin,
            0,
            1,
        )

        color_layout.addWidget(
            QLabel("Max"),
            1,
            0,
        )

        color_layout.addWidget(
            self.color_max_spin,
            1,
            1,
        )

        marker_layout.addWidget(
            color_group
        )

        # --------------------------------------------------------------
        # Rotation
        # --------------------------------------------------------------

        rotation_group = QGroupBox(
            "Rotation"
        )

        rotation_layout = QGridLayout(
            rotation_group
        )

        self.rotation_spin = QDoubleSpinBox()

        self.rotation_spin.setRange(
            -360.0,
            360.0,
        )

        self.rotation_spin.setDecimals(
            2
        )

        self.rotation_spin.setSingleStep(
            1.0
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.rotation_spin.valueChanged.connect(
            self.rotation_changed
        )

        rotation_layout.addWidget(
            QLabel("Angle"),
            0,
            0,
        )

        rotation_layout.addWidget(
            self.rotation_spin,
            0,
            1,
        )

        reset_rotation_button = QPushButton(
            "Reset Rotation"
        )

        reset_rotation_button.clicked.connect(
            self.reset_rotation
        )

        rotation_layout.addWidget(
            reset_rotation_button,
            1,
            0,
            1,
            2,
        )

        marker_layout.addWidget(
            rotation_group
        )

        # --------------------------------------------------------------
        # Undo / Redo / Clear
        # --------------------------------------------------------------

        history_row = QHBoxLayout()

        undo_button = QPushButton(
            "Undo"
        )

        undo_button.clicked.connect(
            self.undo
        )

        redo_button = QPushButton(
            "Redo"
        )

        redo_button.clicked.connect(
            self.redo
        )

        clear_button = QPushButton(
            "Clear"
        )

        clear_button.clicked.connect(
            self.clear_markers
        )

        history_row.addWidget(
            undo_button
        )

        history_row.addWidget(
            redo_button
        )

        history_row.addWidget(
            clear_button
        )

        marker_layout.addLayout(
            history_row
        )

        # --------------------------------------------------------------
        # Export
        # --------------------------------------------------------------

        export_button = QPushButton(
            "Export Annotated Image"
        )

        export_button.clicked.connect(
            self.export_image
        )

        marker_layout.addWidget(
            export_button
        )

        left_layout.addWidget(
            marker_group
        )

        # ==============================================================
        # IMAGE CANVAS
        # ==============================================================

        self.canvas = ImageCanvas(
            self
        )

        self.canvas.marker_added.connect(
            self.add_marker
        )

        main_layout.addWidget(
            scroll
        )

        main_layout.addWidget(
            self.canvas,
            1,
        )

        self.melter.voltage_high1_changed.connect(
            self.update_marker_voltage_state
        )

        self.update_marker_voltage_state()

    # ------------------------------------------------------------------

    def set_device(self):
        self.melter.set_device()

    # ------------------------------------------------------------------

    def on_melt_sound_toggled(self, checked):
        self.melter.melt_sound = checked
        self.melter.save_settings()

    # ------------------------------------------------------------------

    def get_current_voltage(self):
        return self.melter.get_voltage_high1()

    # ------------------------------------------------------------------

    def update_marker_voltage_state(self):
        voltage = self.get_current_voltage()

        self.current_voltage = voltage

        if voltage is None:
            self.current_is_test = False

            self.voltage_status_label.setText(
                "Voltage: —"
            )

            self.test_checkbox.setChecked(
                False
            )

            return

        self.current_is_test = math.isclose(
            voltage,
            5.0,
            abs_tol=1e-9,
        )

        self.voltage_status_label.setText(
            f"Voltage: {voltage:.2f} V"
        )

        self.test_checkbox.setChecked(
            self.current_is_test
        )

    # ------------------------------------------------------------------

    def save_undo_state(self):
        self.undo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.redo_stack.clear()

        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    # ------------------------------------------------------------------

    def add_marker(self, x, y):
        voltage = self.get_current_voltage()

        if voltage is None:
            self.voltage_status_label.setText(
                "Voltage: invalid CH1 value"
            )

            return

        self.save_undo_state()

        marker = Marker(
            x=x,
            y=y,
            size=self.marker_size,
            voltage=voltage,
            is_test=math.isclose(
                voltage,
                5.0,
                abs_tol=1e-9,
            ),
        )

        self.markers.append(
            marker
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def undo(self):
        if not self.undo_stack:
            return

        self.redo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.markers = (
            self.undo_stack.pop()
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def redo(self):
        if not self.redo_stack:
            return

        self.undo_stack.append(
            copy.deepcopy(
                self.markers
            )
        )

        self.markers = (
            self.redo_stack.pop()
        )

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def clear_markers(self):
        if not self.markers:
            return

        self.save_undo_state()

        self.markers = []

        self.canvas.set_markers(
            self.markers
        )

    # ------------------------------------------------------------------

    def marker_size_changed(self, value):
        self.marker_size = int(
            value
        )

        self.marker_size_label.setText(
            f"{value} px"
        )

    # ------------------------------------------------------------------

    def color_range_changed(self):
        self.color_min = (
            self.color_min_spin.value()
        )

        self.color_max = (
            self.color_max_spin.value()
        )

        if self.color_max <= self.color_min:
            return

        self.canvas.render_image()

    # ------------------------------------------------------------------

    def rotation_changed(self, value):
        self.canvas.set_rotation(
            value
        )

    # ------------------------------------------------------------------

    def reset_rotation(self):
        self.rotation_spin.blockSignals(
            True
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.rotation_spin.blockSignals(
            False
        )

        self.canvas.set_rotation(
            0.0
        )

    # ------------------------------------------------------------------

    def open_image(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Images (*.jpg *.jpeg *.png)",
        )

        if not file_name:
            return

        try:
            image = Image.open(
                file_name
            ).convert("RGB")

            # Crop equally to square.
            width, height = image.size

            side = min(
                width,
                height,
            )

            left = (
                width - side
            ) // 2

            top = (
                height - side
            ) // 2

            image = image.crop(
                (
                    left,
                    top,
                    left + side,
                    top + side,
                )
            )

            # Ask for color scale.
            min_value, ok = QInputDialog.getDouble(
                self,
                "Color Scale",
                "Minimum voltage:",
                self.color_min,
                0.0,
                100.0,
                2,
            )

            if not ok:
                return

            max_value, ok = QInputDialog.getDouble(
                self,
                "Color Scale",
                "Maximum voltage:",
                self.color_max,
                0.0,
                100.0,
                2,
            )

            if not ok:
                return

            if max_value <= min_value:
                QMessageBox.warning(
                    self,
                    "Color Scale",
                    "Maximum voltage must be greater than minimum voltage.",
                )

                return

            self.color_min = min_value
            self.color_max = max_value

            self.color_min_spin.setValue(
                min_value
            )

            self.color_max_spin.setValue(
                max_value
            )

            self.markers = []
            self.undo_stack = []
            self.redo_stack = []

            self.rotation_spin.blockSignals(
                True
            )

            self.rotation_spin.setValue(
                0.0
            )

            self.rotation_spin.blockSignals(
                False
            )

            self.canvas.set_image(
                image
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open Image",
                f"Could not open image:\n\n{exc}",
            )

    # ------------------------------------------------------------------

    def export_image(self):
        if self.canvas.base_image is None:
            QMessageBox.warning(
                self,
                "Export",
                "No image is open.",
            )

            return

        file_name, selected_filter = (
            QFileDialog.getSaveFileName(
                self,
                "Export Annotated Image",
                "",
                "PNG (*.png);;JPEG (*.jpg *.jpeg)",
            )
        )

        if not file_name:
            return

        try:
            image = (
                self.canvas.base_image.copy()
            )

            draw = ImageDraw.Draw(
                image
            )

            # Draw markers.
            for marker in self.markers:
                if marker.is_test:
                    fill = (
                        255,
                        0,
                        0,
                    )

                else:
                    fill = (
                        self.canvas.voltage_to_color(
                            marker.voltage
                        )
                    )

                r = (
                    marker.size
                    / 2.0
                )

                draw.ellipse(
                    [
                        marker.x - r,
                        marker.y - r,
                        marker.x + r,
                        marker.y + r,
                    ],
                    fill=fill,
                    outline=(
                        0,
                        0,
                        0,
                    ),
                    width=max(
                        1,
                        int(
                            marker.size
                            / 8
                        ),
                    ),
                )

            # Rotate.
            if abs(
                self.canvas.rotation
            ) > 1e-9:

                image = image.rotate(
                    self.canvas.rotation,
                    expand=True,
                    fillcolor=(
                        30,
                        30,
                        30,
                    ),
                )

            # ----------------------------------------------------------
            # Legend
            # ----------------------------------------------------------

            legend_width = 150
            legend_height = 170

            margin = 15

            legend_x = (
                image.width
                - legend_width
                - margin
            )

            legend_y = margin

            overlay = Image.new(
                "RGBA",
                (
                    legend_width,
                    legend_height,
                ),
                (
                    255,
                    255,
                    255,
                    235,
                ),
            )

            overlay_draw = ImageDraw.Draw(
                overlay
            )

            overlay_draw.rectangle(
                [
                    0,
                    0,
                    legend_width - 1,
                    legend_height - 1,
                ],
                outline=(
                    0,
                    0,
                    0,
                    255,
                ),
                width=2,
            )

            font = ImageFont.load_default()

            title = "Voltage"

            title_bbox = (
                overlay_draw.textbbox(
                    (0, 0),
                    title,
                    font=font,
                )
            )

            title_width = (
                title_bbox[2]
                - title_bbox[0]
            )

            overlay_draw.text(
                (
                    (
                        legend_width
                        - title_width
                    )
                    / 2,
                    10,
                ),
                title,
                fill=(
                    0,
                    0,
                    0,
                    255,
                ),
                font=font,
            )

            bar_left = 30
            bar_top = 42
            bar_width = 28
            bar_height = 95

            for i in range(
                bar_height
            ):
                t = (
                    i
                    / max(
                        1,
                        bar_height - 1,
                    )
                )

                voltage = (
                    self.color_max
                    - t
                    * (
                        self.color_max
                        - self.color_min
                    )
                )

                color = (
                    self.canvas.voltage_to_color(
                        voltage
                    )
                )

                overlay_draw.line(
                    [
                        bar_left,
                        bar_top + i,
                        bar_left
                        + bar_width,
                        bar_top + i,
                    ],
                    fill=(
                        *color,
                        255,
                    ),
                    width=1,
                )

            overlay_draw.rectangle(
                [
                    bar_left,
                    bar_top,
                    bar_left + bar_width,
                    bar_top + bar_height,
                ],
                outline=(
                    0,
                    0,
                    0,
                    255,
                ),
                width=1,
            )

            overlay_draw.text(
                (
                    bar_left
                    + bar_width
                    + 10,
                    bar_top - 4,
                ),
                f"{self.color_max:.2f}",
                fill=(
                    0,
                    0,
                    0,
                    255,
                ),
                font=font,
            )

            mid = (
                self.color_min
                + self.color_max
            ) / 2

            overlay_draw.text(
                (
                    bar_left
                    + bar_width
                    + 10,
                    bar_top
                    + bar_height / 2
                    - 4,
                ),
                f"{mid:.2f}",
                fill=(
                    0,
                    0,
                    0,
                    255,
                ),
                font=font,
            )

            overlay_draw.text(
                (
                    bar_left
                    + bar_width
                    + 10,
                    bar_top
                    + bar_height
                    - 7,
                ),
                f"{self.color_min:.2f}",
                fill=(
                    0,
                    0,
                    0,
                    255,
                ),
                font=font,
            )

            # Test marker key.
            test_y = 148

            overlay_draw.ellipse(
                [
                    15,
                    test_y,
                    25,
                    test_y + 10,
                ],
                fill=(
                    255,
                    0,
                    0,
                    255,
                ),
                outline=(
                    0,
                    0,
                    0,
                    255,
                ),
            )

            overlay_draw.text(
                (
                    32,
                    test_y - 1,
                ),
                "Test = 5.00 V",
                fill=(
                    0,
                    0,
                    0,
                    255,
                ),
                font=font,
            )

            image_rgba = (
                image.convert(
                    "RGBA"
                )
            )

            image_rgba.alpha_composite(
                overlay,
                (
                    legend_x,
                    legend_y,
                ),
            )

            image = (
                image_rgba.convert(
                    "RGB"
                )
            )

            image.save(
                file_name
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export",
                f"Could not export image:\n\n{exc}",
            )


# ----------------------------------------------------------------------
# Application entry point
# ----------------------------------------------------------------------

def main():
    app = QApplication(
        sys.argv
    )

    window = ImageMarkerApp()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()