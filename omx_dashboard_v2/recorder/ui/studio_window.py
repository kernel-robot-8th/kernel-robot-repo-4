"""v2 presentation layer; recording and robot operations remain in MainWindow."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QButtonGroup,
)
from .main_window import MainWindow, MOTORS, COLS, CAMERA_ROLES
from theme import CAM_STYLE


def label(text, name="muted"):
    w = QLabel(text)
    w.setObjectName(name)
    return w


def panel(title):
    box = QFrame()
    box.setObjectName("panel")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    layout.addWidget(label(title, "cardTitle"))
    return box, layout


class StudioWindow(MainWindow):
    def __init__(self):
        super().__init__()
        for tabs in self.findChildren(QTabWidget):
            tabs.tabBar().setDrawBase(False)

    def _build_dashboard(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 14)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(18)
        outer.addLayout(body, 1)
        left = QVBoxLayout()
        left.setSpacing(10)
        body.addLayout(left, 1)

        camera_tools = QHBoxLayout()
        camera_tools.addWidget(label("카메라", "cardTitle"))
        self.lbl_counts = label("", "metric")
        camera_tools.addWidget(self.lbl_counts, 0, Qt.AlignVCenter)
        camera_tools.addStretch()
        self.camera_modes = QButtonGroup(self)
        self.camera_mode_buttons = {}
        for key, title in (("all", "나란히"), ("wrist", "손목 확대"), ("top", "상단 확대")):
            button = QPushButton(title)
            button.setObjectName("cameraMode")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setChecked(key == "all")
            self.camera_modes.addButton(button)
            self.camera_mode_buttons[key] = button
            button.clicked.connect(lambda checked=False, role=key: self._camera_focus(role))
            camera_tools.addWidget(button)
        left.addLayout(camera_tools)
        camera_row = QHBoxLayout()
        camera_row.setSpacing(12)
        self.cam_labels = {}
        self.camera_panels = {}
        for role in CAMERA_ROLES:
            name = {"wrist": "손목 카메라", "top": "상단 카메라"}.get(role, role)
            box, bl = panel(name + "  ·  " + role.upper())
            view = QLabel("세션 준비 후 연결됩니다")
            view.setMinimumSize(180, 70)
            view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            view.setAlignment(Qt.AlignCenter)
            view.setStyleSheet(CAM_STYLE)
            bl.addWidget(view, 1)
            self.cam_labels[role] = view
            self.camera_panels[role] = box
            camera_row.addWidget(box, 1)
        left.addLayout(camera_row, 3)

        self.lbl_banner = QLabel()
        self.lbl_banner.setAlignment(Qt.AlignCenter)
        self.lbl_banner.setMinimumHeight(46)
        self.lbl_banner.setWordWrap(True)
        left.addWidget(self.lbl_banner)

        telemetry, tl = panel("모니터링")
        tl.takeAt(0).widget().deleteLater()
        telemetry.setMaximumHeight(240)
        self.telemetry_panel = telemetry
        status_row = QHBoxLayout()
        self.lbl_loop = label("")
        self.lbl_ee = label("", "muted")
        self.lbl_ee.setWordWrap(True)
        status_row.addWidget(self.lbl_ee, 1)
        status_row.addWidget(self.lbl_loop)
        tl.addLayout(status_row)
        monitor_tabs = QTabWidget()
        self.table = QTableWidget(len(MOTORS), len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setVerticalHeaderLabels(MOTORS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(100)
        for r in range(len(MOTORS)):
            for c in range(len(COLS)):
                item = QTableWidgetItem("—")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFocusPolicy(Qt.ClickFocus)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("연결과 저장 기록이 여기에 표시됩니다.")
        monitor_tabs.addTab(self.table, "관절 상태")
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 4, 0, 0)
        log_layout.addWidget(self.log, 1)
        self.btn_upload = QPushButton("Hugging Face에 업로드")
        self.btn_upload.clicked.connect(self._upload)
        log_layout.addWidget(self.btn_upload, 0, Qt.AlignRight)
        monitor_tabs.addTab(log_page, "실행 로그 · 업로드")
        tl.addWidget(monitor_tabs, 1)
        self.monitor_toggle = QPushButton("▸ 관절 상태 · 실행 로그 · 업로드")
        self.monitor_toggle.setObjectName("monitorToggle")
        self.monitor_toggle.setCheckable(True)
        self.monitor_toggle.setFocusPolicy(Qt.NoFocus)
        self.monitor_toggle.toggled.connect(telemetry.setVisible)
        self.monitor_toggle.toggled.connect(
            lambda on: self.monitor_toggle.setText(("▾" if on else "▸") + " 관절 상태 · 실행 로그 · 업로드")
        )
        left.addWidget(self.monitor_toggle)
        left.addWidget(telemetry, 2)
        telemetry.setVisible(False)

        side_holder = QWidget()
        side_holder.setMinimumWidth(365)
        side_holder.setMaximumWidth(410)
        side_layout = QVBoxLayout(side_holder)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        side = QScrollArea()
        side.setWidgetResizable(True)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls = QWidget()
        right = QVBoxLayout(controls)
        right.setContentsMargins(0, 0, 8, 0)
        right.setSpacing(12)
        side.setWidget(controls)
        side_layout.addWidget(side, 1)
        body.addWidget(side_holder)

        session, sl = panel("01  저장 위치")
        sl.setSpacing(7)
        sl.addWidget(label("녹화 폴더", "fieldLabel"))
        folder_row = QHBoxLayout()
        self.ed_output = QLineEdit()
        self.ed_output.setMinimumWidth(0)
        self.btn_browse = QPushButton("찾기")
        self.btn_browse.setFixedWidth(56)
        self.btn_browse.clicked.connect(self._browse_output)
        folder_row.addWidget(self.ed_output, 1)
        folder_row.addWidget(self.btn_browse)
        sl.addLayout(folder_row)
        sl.addWidget(label("태스크명  ·  녹화 폴더 안에 생성됩니다", "fieldLabel"))
        self.ed_task_name = QLineEdit()
        self.ed_task_name.setPlaceholderText("box_white_basket_20261031")
        sl.addWidget(self.ed_task_name)
        sl.addWidget(label("작업 문장", "fieldLabel"))
        self.ed_task_text = QLineEdit()
        self.ed_task_text.setPlaceholderText("상자를 집어서 흰 바구니에 넣기")
        self.ed_task_text.returnPressed.connect(self.ed_task_text.clearFocus)
        sl.addWidget(self.ed_task_text)
        self.btn_session = QPushButton("세션 준비")
        self.btn_session.setObjectName("primary")
        self.btn_session.clicked.connect(self._start_session)
        sl.addWidget(self.btn_session)
        self.lbl_session = label("저장 위치를 정하고 세션을 준비하세요.", "sessionPath")
        self.lbl_session.setWordWrap(True)
        self.lbl_session.setMinimumWidth(0)
        self.lbl_session.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sl.addWidget(self.lbl_session)
        right.addWidget(session)

        preparation, pl = panel("02  로봇 준비")
        connection = QHBoxLayout()
        self.btn_bringup = QPushButton("로봇 연결")
        self.btn_servo_off = QPushButton("모터 해제")
        self.btn_servo_off.setObjectName("danger")
        self.btn_bringup.clicked.connect(self._bringup)
        self.btn_servo_off.clicked.connect(self._servo_off)
        connection.addWidget(self.btn_bringup)
        connection.addWidget(self.btn_servo_off)
        pl.addLayout(connection)
        self.lbl_pose = label("")
        self.lbl_pose.setWordWrap(True)
        pl.addWidget(self.lbl_pose)
        disclosure = QPushButton("▸ 자세 설정 · 원격조종")
        disclosure.setObjectName("disclosure")
        disclosure.setCheckable(True)
        pose_tools = QWidget()
        pg = QGridLayout(pose_tools)
        pg.setContentsMargins(0, 0, 0, 0)
        self.btn_init = QPushButton("초기 자세 저장")
        self.btn_rest = QPushButton("대기 자세 저장")
        self.btn_free = QPushButton("리더암 해제 · 원격조종")
        self.btn_init.clicked.connect(lambda: self.ctrl.capture_pose("init"))
        self.btn_rest.clicked.connect(lambda: self.ctrl.capture_pose("rest"))
        self.btn_free.clicked.connect(self.ctrl.free_leader)
        pg.addWidget(self.btn_init, 0, 0)
        pg.addWidget(self.btn_rest, 0, 1)
        pg.addWidget(self.btn_free, 1, 0, 1, 2)
        pose_tools.setVisible(False)
        disclosure.toggled.connect(pose_tools.setVisible)
        disclosure.toggled.connect(lambda on: disclosure.setText(("▾" if on else "▸") + " 자세 설정 · 원격조종"))
        pl.addWidget(disclosure)
        pl.addWidget(pose_tools)
        right.addWidget(preparation)

        episode, el = panel("03  에피소드 녹화")
        self.btn_record = QPushButton("● 녹화 시작     Space")
        self.btn_record.setObjectName("record")
        self.btn_record.setMinimumHeight(48)
        self.btn_record.clicked.connect(self._record)
        el.addWidget(self.btn_record)
        outcomes = QHBoxLayout()
        self.btn_success = QPushButton("성공 저장   S")
        self.btn_fail = QPushButton("실패 저장   F")
        self.btn_discard = QPushButton("이번 에피소드 버리기   D")
        self.btn_success.clicked.connect(lambda: self._end("success"))
        self.btn_fail.clicked.connect(lambda: self._end("fail"))
        self.btn_discard.clicked.connect(lambda: self._end("discard"))
        outcomes.addWidget(self.btn_success)
        outcomes.addWidget(self.btn_fail)
        el.addLayout(outcomes)
        el.addWidget(self.btn_discard)
        side_layout.addWidget(episode)
        right.addStretch()
        for b in (self.btn_bringup, self.btn_servo_off, self.btn_init, self.btn_rest,
                  self.btn_free, self.btn_record, self.btn_success, self.btn_fail,
                  self.btn_discard, self.btn_upload):
            b.setFocusPolicy(Qt.NoFocus)
        return root

    def _camera_focus(self, role):
        for key, panel in self.camera_panels.items():
            panel.setVisible(role == "all" or key == role)

    def _build_settings(self):
        content = super()._build_settings()
        content.layout().setContentsMargins(22, 16, 22, 20)
        content.layout().setSpacing(20)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _refresh(self):
        super()._refresh()
        s = self.ctrl.snapshot()
        self.btn_browse.setEnabled(self.ed_output.isEnabled())
        self.lbl_counts.setText(f"성공  {self.counts.get('success', 0)}     실패  {self.counts.get('fail', 0)}")
        if not s.get("recording", False):
            self.btn_record.setText("● 녹화 시작     Space")
        if not self.session:
            self.lbl_banner.setText("01  저장 위치를 정한 뒤, 세션을 준비하세요")
        elif not self.ctrl.running:
            self.lbl_banner.setText("02  세션 준비 완료 · 로봇을 연결하세요")
        self.lbl_pose.setText(
            f"초기 자세: {'저장됨' if self.poses.get('init') else '미설정'}  ·  "
            f"대기 자세: {'저장됨' if self.poses.get('rest') else '초기 자세 사용'}"
        )
