#!/usr/bin/env python3
"""OMX 대시보드 — 데스크톱 프로그램 창으로 실행.

  source ~/venv/il/bin/activate
  python app.py

화면:
  추론 — index.html 화면 (server.py 를 이 프로그램 안에서 백그라운드로 돌림)
  녹화 — 팀 수집 대시보드(recorder/ = omx_recoder)를 그대로 끼워 넣음 (rec_embed.py)
  녹화 설정 — 녹화 화면의 장비 설정을 같은 상단 메뉴로 통합
PySide6의 웹 화면(QtWebEngine)을 못 쓰는 환경이면 추론 화면만 기본 브라우저로 엽니다.
"""

import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 수집 대시보드 main.py와 같은 처리: Python 3.10 + PySide6 조합에서 typing.Self 충돌 방지
try:
    import typing_extensions  # noqa: F401
except ImportError:
    pass

import server  # noqa: E402

TITLE = "OMX Studio · v2"


def start_backend():
    srv = server.make_server(0)  # 빈 포트 자동 선택
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def run_window(url: str) -> int:
    from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
    from PySide6.QtGui import QIcon, QColor
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget, QVBoxLayout

    import rec_embed
    from theme import apply_palette, BG
    from window_chrome import NavigationTitleBar, WindowResizeEdges

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setWindowTitle(TITLE)
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "icon.svg")))
            self.setMinimumSize(1024, 700)
            screen = QApplication.primaryScreen().availableGeometry()
            self.resize(min(1480, screen.width() - 64), min(960, screen.height() - 64))
            self.view = QWebEngineView(self)
            self.view.page().setBackgroundColor(QColor(BG))
            self.view.settings().setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
            self.view.setUrl(QUrl(url + "/?app=1"))

            # 녹화 탭: 팀 수집 대시보드. 못 불러오면 이유만 보여주고 추론은 그대로 씀
            self.rec = None
            try:
                self.rec = rec_embed.make_recorder(server)
                server.BUSY_CHECK = self.rec.robot_busy  # 녹화 탭이 로봇을 잡고 있으면 추론 시작을 막음
                rec_tab = self.rec
            except Exception as e:  # noqa: BLE001
                rec_tab = QLabel(f"녹화 탭을 못 불러왔어:\n{type(e).__name__}: {e}\n\n"
                                 "il 가상환경에 PySide6, pyyaml, opencv 가 있는지 확인해줘.")
                rec_tab.setAlignment(Qt.AlignCenter)
                rec_tab.setWordWrap(True)

            self.tabs = QTabWidget(self)
            self.tabs.setObjectName("mainTabs")
            self.tabs.setDocumentMode(True)
            self.tabs.tabBar().setDrawBase(False)
            self.tabs.addTab(self.view, "모델 추론")
            self.tabs.addTab(rec_tab, "데이터 녹화")
            if self.rec is not None:
                recorder_tabs = self.rec.centralWidget()
                settings_page = recorder_tabs.widget(1)
                recorder_tabs.removeTab(1)
                recorder_tabs.tabBar().hide()
                self.tabs.addTab(settings_page, "녹화 설정")
            self.tabs.setStyleSheet(rec_embed.QSS)
            self.view.setStyleSheet("")  # 웹 화면은 자체 디자인
            try:  # 마지막으로 보던 탭 기억
                from PySide6.QtCore import QSettings
                self.settings = QSettings("omx", "dashboard-v2")
                self.tabs.setCurrentIndex(int(self.settings.value("tab", 0)))
                self.tabs.currentChanged.connect(lambda i: self.settings.setValue("tab", i))
            except Exception:  # noqa: BLE001
                pass
            self.tabs.tabBar().hide()
            shell = QWidget(self)
            layout = QVBoxLayout(shell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.titlebar = NavigationTitleBar(self, self.tabs)
            layout.addWidget(self.titlebar)
            layout.addWidget(self.tabs, 1)
            self.setCentralWidget(shell)
            self.resize_edges = WindowResizeEdges(self)

            # 추론이 끝날 때마다 로그 전체를 클립보드에 자동 복사
            self.copied_run = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.auto_copy_log)
            self.timer.start(500)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, "resize_edges"):
                self.resize_edges.update()

        def changeEvent(self, event):
            super().changeEvent(event)
            if event.type() == QEvent.WindowStateChange and hasattr(self, "titlebar"):
                self.titlebar.sync_window_state()
                self.resize_edges.update()

        def auto_copy_log(self):
            r = server.RUNNER
            if r.run_id == self.copied_run or r.running() or r.ended is None:
                return
            self.copied_run = r.run_id
            QApplication.clipboard().setText(r.full_log())
            self.view.page().runJavaScript(
                "window.toast && toast('실행 끝 — 로그를 클립보드에 복사했어 (Ctrl+V)')"
            )

        def closeEvent(self, event):
            # 녹화 탭 먼저: 녹화 중이면 막고, BringUp 상태면 Servo OFF 후 종료할지 물어봄 (팀 코드 그대로)
            if self.rec is not None and not self.rec.close():
                event.ignore()
                return
            if server.RUNNER.running():
                ans = QMessageBox.question(
                    self,
                    TITLE,
                    "추론이나 녹화가 아직 돌고 있어. 정지하고 프로그램을 끌까?\n(녹화 중이면 지금 에피소드는 저장 안 됨)",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if ans != QMessageBox.Yes:
                    event.ignore()
                    return
                self.setWindowTitle(f"{TITLE} — 정지 중…")
                QApplication.processEvents()
                server.stop_running()
            event.accept()

    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    app.setDesktopFileName("omx-dashboard-v2")
    apply_palette(app)
    app.setStyleSheet(rec_embed.QSS)
    win = Window()
    win.show()
    return app.exec()


def main():
    srv, url = start_backend()
    print(f"{TITLE}: {url}")
    try:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
        except ImportError as e:
            print(f"[알림] PySide6 웹 화면을 못 불러와서 브라우저로 엽니다: {e}")
            print("       창으로 쓰려면: pip install PySide6==6.8.3")
            webbrowser.open(url)
            print("끄려면 이 터미널에서 Ctrl+C")
            threading.Event().wait()
            return 0
        return run_window(url)
    except KeyboardInterrupt:
        return 0
    finally:
        server.stop_running()
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    sys.exit(main())
