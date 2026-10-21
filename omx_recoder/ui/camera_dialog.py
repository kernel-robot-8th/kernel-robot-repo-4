from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.cameras import scan_cameras
from core.config import CAMERA_ROLES

NONE_ROLE = "미사용"


def to_pixmap(rgb, w: int, h: int) -> QPixmap:
    hh, ww, _ = rgb.shape
    img = QImage(rgb.data, ww, hh, 3 * ww, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class CameraPickerDialog(QDialog):
    def __init__(self, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("카메라 찾기")
        self.resize(760, 560)
        self.result_map: dict = {}

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.found = scan_cameras()
        finally:
            QApplication.restoreOverrideCursor()

        layout = QVBoxLayout(self)
        if not self.found:
            layout.addWidget(QLabel("연결된 카메라를 찾지 못했습니다."))
        layout.addWidget(QLabel("각 카메라의 역할(wrist / top)을 지정하세요."))

        inner = QWidget()
        grid = QGridLayout(inner)
        self.combos = []
        cur_ids = {str(v.get("index_or_path", "")): k for k, v in current.items()}
        for i, cam in enumerate(self.found):
            thumb = QLabel()
            thumb.setFixedSize(320, 240)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("background:#111;color:#aaa;")
            if cam["frame"] is not None:
                thumb.setPixmap(to_pixmap(cam["frame"], 320, 240))
            else:
                thumb.setText("프레임 없음")
            info = QLabel(f"{cam['id']}\n{cam['width']}x{cam['height']} @ {cam['fps']:.0f}fps" if cam["fps"] else str(cam["id"]))
            combo = QComboBox()
            combo.addItems([NONE_ROLE, *CAMERA_ROLES])
            role = cur_ids.get(str(cam["id"]))
            if role:
                combo.setCurrentText(role)
            self.combos.append((cam["id"], combo))
            r, c = divmod(i, 2)
            box = QVBoxLayout()
            w = QWidget()
            w.setLayout(box)
            box.addWidget(thumb)
            box.addWidget(info)
            box.addWidget(combo)
            grid.addWidget(w, r, c)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        mapping = {}
        for cam_id, combo in self.combos:
            role = combo.currentText()
            if role == NONE_ROLE:
                continue
            if role in mapping:
                QMessageBox.warning(self, "중복", f"'{role}' 역할이 두 카메라에 지정되었습니다.")
                return
            mapping[role] = cam_id
        self.result_map = mapping
        self.accept()
