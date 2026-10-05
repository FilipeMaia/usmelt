import sys
import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass
class Marker:
    x: float
    y: float
    size: float
    voltage: float
    is_test: bool


class ImageCanvas(QWidget):
    marker_added = Signal(float, float)

    def __init__(self):
        super().__init__()

        self.setMinimumSize(500, 500)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.base_image = None
        self.display_image = None
        self.display_pixmap = None

        self.rotation = 0.0
        self.zoom = 1.0

        self.pan_x = 0.0
        self.pan_y = 0.0
        self.last_pan_position = None

        self.display_rect = QRectF()

        self.setMouseTracking(True)

    def set_image(self, image):
        self.base_image = image.copy()
        self.rotation = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.last_pan_position = None
        self.update_display()

    def update_display(self):
        if self.base_image is None:
            self.display_image = None
            self.display_pixmap = None
            self.update()
            return

        self.display_image = self.base_image.rotate(
            self.rotation,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor=(32, 32, 32),
        )

        self.set_display_image(self.display_image)

    def set_display_image(self, image):
        self.display_image = image
        self.display_pixmap = self.create_pixmap(image)
        self.update_geometry()
        self.update()

    @staticmethod
    def create_pixmap(image):
        rgb_image = image.convert("RGB")
        data = rgb_image.tobytes("raw", "RGB")

        qimage = QImage(
            data,
            rgb_image.width,
            rgb_image.height,
            rgb_image.width * 3,
            QImage.Format_RGB888,
        ).copy()

        return QPixmap.fromImage(qimage)

    def update_geometry(self):
        if self.display_pixmap is None:
            self.display_rect = QRectF()
            return

        image_width = self.display_pixmap.width() * self.zoom
        image_height = self.display_pixmap.height() * self.zoom

        x = (self.width() - image_width) / 2.0 + self.pan_x
        y = (self.height() - image_height) / 2.0 + self.pan_y

        self.display_rect = QRectF(
            x,
            y,
            image_width,
            image_height,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.darkGray)

        if self.display_pixmap is not None:
            source_rect = QRectF(
                0,
                0,
                self.display_pixmap.width(),
                self.display_pixmap.height(),
            )

            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

            painter.drawPixmap(
                self.display_rect,
                self.display_pixmap,
                source_rect,
            )

        painter.end()

    def widget_to_rotated_image(self, position):
        if self.display_pixmap is None or self.display_rect.isEmpty():
            return None

        if not self.display_rect.contains(position):
            return None

        x = (
            (position.x() - self.display_rect.left())
            / self.display_rect.width()
            * self.display_pixmap.width()
        )

        y = (
            (position.y() - self.display_rect.top())
            / self.display_rect.height()
            * self.display_pixmap.height()
        )

        return x, y

    def rotated_to_base_image(self, x, y):
        if self.base_image is None or self.display_image is None:
            return None

        # PIL Image.width and Image.height are properties,
        # not functions.
        cx_rotated = self.display_image.width / 2.0
        cy_rotated = self.display_image.height / 2.0

        cx_base = self.base_image.width / 2.0
        cy_base = self.base_image.height / 2.0

        dx = x - cx_rotated
        dy = y - cy_rotated

        theta = math.radians(self.rotation)

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        # Inverse rotation.
        base_dx = dx * cos_t - dy * sin_t
        base_dy = dx * sin_t + dy * cos_t

        return (
            base_dx + cx_base,
            base_dy + cy_base,
        )

    def mousePressEvent(self, event):
        if self.base_image is None:
            return

        if event.button() == Qt.MiddleButton:
            self.last_pan_position = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            rotated_point = self.widget_to_rotated_image(
                event.position()
            )

            if rotated_point is None:
                return

            base_point = self.rotated_to_base_image(
                *rotated_point
            )

            if base_point is None:
                return

            x, y = base_point

            if (
                0 <= x < self.base_image.width
                and 0 <= y < self.base_image.height
            ):
                self.marker_added.emit(x, y)

            event.accept()

    def mouseMoveEvent(self, event):
        if self.last_pan_position is not None:
            current_position = event.position()

            delta = (
                current_position
                - self.last_pan_position
            )

            self.pan_x += delta.x()
            self.pan_y += delta.y()

            self.last_pan_position = current_position

            self.update_geometry()
            self.update()

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.last_pan_position = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.base_image is None or self.display_pixmap is None:
            return

        old_zoom = self.zoom

        if event.angleDelta().y() > 0:
            self.zoom *= 1.15
        else:
            self.zoom /= 1.15

        self.zoom = max(
            0.25,
            min(10.0, self.zoom),
        )

        if abs(self.zoom - old_zoom) < 1e-9:
            return

        cursor_position = event.position()

        image_point = self.widget_to_rotated_image(
            cursor_position
        )

        if image_point is not None:
            image_x, image_y = image_point

            old_left = self.display_rect.left()
            old_top = self.display_rect.top()

            image_widget_x = (
                old_left
                + image_x
                / self.display_pixmap.width()
                * self.display_rect.width()
            )

            image_widget_y = (
                old_top
                + image_y
                / self.display_pixmap.height()
                * self.display_rect.height()
            )

            self.update_geometry()

            self.pan_x += (
                cursor_position.x()
                - image_widget_x
            )

            self.pan_y += (
                cursor_position.y()
                - image_widget_y
            )

            self.update_geometry()

        else:
            self.update_geometry()

        self.update()
        event.accept()

    def resizeEvent(self, event):
        self.update_geometry()
        super().resizeEvent(event)


class ImageMarkerApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Image Marker")
        self.resize(1200, 800)

        self.markers = []
        self.undo_stack = []
        self.redo_stack = []

        self.test_enabled = False

        self.color_min = 1.00
        self.color_max = 2.00

        self.canvas = ImageCanvas()
        self.canvas.marker_added.connect(
            self.add_marker
        )

        self.create_toolbar()

        central_widget = QWidget()

        central_layout = QHBoxLayout(
            central_widget
        )

        central_layout.setContentsMargins(
            0, 0, 0, 0
        )

        central_layout.setSpacing(0)

        central_layout.addWidget(self.toolbar)
        central_layout.addWidget(
            self.canvas,
            1
        )

        self.setCentralWidget(central_widget)

        self.statusBar().showMessage(
            "Open an image. Left-click to place a marker; "
            "middle-drag to pan; mouse wheel to zoom."
        )

    def create_toolbar(self):
        self.toolbar = QWidget()
        self.toolbar.setFixedWidth(260)

        layout = QVBoxLayout(self.toolbar)

        layout.setContentsMargins(
            10, 10, 10, 10
        )

        layout.setSpacing(8)

        open_button = QPushButton(
            "Open image"
        )

        open_button.clicked.connect(
            self.open_image
        )

        layout.addWidget(open_button)

        marker_group = QGroupBox("Marker")

        marker_layout = QFormLayout(
            marker_group
        )

        self.marker_size_slider = QSlider(
            Qt.Horizontal
        )

        self.marker_size_slider.setRange(
            2,
            100
        )

        self.marker_size_slider.setValue(
            15
        )

        self.marker_size_label = QLabel(
            "15 px"
        )

        marker_size_row = QHBoxLayout()

        marker_size_row.addWidget(
            self.marker_size_slider
        )

        marker_size_row.addWidget(
            self.marker_size_label
        )

        marker_layout.addRow(
            "Size:",
            marker_size_row
        )

        self.marker_size_slider.valueChanged.connect(
            lambda value:
                self.marker_size_label.setText(
                    f"{value} px"
                )
        )

        self.test_checkbox = QCheckBox(
            "Test"
        )

        self.test_checkbox.stateChanged.connect(
            self.test_changed
        )

        marker_layout.addRow(
            "",
            self.test_checkbox
        )

        self.voltage_slider = QSlider(
            Qt.Horizontal
        )

        self.voltage_slider.setRange(
            20,
            40
        )

        self.voltage_slider.setSingleStep(
            1
        )

        self.voltage_slider.setValue(
            20
        )

        self.voltage_label = QLabel(
            "1.00 V"
        )

        voltage_row = QHBoxLayout()

        voltage_row.addWidget(
            self.voltage_slider
        )

        voltage_row.addWidget(
            self.voltage_label
        )

        marker_layout.addRow(
            "Voltage:",
            voltage_row
        )

        self.voltage_slider.valueChanged.connect(
            self.voltage_changed
        )

        layout.addWidget(marker_group)

        color_group = QGroupBox(
            "Color scale"
        )

        color_layout = QFormLayout(
            color_group
        )

        self.color_min_spin = QDoubleSpinBox()

        self.color_min_spin.setRange(
            1.00,
            2.00
        )

        self.color_min_spin.setSingleStep(
            0.05
        )

        self.color_min_spin.setDecimals(
            2
        )

        self.color_min_spin.setValue(
            self.color_min
        )

        self.color_max_spin = QDoubleSpinBox()

        self.color_max_spin.setRange(
            1.00,
            2.00
        )

        self.color_max_spin.setSingleStep(
            0.05
        )

        self.color_max_spin.setDecimals(
            2
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

        color_layout.addRow(
            "Minimum:",
            self.color_min_spin
        )

        color_layout.addRow(
            "Maximum:",
            self.color_max_spin
        )

        layout.addWidget(color_group)

        rotation_group = QGroupBox(
            "Rotation"
        )

        rotation_layout = QFormLayout(
            rotation_group
        )

        self.rotation_spin = QDoubleSpinBox()

        self.rotation_spin.setRange(
            -180.0,
            180.0
        )

        self.rotation_spin.setSingleStep(
            0.1
        )

        self.rotation_spin.setDecimals(
            1
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.rotation_spin.valueChanged.connect(
            self.rotation_changed
        )

        rotation_layout.addRow(
            "Angle:",
            self.rotation_spin
        )

        rotation_buttons = QHBoxLayout()

        minus_button = QPushButton(
            "-1°"
        )

        minus_button.clicked.connect(
            lambda:
                self.rotation_spin.setValue(
                    self.rotation_spin.value()
                    - 1.0
                )
        )

        plus_button = QPushButton(
            "+1°"
        )

        plus_button.clicked.connect(
            lambda:
                self.rotation_spin.setValue(
                    self.rotation_spin.value()
                    + 1.0
                )
        )

        reset_rotation_button = QPushButton(
            "Reset"
        )

        reset_rotation_button.clicked.connect(
            lambda:
                self.rotation_spin.setValue(
                    0.0
                )
        )

        rotation_buttons.addWidget(
            minus_button
        )

        rotation_buttons.addWidget(
            plus_button
        )

        rotation_buttons.addWidget(
            reset_rotation_button
        )

        rotation_layout.addRow(
            rotation_buttons
        )

        layout.addWidget(
            rotation_group
        )

        history_group = QGroupBox(
            "Markers"
        )

        history_layout = QVBoxLayout(
            history_group
        )

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
            "Clear markers"
        )

        clear_button.clicked.connect(
            self.clear_markers
        )

        history_layout.addWidget(
            undo_button
        )

        history_layout.addWidget(
            redo_button
        )

        history_layout.addWidget(
            clear_button
        )

        layout.addWidget(
            history_group
        )

        export_button = QPushButton(
            "Export image"
        )

        export_button.clicked.connect(
            self.export_image
        )

        layout.addWidget(
            export_button
        )

        layout.addStretch()

    def voltage_changed(self, slider_value):
        voltage = slider_value / 20.0

        self.voltage_label.setText(
            f"{voltage:.2f} V"
        )

        # Changing voltage turns Test mode off,
        # but the checkbox remains enabled.
        if self.test_checkbox.isChecked():
            self.test_checkbox.setChecked(
                False
            )

        self.test_enabled = False

    def test_changed(self, state):
        self.test_enabled = (
            state == Qt.CheckState.Checked
        )

        self.update_display_with_markers()

    def get_current_voltage(self):
        return (
            self.voltage_slider.value()
            / 20.0
        )

    def rotation_changed(self, value):
        if self.canvas.base_image is None:
            return

        self.canvas.rotation = float(value)

        self.update_display_with_markers()

    def color_range_changed(self):
        minimum = self.color_min_spin.value()
        maximum = self.color_max_spin.value()

        if maximum <= minimum:
            return

        self.color_min = minimum
        self.color_max = maximum

        self.update_display_with_markers()

    def crop_to_square(self, image):
        width, height = image.size

        if width == height:
            return image

        if width > height:
            left = (width - height) // 2
            right = left + height

            return image.crop(
                (
                    left,
                    0,
                    right,
                    height,
                )
            )

        top = (height - width) // 2
        bottom = top + width

        return image.crop(
            (
                0,
                top,
                width,
                bottom,
            )
        )

    def ask_color_range(
        self,
        default_min=1.00,
        default_max=2.00,
    ):
        minimum, ok = QInputDialog.getDouble(
            self,
            "Color scale",
            "Minimum voltage (V):",
            default_min,
            1.00,
            2.00,
            2,
            step=0.05,
        )

        if not ok:
            return None

        maximum, ok = QInputDialog.getDouble(
            self,
            "Color scale",
            "Maximum voltage (V):",
            default_max,
            1.00,
            2.00,
            2,
            step=0.05,
        )

        if not ok:
            return None

        if maximum <= minimum:
            QMessageBox.warning(
                self,
                "Invalid color scale",
                "The maximum voltage must be greater "
                "than the minimum voltage.",
            )

            return self.ask_color_range(
                minimum,
                default_max,
            )

        return minimum, maximum

    def open_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open image",
            "",
            "Images (*.jpg *.jpeg *.png)",
        )

        if not filename:
            return

        try:
            image = Image.open(
                filename
            ).convert("RGB")

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open image failed",
                f"Could not open the image:\n{exc}",
            )

            return

        color_range = self.ask_color_range(
            self.color_min,
            self.color_max,
        )

        if color_range is None:
            return

        self.color_min, self.color_max = (
            color_range
        )

        self.color_min_spin.setValue(
            self.color_min
        )

        self.color_max_spin.setValue(
            self.color_max
        )

        image = self.crop_to_square(
            image
        )

        self.markers.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

        self.test_checkbox.setChecked(
            False
        )

        self.rotation_spin.setValue(
            0.0
        )

        self.canvas.set_image(
            image
        )

        self.update_display_with_markers()

        self.statusBar().showMessage(
            f"Loaded {filename} — "
            f"{image.width} × {image.height} px"
        )

    def save_undo_state(self):
        state = [
            Marker(
                marker.x,
                marker.y,
                marker.size,
                marker.voltage,
                marker.is_test,
            )
            for marker in self.markers
        ]

        self.undo_stack.append(
            state
        )

        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

        self.redo_stack.clear()

    def add_marker(self, x, y):
        if self.canvas.base_image is None:
            return

        self.save_undo_state()

        # Read the checkbox directly so the marker always
        # uses the current visible Test state.
        is_test = (
            self.test_checkbox.isChecked()
        )

        marker = Marker(
            x=x,
            y=y,
            size=float(
                self.marker_size_slider.value()
            ),
            voltage=self.get_current_voltage(),
            is_test=is_test,
        )

        self.markers.append(
            marker
        )

        self.update_display_with_markers()

        mode = (
            "Test"
            if is_test
            else f"{marker.voltage:.2f} V"
        )

        self.statusBar().showMessage(
            f"Marker {len(self.markers)} added — "
            f"{mode}"
        )

    def undo(self):
        if not self.undo_stack:
            return

        current_state = [
            Marker(
                marker.x,
                marker.y,
                marker.size,
                marker.voltage,
                marker.is_test,
            )
            for marker in self.markers
        ]

        self.redo_stack.append(
            current_state
        )

        self.markers = (
            self.undo_stack.pop()
        )

        self.update_display_with_markers()

    def redo(self):
        if not self.redo_stack:
            return

        current_state = [
            Marker(
                marker.x,
                marker.y,
                marker.size,
                marker.voltage,
                marker.is_test,
            )
            for marker in self.markers
        ]

        self.undo_stack.append(
            current_state
        )

        self.markers = (
            self.redo_stack.pop()
        )

        self.update_display_with_markers()

    def clear_markers(self):
        if not self.markers:
            return

        self.save_undo_state()

        self.markers.clear()

        self.update_display_with_markers()

    def voltage_to_color(self, voltage):
        if self.color_max <= self.color_min:
            return 0, 0, 255

        normalized = (
            (voltage - self.color_min)
            / (self.color_max - self.color_min)
        )

        normalized = max(
            0.0,
            min(1.0, normalized),
        )

        blue = (0, 0, 255)
        green = (0, 255, 0)
        yellow = (255, 255, 0)
        orange = (255, 165, 0)

        if normalized <= 1.0 / 3.0:
            t = normalized * 3.0

            return tuple(
                int(
                    blue[i]
                    + (
                        green[i]
                        - blue[i]
                    )
                    * t
                )
                for i in range(3)
            )

        if normalized <= 2.0 / 3.0:
            t = (
                normalized
                - 1.0 / 3.0
            ) * 3.0

            return tuple(
                int(
                    green[i]
                    + (
                        yellow[i]
                        - green[i]
                    )
                    * t
                )
                for i in range(3)
            )

        t = (
            normalized
            - 2.0 / 3.0
        ) * 3.0

        return tuple(
            int(
                yellow[i]
                + (
                    orange[i]
                    - yellow[i]
                )
                * t
            )
            for i in range(3)
        )

    def render_markers(self, image):
        result = image.copy()
        draw = ImageDraw.Draw(result)

        for marker in self.markers:
            if marker.is_test:
                color = (255, 0, 0)
            else:
                color = self.voltage_to_color(
                    marker.voltage
                )

            radius = marker.size / 2.0

            x0 = marker.x - radius
            y0 = marker.y - radius
            x1 = marker.x + radius
            y1 = marker.y + radius

            draw.ellipse(
                (
                    x0,
                    y0,
                    x1,
                    y1,
                ),
                fill=color,
                outline=(255, 255, 255),
                width=max(
                    1,
                    int(marker.size * 0.12),
                ),
            )

        return result

    def update_display_with_markers(self):
        if self.canvas.base_image is None:
            return

        annotated = self.render_markers(
            self.canvas.base_image
        )

        rotated = annotated.rotate(
            self.canvas.rotation,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor=(32, 32, 32),
        )

        self.canvas.set_display_image(
            rotated
        )

    def create_color_scale_legend(
        self,
        width=150,
        height=170,
    ):
        legend = Image.new(
            "RGBA",
            (
                width,
                height,
            ),
            (255, 255, 255, 235),
        )

        draw = ImageDraw.Draw(
            legend
        )

        draw.rectangle(
            (
                0,
                0,
                width - 1,
                height - 1,
            ),
            outline=(40, 40, 40, 255),
            width=2,
        )

        draw.text(
            (10, 8),
            "Voltage (V)",
            fill=(20, 20, 20, 255),
        )

        bar_left = 25
        bar_right = 65
        bar_top = 45
        bar_bottom = height - 30

        bar_height = (
            bar_bottom - bar_top
        )

        for y in range(
            bar_top,
            bar_bottom + 1,
        ):
            normalized = 1.0 - (
                (y - bar_top)
                / max(1, bar_height)
            )

            voltage = (
                self.color_min
                + normalized
                * (
                    self.color_max
                    - self.color_min
                )
            )

            color = self.voltage_to_color(
                voltage
            )

            draw.line(
                (
                    bar_left,
                    y,
                    bar_right,
                    y,
                ),
                fill=(
                    *color,
                    255,
                ),
                width=1,
            )

        draw.rectangle(
            (
                bar_left,
                bar_top,
                bar_right,
                bar_bottom,
            ),
            outline=(40, 40, 40, 255),
            width=1,
        )

        midpoint = (
            self.color_min
            + self.color_max
        ) / 2.0

        draw.text(
            (
                75,
                bar_top - 7,
            ),
            f"{self.color_max:.2f}",
            fill=(20, 20, 20, 255),
        )

        draw.text(
            (
                75,
                (bar_top + bar_bottom) // 2 - 7,
            ),
            f"{midpoint:.2f}",
            fill=(20, 20, 20, 255),
        )

        draw.text(
            (
                75,
                bar_bottom - 7,
            ),
            f"{self.color_min:.2f}",
            fill=(20, 20, 20, 255),
        )

        return legend

    def add_legend_to_image(self, image):
        legend = (
            self.create_color_scale_legend()
        )

        margin = 20

        x = (
            image.width
            - legend.width
            - margin
        )

        y = margin

        image = image.convert(
            "RGBA"
        )

        image.alpha_composite(
            legend,
            (x, y),
        )

        return image.convert(
            "RGB"
        )

    def export_image(self):
        if self.canvas.base_image is None:
            QMessageBox.information(
                self,
                "Export image",
                "Open an image first.",
            )

            return

        filename, selected_filter = (
            QFileDialog.getSaveFileName(
                self,
                "Export image",
                "",
                "PNG (*.png);;JPEG (*.jpg *.jpeg)",
            )
        )

        if not filename:
            return

        try:
            # Render markers on the original image first.
            annotated = self.render_markers(
                self.canvas.base_image
            )

            # Rotate the complete annotated image.
            # Therefore markers remain attached to
            # the corresponding image features.
            rotated = annotated.rotate(
                self.canvas.rotation,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(32, 32, 32),
            )

            # Add the legend after rotation so it stays
            # upright in the exported image.
            exported = (
                self.add_legend_to_image(
                    rotated
                )
            )

            if filename.lower().endswith(
                (".jpg", ".jpeg")
            ):
                exported.save(
                    filename,
                    quality=95,
                )
            else:
                exported.save(
                    filename
                )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                f"Could not export the image:\n{exc}",
            )

            return

        self.statusBar().showMessage(
            f"Exported image to {filename}"
        )


def main():
    app = QApplication(sys.argv)

    window = ImageMarkerApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()