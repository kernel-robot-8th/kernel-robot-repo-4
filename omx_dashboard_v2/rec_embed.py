"""팀 수집 대시보드(recorder/ = omx_recoder)를 추론 대시보드 창의 '녹화' 탭으로 끼워 넣기.

v2 화면은 ui/studio_window.py에서 구성하고, 녹화 동작은 기존 코드에 맡김:
- 색·모양(QSS)을 추론 탭과 비슷한 밝은 회색 톤으로
- 팀 코드의 프로그램 전체 키 감시를 떼고 같은 단축키(Space/S/F/D/Esc)를 녹화 탭 전용으로 다시 검
  (웹 화면과 같이 있으면 PySide6가 죽는 문제 방지 + 추론 탭에선 녹화 단축키가 안 먹게)
- 추론이 돌고 있을 때는 BringUp을 막음 (로봇·카메라가 하나라서)
"""

import sys
from pathlib import Path

REC_DIR = Path(__file__).resolve().parent / "recorder"

from theme import QSS, CAM_STYLE, STYLES, MUTED


def make_recorder(server):
    """녹화 탭 위젯을 만들어서 돌려줌. 실패하면 예외를 그대로 올림 (app.py가 안내 문구로 바꿈)."""
    if str(REC_DIR) not in sys.path:
        sys.path.insert(0, str(REC_DIR))

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ui import main_window as mw
    from ui.studio_window import StudioWindow

    for name, style in STYLES.items():  # 팀 코드가 실행 중에 이 이름으로 색을 찾아 씀
        setattr(mw, name, style)

    class EmbeddedRecorder(StudioWindow):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.Widget)  # 별도 창이 아니라 탭 안의 화면으로
            self.setObjectName("omxRecorder")
            self.setStyleSheet(QSS)
            for lbl in self.cam_labels.values():
                lbl.setStyleSheet(CAM_STYLE)
            self.table.verticalHeader().setStyleSheet(f"QHeaderView::section {{ color: {MUTED}; }}")
            self.centralWidget().setContentsMargins(0, 0, 0, 0)

            # 팀 코드는 프로그램 전체에 키 감시(eventFilter)를 거는데, 같은 창의 웹 화면(추론 탭) 내부
            # 객체까지 건드려서 PySide6가 죽음 → 감시는 떼고 같은 단축키를 이 탭 전용으로 다시 검.
            # 입력칸에 글씨를 칠 때는 입력칸이 키를 먼저 가져가서 단축키가 안 먹음 (팀 코드와 같은 동작).
            QApplication.instance().removeEventFilter(self)
            for key, fn in (
                (Qt.Key_Space, self._record),
                (Qt.Key_S, lambda: self._end("success")),
                (Qt.Key_F, lambda: self._end("fail")),
                (Qt.Key_D, lambda: self._end("discard")),
                (Qt.Key_Escape, self._clear_focus),
            ):
                sc = QShortcut(QKeySequence(key), self)
                sc.setContext(Qt.WindowShortcut)  # 녹화 탭이 보일 때만 동작 (숨은 위젯의 단축키는 Qt가 무시)
                sc.setAutoRepeat(False)
                sc.activated.connect(fn)

        def eventFilter(self, obj, event):  # 혹시 다시 걸려도 아무것도 안 함
            return False

        def _clear_focus(self):
            w = QApplication.focusWidget()
            if w is not None:
                w.clearFocus()

        def _bringup(self):
            if server.RUNNER.running():
                QMessageBox.warning(self, "BringUp", "추론 탭에서 모델이 돌고 있어. 로봇·카메라가 겹치니까 먼저 정지해줘.")
                return
            super()._bringup()

        def robot_busy(self) -> bool:
            return bool(self.ctrl.running)

    return EmbeddedRecorder()
