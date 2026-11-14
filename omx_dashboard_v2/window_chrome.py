"""Compact navigation title bar with native Wayland/X11 move and resize."""
from PySide6.QtCore import Qt, QPoint, QRectF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QButtonGroup


class WindowButton(QPushButton):
    def __init__(self, kind, tooltip, callback, parent):
        super().__init__(parent)
        self.kind = kind
        self.restore = False
        self.setObjectName("windowClose" if kind == "close" else "windowControl")
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(40, 40)
        self.clicked.connect(callback)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#c0cede"), 1.4))
        x, y = self.width() / 2, self.height() / 2
        if self.kind == "minimize":
            painter.drawLine(QPoint(int(x - 5), int(y + 3)), QPoint(int(x + 5), int(y + 3)))
        elif self.kind == "close":
            painter.drawLine(QPoint(int(x - 5), int(y - 5)), QPoint(int(x + 5), int(y + 5)))
            painter.drawLine(QPoint(int(x + 5), int(y - 5)), QPoint(int(x - 5), int(y + 5)))
        elif self.restore:
            painter.drawRect(QRectF(x - 2, y - 5, 8, 8))
            painter.fillRect(QRectF(x - 5, y - 2, 8, 8), self.palette().window())
            painter.drawRect(QRectF(x - 5, y - 2, 8, 8))
        else:
            painter.drawRect(QRectF(x - 5, y - 5, 10, 10))


class NavigationTitleBar(QWidget):
    def __init__(self, window, pages):
        super().__init__(window)
        self.host = window
        self.pages = pages
        self._move_offset = None
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedHeight(42)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 3, 0)
        row.setSpacing(0)
        logo = QLabel()
        logo.setPixmap(window.windowIcon().pixmap(22, 22))
        logo.setFixedWidth(30)
        logo.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(logo)
        name = QLabel("OMX")
        name.setObjectName("titleBrand")
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addSpacing(18)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i in range(pages.count()):
            button = QPushButton(pages.tabText(i))
            button.setObjectName("titleNav")
            button.setCheckable(True)
            button.setFixedHeight(42)
            button.clicked.connect(lambda checked=False, index=i: pages.setCurrentIndex(index))
            self.nav_group.addButton(button, i)
            self.nav_buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        self.minimize_button = WindowButton("minimize", "최소화", window.showMinimized, self)
        self.maximize_button = WindowButton("maximize", "최대화", self.toggle_maximized, self)
        # Use the existing closeEvent, including its recording/stop confirmations.
        self.close_button = WindowButton("close", "닫기", window.close, self)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            row.addWidget(button)
        pages.currentChanged.connect(self.select_page)
        self.select_page(pages.currentIndex())

    def select_page(self, index):
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)

    def sync_window_state(self):
        maximized = self.host.isMaximized()
        self.maximize_button.restore = maximized
        text = "이전 크기로" if maximized else "최대화"
        self.maximize_button.setToolTip(text)
        self.maximize_button.setAccessibleName(text)
        self.maximize_button.update()

    def toggle_maximized(self):
        self._move_offset = None
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()
        self.sync_window_state()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        handle = self.host.windowHandle()
        if handle is not None and handle.startSystemMove():
            self._move_offset = None
        else:
            # Useful on platforms without native interactive move (including offscreen QA).
            if self.host.isMaximized():
                ratio = event.position().x() / max(1, self.width())
                self.host.showNormal()
                self._move_offset = QPoint(int(self.host.width() * ratio), int(event.position().y()))
            else:
                self._move_offset = event.globalPosition().toPoint() - self.host.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._move_offset is not None and event.buttons() & Qt.LeftButton:
            self.host.move(event.globalPosition().toPoint() - self._move_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._move_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ResizeEdge(QWidget):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.host = window
        self.edges = edges
        self._origin = None
        self._geometry = None
        self.setCursor(cursor)
        self.setStyleSheet("background:transparent;border:0;")

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        handle = self.host.windowHandle()
        if handle is not None and handle.startSystemResize(self.edges):
            self._origin = None
        else:
            self._origin = event.globalPosition().toPoint()
            self._geometry = self.host.geometry()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is None or not event.buttons() & Qt.LeftButton:
            return super().mouseMoveEvent(event)
        delta = event.globalPosition().toPoint() - self._origin
        rect = type(self._geometry)(self._geometry)
        min_w, min_h = self.host.minimumWidth(), self.host.minimumHeight()
        if self.edges & Qt.LeftEdge:
            rect.setLeft(min(rect.left() + delta.x(), rect.right() - min_w + 1))
        if self.edges & Qt.RightEdge:
            rect.setRight(max(rect.right() + delta.x(), rect.left() + min_w - 1))
        if self.edges & Qt.TopEdge:
            rect.setTop(min(rect.top() + delta.y(), rect.bottom() - min_h + 1))
        if self.edges & Qt.BottomEdge:
            rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + min_h - 1))
        self.host.setGeometry(rect)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._origin = None
        self._geometry = None
        super().mouseReleaseEvent(event)


class WindowResizeEdges:
    """Only eight narrow edge widgets receive resize events; no global event filter."""
    def __init__(self, window):
        self.host = window
        specs = [
            (Qt.LeftEdge, Qt.SizeHorCursor), (Qt.RightEdge, Qt.SizeHorCursor),
            (Qt.TopEdge, Qt.SizeVerCursor), (Qt.BottomEdge, Qt.SizeVerCursor),
            (Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor),
            (Qt.TopEdge | Qt.RightEdge, Qt.SizeBDiagCursor),
            (Qt.BottomEdge | Qt.LeftEdge, Qt.SizeBDiagCursor),
            (Qt.BottomEdge | Qt.RightEdge, Qt.SizeFDiagCursor),
        ]
        self.handles = [ResizeEdge(window, edge, cursor) for edge, cursor in specs]
        self.update()

    def update(self):
        w, h, d = self.host.width(), self.host.height(), 5
        boxes = [(0,d,d,h-2*d), (w-d,d,d,h-2*d), (d,0,w-2*d,d), (d,h-d,w-2*d,d),
                 (0,0,d,d), (w-d,0,d,d), (0,h-d,d,d), (w-d,h-d,d,d)]
        visible = not (self.host.isMaximized() or self.host.isFullScreen())
        for handle, box in zip(self.handles, boxes):
            handle.setGeometry(*box)
            handle.setVisible(visible)
            handle.raise_()
