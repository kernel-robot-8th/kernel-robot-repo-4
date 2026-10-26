import json
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import hub, trainer
from core.cameras import CameraManager
from core.config import (
    APP_DIR,
    CAMERA_ROLES,
    MOTORS,
    load_config,
    load_poses,
    save_config,
    save_poses,
)
from core.recorder import Recorder
from core.robot_ctrl import Mode, RobotController
from core.trainer import Trainer
from ui.camera_dialog import CameraPickerDialog, to_pixmap

VCODECS = ["libsvtav1", "h264", "hevc", "auto"]
COLS = ["리더", "팔로워", "차이", "속도", "전류", "온도(°C)", "전압(V)"]

STYLE_GREEN = "background:#2e7d32;color:white;font-weight:bold;"
STYLE_RED = "background:#c62828;color:white;font-weight:bold;"
STYLE_ORANGE = "background:#ef6c00;color:white;font-weight:bold;"
STYLE_BLUE = "background:#1565c0;color:white;font-weight:bold;"
STYLE_GRAY = "background:#616161;color:white;font-weight:bold;"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OMX 모방학습 데이터 수집")
        self.resize(1500, 920)

        self.cfg = load_config()
        self.poses = load_poses()
        self.cameras = CameraManager()
        self.recorder = Recorder()
        self.ctrl = RobotController(self.cameras, self.recorder)
        self.ui_events: queue.Queue = queue.Queue()
        self.session: dict | None = None
        self.uploading = False
        self.last_task_text = self.cfg["session"]["task_text"]
        self.counts = {"success": 0, "fail": 0}
        self.trainer = Trainer(self._omx_dir())
        self.train_total = 0
        self.train_policy = ""  # policy whose values the settings box currently shows
        self.docker_ok = False
        self.image_ok = False
        self.train_root: Path | None = None
        self.train_eps = 0
        self.train_lengths: dict[int, int] = {}
        self.train_episodes: list[int] | None = None  # None = every episode
        self.train_holdout: list[int] = []
        self.train_split_error = ""

        tabs = QTabWidget()
        tabs.addTab(self._build_dashboard(), "대시보드")
        tabs.addTab(self._build_train(), "학습")
        tabs.addTab(self._build_settings(), "설정")
        self.setCentralWidget(tabs)
        self._load_settings_to_ui()
        self._attach_running_train()

        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self._refresh()

    # ================================================================== UI build
    def _build_dashboard(self) -> QWidget:
        root = QWidget()
        v = QVBoxLayout(root)

        # --- session bar
        sbox = QGroupBox("세션")
        sh = QHBoxLayout(sbox)
        self.ed_output = QLineEdit()
        btn_browse = QPushButton("폴더 선택")
        btn_browse.clicked.connect(self._browse_output)
        self.ed_task_name = QLineEdit()
        self.ed_task_name.setPlaceholderText("태스크명 (폴더·repo 이름)")
        self.btn_session = QPushButton("세션 시작")
        self.btn_session.clicked.connect(self._start_session)
        self.lbl_session = QLabel("세션 없음")
        sh.addWidget(QLabel("저장 경로"))
        sh.addWidget(self.ed_output, 3)
        sh.addWidget(btn_browse)
        sh.addWidget(QLabel("태스크명"))
        sh.addWidget(self.ed_task_name, 1)
        sh.addWidget(self.btn_session)
        sh.addWidget(self.lbl_session, 2)
        v.addWidget(sbox)

        body = QHBoxLayout()
        v.addLayout(body, 1)

        # --- left: cameras + status
        left = QVBoxLayout()
        cam_row = QHBoxLayout()
        self.cam_labels = {}
        for role in CAMERA_ROLES:
            box = QGroupBox(role)
            bl = QVBoxLayout(box)
            lbl = QLabel("카메라 없음")
            lbl.setFixedSize(480, 360)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background:#111;color:#888;")
            bl.addWidget(lbl)
            self.cam_labels[role] = lbl
            cam_row.addWidget(box)
        left.addLayout(cam_row)

        self.lbl_banner = QLabel()
        self.lbl_banner.setAlignment(Qt.AlignCenter)
        self.lbl_banner.setMinimumHeight(56)
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        self.lbl_banner.setFont(f)
        left.addWidget(self.lbl_banner)

        info = QHBoxLayout()
        self.lbl_counts = QLabel()
        self.lbl_loop = QLabel()
        self.lbl_ee = QLabel()
        for w in (self.lbl_counts, self.lbl_loop):
            w.setStyleSheet("font-size:14px;")
        info.addWidget(self.lbl_counts)
        info.addStretch()
        info.addWidget(self.lbl_loop)
        left.addLayout(info)
        self.lbl_ee.setStyleSheet("font-family:monospace;font-size:13px;")
        left.addWidget(self.lbl_ee)

        self.table = QTableWidget(len(MOTORS), len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setVerticalHeaderLabels(MOTORS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        for r in range(len(MOTORS)):
            for c in range(len(COLS)):
                it = QTableWidgetItem("-")
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
        left.addWidget(self.table)
        body.addLayout(left, 3)

        # --- right: controls
        right = QVBoxLayout()
        cbox = QGroupBox("제어")
        cg = QGridLayout(cbox)
        self.btn_bringup = QPushButton("BringUp")
        self.btn_servo_off = QPushButton("Servo OFF")
        self.btn_init = QPushButton("리더 자세 → Init 저장")
        self.btn_rest = QPushButton("리더 자세 → Rest 저장")
        self.btn_free = QPushButton("리더암 해제 (녹화 없이 원격조종)")
        self.btn_record = QPushButton("녹화  [Space]")
        self.btn_success = QPushButton("Success  [S]")
        self.btn_fail = QPushButton("Fail  [F]")
        self.btn_discard = QPushButton("Discard  [D]")
        self.btn_upload = QPushButton("HF Hub 업로드")
        for b in (self.btn_bringup, self.btn_servo_off, self.btn_record, self.btn_success, self.btn_fail, self.btn_discard):
            b.setMinimumHeight(48)
            b.setFocusPolicy(Qt.NoFocus)
        for b in (self.btn_init, self.btn_rest, self.btn_free, self.btn_upload):
            b.setFocusPolicy(Qt.NoFocus)
        self.btn_bringup.clicked.connect(self._bringup)
        self.btn_servo_off.clicked.connect(self._servo_off)
        self.btn_init.clicked.connect(lambda: self.ctrl.capture_pose("init"))
        self.btn_rest.clicked.connect(lambda: self.ctrl.capture_pose("rest"))
        self.btn_free.clicked.connect(self.ctrl.free_leader)
        self.btn_record.clicked.connect(self._record)
        self.btn_success.clicked.connect(lambda: self._end("success"))
        self.btn_fail.clicked.connect(lambda: self._end("fail"))
        self.btn_discard.clicked.connect(lambda: self._end("discard"))
        self.btn_upload.clicked.connect(self._upload)
        cg.addWidget(self.btn_bringup, 0, 0)
        cg.addWidget(self.btn_servo_off, 0, 1)
        cg.addWidget(self.btn_init, 1, 0)
        cg.addWidget(self.btn_rest, 1, 1)
        cg.addWidget(self.btn_free, 2, 0, 1, 2)
        cg.addWidget(self.btn_record, 3, 0, 1, 2)
        cg.addWidget(self.btn_success, 4, 0)
        cg.addWidget(self.btn_fail, 4, 1)
        cg.addWidget(self.btn_discard, 5, 0, 1, 2)
        cg.addWidget(self.btn_upload, 6, 0, 1, 2)
        right.addWidget(cbox)

        tbox = QGroupBox("에피소드 태스크 문장")
        tl = QVBoxLayout(tbox)
        self.ed_task_text = QLineEdit()
        self.ed_task_text.setPlaceholderText("예: 신발 상자를 핑키 위로 옮겨")
        self.ed_task_text.returnPressed.connect(self.ed_task_text.clearFocus)
        self.lbl_pose = QLabel()
        tl.addWidget(self.ed_task_text)
        tl.addWidget(QLabel("Enter로 입력 완료 · 비우면 이전 문장 사용"))
        tl.addWidget(self.lbl_pose)
        right.addWidget(tbox)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFocusPolicy(Qt.ClickFocus)
        self.log.setMaximumBlockCount(2000)
        right.addWidget(QLabel("로그"))
        right.addWidget(self.log, 1)
        body.addLayout(right, 2)
        return root

    def _build_settings(self) -> QWidget:
        root = QWidget()
        h = QHBoxLayout(root)
        col1, col2 = QVBoxLayout(), QVBoxLayout()
        h.addLayout(col1)
        h.addLayout(col2)
        self.settings_boxes = []

        # robot
        rbox = QGroupBox("로봇")
        rf = QFormLayout(rbox)
        self.ed_fport, self.ed_fid = QLineEdit(), QLineEdit()
        self.ed_lport, self.ed_lid = QLineEdit(), QLineEdit()
        for ed in (self.ed_fport, self.ed_lport):
            ed.setPlaceholderText("auto")
            ed.setToolTip("auto: BringUp 때 모터 ID로 보드를 찾습니다. 경로를 적어도 응답이 없으면 자동 감지합니다.")
        rf.addRow("팔로워 포트", self.ed_fport)
        rf.addRow("팔로워 ID", self.ed_fid)
        rf.addRow("리더 포트", self.ed_lport)
        rf.addRow("리더 ID", self.ed_lid)
        col1.addWidget(rbox)

        # cameras
        cbox = QGroupBox("카메라")
        cf = QGridLayout(cbox)
        self.cam_edits = {}
        cf.addWidget(QLabel("역할"), 0, 0)
        for j, t in enumerate(["index / 경로", "width", "height", "fps"]):
            cf.addWidget(QLabel(t), 0, j + 1)
        for i, role in enumerate(CAMERA_ROLES, start=1):
            ed = QLineEdit()
            w, hh, fp = QSpinBox(), QSpinBox(), QSpinBox()
            w.setRange(160, 3840)
            hh.setRange(120, 2160)
            fp.setRange(1, 120)
            cf.addWidget(QLabel(role), i, 0)
            cf.addWidget(ed, i, 1)
            cf.addWidget(w, i, 2)
            cf.addWidget(hh, i, 3)
            cf.addWidget(fp, i, 4)
            self.cam_edits[role] = (ed, w, hh, fp)
        self.btn_find_cam = QPushButton("카메라 찾기")
        self.btn_find_cam.clicked.connect(self._find_cameras)
        cf.addWidget(self.btn_find_cam, len(CAMERA_ROLES) + 1, 0, 1, 5)
        col1.addWidget(cbox)

        # record
        recbox = QGroupBox("녹화")
        recf = QFormLayout(recbox)
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 120)
        self.sp_status = QDoubleSpinBox()
        self.sp_status.setRange(0.1, 30)
        self.sp_status.setSingleStep(0.5)
        self.cb_vcodec = QComboBox()
        self.cb_vcodec.addItems(VCODECS)
        recf.addRow("녹화 주기 (Hz)", self.sp_fps)
        recf.addRow("온도·전압 주기 (Hz)", self.sp_status)
        recf.addRow("비디오 코덱", self.cb_vcodec)
        col1.addWidget(recbox)
        col1.addStretch()

        # motion
        mbox = QGroupBox("동작")
        mf = QFormLayout(mbox)
        self.sp_move = QDoubleSpinBox()
        self.sp_move.setRange(0.5, 20)
        self.sp_step = QDoubleSpinBox()
        self.sp_step.setRange(0.0, 100)
        mf.addRow("Init/Rest 이동 시간 (s)", self.sp_move)
        mf.addRow("프레임당 최대 이동량 (0=제한 없음)", self.sp_step)
        col2.addWidget(mbox)

        # hub
        hbox = QGroupBox("Hugging Face Hub")
        hf = QFormLayout(hbox)
        self.ed_hub_user = QLineEdit()
        self.ck_private = QCheckBox("비공개(private) 업로드")
        btn_login = QPushButton("로그인 확인")
        btn_login.clicked.connect(self._check_login)
        hf.addRow("계정", self.ed_hub_user)
        hf.addRow("", self.ck_private)
        hf.addRow("", btn_login)
        col2.addWidget(hbox)

        # fk
        fbox = QGroupBox("EE 포즈 (FK) 보정")
        ff = QFormLayout(fbox)
        self.ed_fk_signs = QLineEdit()
        self.ed_fk_offsets = QLineEdit()
        ff.addRow("관절 부호 (5개)", self.ed_fk_signs)
        ff.addRow("관절 오프셋 deg (5개)", self.ed_fk_offsets)
        col2.addWidget(fbox)

        btn_save = QPushButton("설정 저장")
        btn_save.clicked.connect(self._save_settings)
        col2.addWidget(btn_save)
        col2.addStretch()

        self.settings_boxes = [rbox, cbox, recbox, mbox, fbox]
        return root

    def _build_train(self) -> QWidget:
        root = QWidget()
        h = QHBoxLayout(root)
        left = QVBoxLayout()
        h.addLayout(left, 1)

        ebox = QGroupBox("학습 환경 (omx_train · Docker)")
        ev = QVBoxLayout(ebox)
        self.lbl_docker = QLabel()
        self.lbl_docker.setWordWrap(True)
        self.btn_build = QPushButton("이미지 빌드")
        self.btn_build.setToolTip("선택한 정책 폴더의 Dockerfile로 학습 이미지를 만듭니다 (처음 한 번, 수 분 걸림)")
        self.btn_build.clicked.connect(self._build_image)
        btn_check = QPushButton("다시 확인")
        btn_check.clicked.connect(self._check_docker)
        erow = QHBoxLayout()
        for b in (self.btn_build, btn_check):
            b.setFocusPolicy(Qt.NoFocus)
            erow.addWidget(b)
        erow.addStretch()
        ev.addWidget(self.lbl_docker)
        ev.addLayout(erow)
        left.addWidget(ebox)

        dbox = QGroupBox("데이터")
        df = QFormLayout(dbox)
        self.ed_train_data = QLineEdit()
        self.ed_train_data.setPlaceholderText("비우면 현재 세션의 success 폴더")
        self.ed_train_data.setToolTip("LeRobot 데이터셋 폴더 (meta/info.json이 있는 폴더)")
        self.ed_train_data.editingFinished.connect(self._update_train_data)
        btn_pick = QPushButton("폴더 선택")
        btn_pick.clicked.connect(self._browse_train_data)
        btn_default = QPushButton("세션 폴더로")
        btn_default.clicked.connect(self._reset_train_data)
        for b in (btn_pick, btn_default):
            b.setFocusPolicy(Qt.NoFocus)
        prow = QHBoxLayout()
        prow.addWidget(self.ed_train_data, 1)
        prow.addWidget(btn_pick)
        prow.addWidget(btn_default)
        self.lbl_train_data = QLabel()
        self.lbl_train_data.setWordWrap(True)
        self.lbl_train_data.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ed_holdout = QLineEdit()
        self.ed_holdout.setPlaceholderText("예: 5,9 또는 3-5 (비우면 전체 학습)")
        self.ed_holdout.setToolTip("평가에 쓸 에피소드를 학습에서 뺍니다 (train.sh의 EPISODES)")
        self.ed_holdout.editingFinished.connect(self._update_train_data)
        df.addRow("데이터 폴더", prow)
        df.addRow("평가용 제외 에피소드", self.ed_holdout)
        df.addRow("", self.lbl_train_data)
        self.train_data_box = dbox
        left.addWidget(dbox)

        pbox = QGroupBox("학습 설정 (train.sh에 덮어쓸 값)")
        pf = QFormLayout(pbox)
        self.cb_policy = QComboBox()
        for key, folder in trainer.POLICIES.items():
            self.cb_policy.addItem(folder, key)
        self.cb_policy.currentIndexChanged.connect(self._policy_changed)
        self.btn_train_defaults = QPushButton("train.sh 값으로")
        self.btn_train_defaults.setToolTip("아래 값을 train.sh에 적힌 값(마지막 학습 설정)으로 되돌립니다")
        self.btn_train_defaults.setFocusPolicy(Qt.NoFocus)
        self.btn_train_defaults.clicked.connect(self._reset_train_params)
        polrow = QHBoxLayout()
        polrow.addWidget(self.cb_policy, 1)
        polrow.addWidget(self.btn_train_defaults)
        self.sp_gpu = QSpinBox()
        self.sp_gpu.setRange(0, 15)
        self.sp_steps = QSpinBox()
        self.sp_steps.setRange(10, 10_000_000)
        self.sp_steps.setSingleStep(1000)
        self.sp_batch = QSpinBox()
        self.sp_batch.setRange(1, 1024)
        self.sp_workers = QSpinBox()
        self.sp_workers.setRange(0, 64)
        self.sp_log_freq = QSpinBox()
        self.sp_log_freq.setRange(1, 1_000_000)
        self.sp_save_freq = QSpinBox()
        self.sp_save_freq.setRange(1, 10_000_000)
        self.ck_wandb = QCheckBox("Weights & Biases 기록")
        self.ck_aug = QCheckBox("이미지 증강 (밝기·대비·채도·색조·선명도·이동)")
        self.sp_epochs = QDoubleSpinBox()
        self.sp_epochs.setRange(0.1, 100_000)
        self.sp_epochs.setDecimals(1)
        self.sp_epochs.setValue(20)
        self.btn_epochs = QPushButton("step에 적용")
        self.btn_epochs.setFocusPolicy(Qt.NoFocus)
        self.btn_epochs.clicked.connect(self._apply_epochs)
        erow = QHBoxLayout()
        erow.addWidget(self.sp_epochs, 1)
        erow.addWidget(self.btn_epochs)
        self.lbl_epoch = QLabel()
        self.lbl_epoch.setStyleSheet("color:#888;")
        for sp in (self.sp_steps, self.sp_batch, self.sp_save_freq):
            sp.valueChanged.connect(self._update_epoch_info)
        self.ed_extra = QLineEdit()
        self.ed_extra.setPlaceholderText("예: --policy.chunk_size=50 --seed=7 (맨 뒤에 붙어 위 값을 덮어씀)")
        pf.addRow("정책", polrow)
        pf.addRow("GPU 번호", self.sp_gpu)
        pf.addRow("학습 step", self.sp_steps)
        pf.addRow("batch size", self.sp_batch)
        pf.addRow("epoch → step", erow)
        pf.addRow("", self.lbl_epoch)
        pf.addRow("데이터 로더 worker", self.sp_workers)
        pf.addRow("로그 주기 (step)", self.sp_log_freq)
        pf.addRow("체크포인트 주기 (step)", self.sp_save_freq)
        pf.addRow("", self.ck_aug)
        pf.addRow("", self.ck_wandb)
        pf.addRow("추가 인자", self.ed_extra)
        left.addWidget(pbox)
        self.train_box = pbox

        xbox = QGroupBox("실행")
        xg = QGridLayout(xbox)
        self.btn_train = QPushButton("학습 시작")
        self.cb_runs = QComboBox()
        self.cb_runs.setToolTip("체크포인트가 남은 학습 (최신순)")
        self.btn_train_resume = QPushButton("이어서 학습")
        self.btn_train_stop = QPushButton("중지")
        self.btn_train_open = QPushButton("결과 폴더 열기")
        self.btn_train.setMinimumHeight(48)
        self.btn_train.clicked.connect(self._start_train)
        self.btn_train_resume.clicked.connect(self._resume_train)
        self.btn_train_stop.clicked.connect(self.trainer.stop)
        self.btn_train_open.clicked.connect(self._open_train_dir)
        for b in (self.btn_train, self.btn_train_resume, self.btn_train_stop, self.btn_train_open):
            b.setFocusPolicy(Qt.NoFocus)
        xg.addWidget(self.btn_train, 0, 0, 1, 2)
        xg.addWidget(self.cb_runs, 1, 0)
        xg.addWidget(self.btn_train_resume, 1, 1)
        xg.addWidget(self.btn_train_stop, 2, 0)
        xg.addWidget(self.btn_train_open, 2, 1)
        note = QLabel("학습은 Docker 컨테이너에서 돌아 대시보드를 꺼도 계속되고, 다시 열면 이어서 표시합니다.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        xg.addWidget(note, 3, 0, 1, 2)
        left.addWidget(xbox)
        left.addStretch()

        right = QVBoxLayout()
        h.addLayout(right, 2)
        gbox = QGroupBox("진행")
        gv = QVBoxLayout(gbox)
        self.pb_train = QProgressBar()
        self.pb_train.setFormat("%v / %m step (%p%)")
        self.lbl_train_stat = QLabel("대기")
        self.lbl_train_stat.setStyleSheet("font-family:monospace;font-size:13px;")
        self.lbl_train_out = QLabel()
        self.lbl_train_out.setWordWrap(True)
        self.lbl_train_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_train_tqdm = QLabel()
        self.lbl_train_tqdm.setStyleSheet("font-family:monospace;color:#888;")
        gv.addWidget(self.pb_train)
        gv.addWidget(self.lbl_train_stat)
        gv.addWidget(self.lbl_train_tqdm)
        gv.addWidget(self.lbl_train_out)
        right.addWidget(gbox)
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setFocusPolicy(Qt.ClickFocus)
        self.train_log.setMaximumBlockCount(2000)
        right.addWidget(QLabel("학습 로그 (첫 줄 = 같은 학습을 터미널에서 실행하는 명령)"))
        right.addWidget(self.train_log, 1)
        return root

    # ================================================================== settings io
    def _load_settings_to_ui(self):
        c = self.cfg
        self.ed_output.setText(c["session"]["output_dir"])
        self.ed_task_name.setText(c["session"]["task_name"])
        self.ed_task_text.setText(c["session"]["task_text"])
        r = c["robot"]
        self.ed_fport.setText(r["follower_port"])
        self.ed_fid.setText(r["follower_id"])
        self.ed_lport.setText(r["leader_port"])
        self.ed_lid.setText(r["leader_id"])
        for role, (ed, w, h, fp) in self.cam_edits.items():
            cc = c["cameras"][role]
            ed.setText(str(cc.get("index_or_path", "")))
            w.setValue(int(cc["width"]))
            h.setValue(int(cc["height"]))
            fp.setValue(int(cc["fps"]))
        self.sp_fps.setValue(int(c["record"]["fps"]))
        self.sp_status.setValue(float(c["record"]["status_hz"]))
        self.cb_vcodec.setCurrentText(c["record"]["vcodec"])
        m = c["motion"]
        self.sp_move.setValue(float(m["move_duration_s"]))
        self.sp_step.setValue(float(m["max_step"]))
        self.ed_hub_user.setText(c["hub"]["user"])
        self.ck_private.setChecked(bool(c["hub"]["private"]))
        self.ed_fk_signs.setText(", ".join(str(int(s)) for s in c["fk"]["signs"]))
        self.ed_fk_offsets.setText(", ".join(f"{o:g}" for o in c["fk"]["offsets_deg"]))
        t = c["train"]
        # Older config.yaml kept these once for every policy; they now belong to the saved policy.
        legacy = {k: t.pop(k) for k in ("image_aug", "extra_args") if k in t}
        if legacy:
            saved = (t.get("params") or {}).get(t["policy"]) or {}
            t["params"] = {**(t.get("params") or {}), t["policy"]: {**legacy, **saved}}
        self.cb_policy.blockSignals(True)
        self.cb_policy.setCurrentIndex(max(self.cb_policy.findData(t["policy"]), 0))
        self.cb_policy.blockSignals(False)
        self.sp_gpu.setValue(int(t["gpu"]))
        self.ck_wandb.setChecked(bool(t["wandb"]))
        self.ed_holdout.setText(t["holdout_episodes"])
        self.ed_train_data.setText(t["dataset_root"])
        self._load_train_params()
        self._check_docker()
        self._update_train_data()

    def _collect_settings(self) -> dict:
        c = self.cfg
        c["session"]["output_dir"] = self.ed_output.text().strip() or "./output"
        c["session"]["task_name"] = self.ed_task_name.text().strip()
        c["session"]["task_text"] = self.last_task_text
        c["robot"].update(
            follower_port=self.ed_fport.text().strip(),
            follower_id=self.ed_fid.text().strip(),
            leader_port=self.ed_lport.text().strip(),
            leader_id=self.ed_lid.text().strip(),
        )
        for role, (ed, w, h, fp) in self.cam_edits.items():
            c["cameras"][role] = {
                "index_or_path": ed.text().strip(),
                "width": w.value(),
                "height": h.value(),
                "fps": fp.value(),
            }
        c["record"].update(fps=self.sp_fps.value(), status_hz=self.sp_status.value(), vcodec=self.cb_vcodec.currentText())
        c["motion"].update(
            move_duration_s=self.sp_move.value(),
            max_step=self.sp_step.value(),
        )
        c["hub"].update(user=self.ed_hub_user.text().strip(), private=self.ck_private.isChecked())
        signs = [int(float(x)) for x in self.ed_fk_signs.text().replace(" ", "").split(",") if x]
        offs = [float(x) for x in self.ed_fk_offsets.text().replace(" ", "").split(",") if x]
        if len(signs) != 5 or len(offs) != 5:
            raise ValueError("FK 부호/오프셋은 5개 값을 쉼표로 구분해 입력하세요.")
        c["fk"].update(signs=signs, offsets_deg=offs)
        params = dict(c["train"].get("params") or {})
        if self.train_policy:
            params[self.train_policy] = self._train_params()
        # Rebuilt rather than updated so keys of the old local-lerobot trainer drop out of config.yaml.
        c["train"] = {
            "omx_train_dir": c["train"]["omx_train_dir"],
            "dataset_root": self.ed_train_data.text().strip(),
            "policy": self._policy(),
            "gpu": self.sp_gpu.value(),
            "params": params,
            "wandb": self.ck_wandb.isChecked(),
            "holdout_episodes": self.ed_holdout.text().strip(),
        }
        return c

    def _save_settings(self) -> bool:
        try:
            self._collect_settings()
        except ValueError as e:
            QMessageBox.warning(self, "설정 오류", str(e))
            return False
        save_config(self.cfg)
        self._log("설정 저장 완료")
        if self.session and not self.ctrl.running:
            self._connect_cameras()
        return True

    # ================================================================== actions
    def _browse_output(self):
        start = str(self._resolve(self.ed_output.text() or "./output"))
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", start)
        if d:
            self.ed_output.setText(d)

    @staticmethod
    def _resolve(p: str) -> Path:
        path = Path(p).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path)

    def _start_session(self):
        name = self.ed_task_name.text().strip()
        if not name or any(ch in name for ch in r'/\ '):
            QMessageBox.warning(self, "태스크명", "태스크명을 공백·슬래시 없이 입력하세요.")
            return
        if not self._save_settings():
            return
        task_dir = self._resolve(self.cfg["session"]["output_dir"]) / name
        task_dir.mkdir(parents=True, exist_ok=True)
        self.session = {"task_dir": str(task_dir), "task_name": name}
        self.counts = Recorder.disk_counts(task_dir)
        self.lbl_session.setText(f"세션: {task_dir}")
        self._log(f"세션 시작: {task_dir} (기존 Success {self.counts['success']} / Fail {self.counts['fail']})")
        self._update_train_data()
        self._connect_cameras()
        self._refresh()

    def _connect_cameras(self):
        errs = self.cameras.connect(self.cfg["cameras"])
        for e in errs:
            self._log(e, error=True)
        paths = self.cameras.paths
        self._log(f"카메라 연결: {', '.join(f'{r}({p})' for r, p in paths.items()) if paths else '없음'}")

    def _find_cameras(self):
        if self.ctrl.running:
            return
        self.cameras.disconnect()
        cur = {r: {"index_or_path": self.cam_edits[r][0].text()} for r in CAMERA_ROLES}
        dlg = CameraPickerDialog(cur, self)
        if dlg.exec():
            for role in CAMERA_ROLES:
                self.cam_edits[role][0].setText(str(dlg.result_map.get(role, "")))
            self._save_settings()
        if self.session:
            self._connect_cameras()

    def _bringup(self):
        if not self.session or self.ctrl.running:
            return
        if not self._save_settings():
            return
        if self.trainer.running:
            msg = "학습이 진행 중입니다. 학습과 녹화를 함께 하면 녹화 주기가 흔들릴 수 있습니다. 계속할까요?"
            if QMessageBox.question(self, "학습 중", msg) != QMessageBox.Yes:
                return
        if not self.cameras.roles:
            if QMessageBox.question(self, "카메라 없음", "연결된 카메라가 없습니다. 영상 없이 진행할까요?") != QMessageBox.Yes:
                return
        self._log("BringUp 시작")
        self.ctrl.bringup(self.cfg, self.poses, self.session)

    def _servo_off(self):
        self.ctrl.servo_off()

    def _current_task_text(self) -> str:
        t = self.ed_task_text.text().strip()
        if t:
            self.last_task_text = t
        else:
            self.ed_task_text.setText(self.last_task_text)
        return self.last_task_text

    def _record(self):
        if not self.btn_record.isEnabled():
            return
        task = self._current_task_text()
        if not task:
            QMessageBox.warning(self, "태스크 문장", "에피소드 태스크 문장을 입력하세요.")
            return
        self.cfg["session"]["task_text"] = task
        save_config(self.cfg)
        self.ctrl.start_record(task)

    def _end(self, outcome: str):
        btn = {"success": self.btn_success, "fail": self.btn_fail, "discard": self.btn_discard}[outcome]
        if btn.isEnabled():
            self.ctrl.end_episode(outcome)

    def _check_login(self):
        name = hub.whoami()
        if name is None:
            token, ok = QInputDialog.getText(self, "HF 로그인", "Hugging Face 토큰 (write 권한):", QLineEdit.Password)
            if not ok or not token.strip():
                return
            try:
                name = hub.login(token.strip())
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "로그인 실패", str(e))
                return
        if name:
            self.ed_hub_user.setText(name)
            self._save_settings()
            self._log(f"HF 로그인: {name}")

    def _upload(self):
        if not self.session or self.uploading:
            return
        user = self.ed_hub_user.text().strip() or hub.whoami()
        if not user:
            QMessageBox.warning(self, "HF Hub", "설정 탭에서 '로그인 확인'을 먼저 하세요.")
            return
        private = self.ck_private.isChecked()
        msg = f"{user}/{self.session['task_name']}_success, _fail 로 업로드합니다. ({'비공개' if private else '공개'})"
        if QMessageBox.question(self, "HF Hub 업로드", msg) != QMessageBox.Yes:
            return
        self.uploading = True
        sess = dict(self.session)

        def work():
            try:
                pushed = hub.push_task(sess["task_dir"], sess["task_name"], user, private, log=lambda s: self.ui_events.put(("log", s)))
                self.ui_events.put(("log", f"[HF] 완료: {', '.join(pushed) if pushed else '업로드할 데이터 없음'}"))
            except Exception as e:  # noqa: BLE001
                self.ui_events.put(("error", f"[HF] 업로드 실패: {e}"))
            finally:
                self.ui_events.put(("upload_done", None))

        threading.Thread(target=work, daemon=True).start()

    # ================================================================== training (omx_train/<policy>/train.sh)
    def _omx_dir(self) -> Path:
        p = Path(self.cfg["train"]["omx_train_dir"]).expanduser()
        return (p if p.is_absolute() else APP_DIR / p).resolve()

    def _policy(self) -> str:
        return self.cb_policy.currentData() or "act"

    def _param_spins(self) -> dict:
        return {
            "steps": self.sp_steps,
            "batch_size": self.sp_batch,
            "save_freq": self.sp_save_freq,
            "log_freq": self.sp_log_freq,
            "num_workers": self.sp_workers,
        }

    def _train_params(self) -> dict:
        """Values kept per policy: an extra argument of one policy may not exist in the other."""
        params = {k: sp.value() for k, sp in self._param_spins().items()}
        params.update(image_aug=self.ck_aug.isChecked(), extra_args=self.ed_extra.text().strip())
        return params

    def _script_defaults(self, policy: str) -> dict:
        try:
            return trainer.script_defaults(trainer.train_script(self.trainer.omx_dir, policy))
        except OSError:
            return {}

    def _load_train_params(self):
        """Show the saved values of the selected policy, or train.sh's when there are none yet."""
        policy = self._policy()
        self.train_policy = policy
        saved = (self.cfg["train"].get("params") or {}).get(policy) or {}
        values = {**self._script_defaults(policy), **saved}
        for k, sp in self._param_spins().items():
            if k in values:
                sp.setValue(int(values[k]))
        self.ck_aug.setChecked(bool(saved.get("image_aug", False)))
        self.ed_extra.setText(saved.get("extra_args", ""))
        self._refresh_runs()

    def _policy_changed(self, _index: int):
        if self.train_policy:
            self.cfg["train"].setdefault("params", {})[self.train_policy] = self._train_params()
        self._load_train_params()
        self._check_docker()
        self._update_train_data()

    def _reset_train_params(self):
        for k, v in self._script_defaults(self._policy()).items():
            self._param_spins()[k].setValue(int(v))

    def _check_docker(self):
        omx = self.trainer.omx_dir
        if not trainer.train_script(omx, self._policy()).exists():
            self.docker_ok = self.image_ok = False
            self.lbl_docker.setText(f"omx_train을 찾을 수 없습니다: {omx} (config.yaml의 train.omx_train_dir)")
            return
        image = trainer.image_name(omx, self._policy())
        self.docker_ok, self.image_ok, msg = trainer.docker_status(image)
        self.lbl_docker.setText(f"{msg}\n폴더: {trainer.policy_dir(omx, self._policy())}")
        self.lbl_docker.setStyleSheet("" if self.image_ok else "color:#ef6c00;")

    def _build_image(self):
        if self.trainer.busy:
            return
        self.train_log.clear()
        self._log(f"이미지 빌드 시작: {trainer.image_name(self.trainer.omx_dir, self._policy())}")
        self.lbl_train_stat.setText("이미지 빌드 중...")
        self.trainer.build_image(self._policy())

    def _refresh_runs(self):
        self.cb_runs.clear()
        for run in trainer.list_runs(self.trainer.omx_dir, self._policy()):
            self.cb_runs.addItem(run.name, str(run))

    def _train_data_root(self) -> Path | None:
        text = self.ed_train_data.text().strip()
        if text:
            return self._resolve(text)
        if self.session:
            return trainer.dataset_root(Path(self.session["task_dir"]))
        return None

    def _train_task_name(self, root: Path) -> str:
        return self.session["task_name"] if self.session and not self.ed_train_data.text().strip() else root.parent.name

    def _update_train_data(self):
        root = self._train_data_root()
        self.train_root = root
        # The full default path is too long for the field, so it goes in the tooltip; the label below shows it too.
        if self.session:
            default = str(trainer.dataset_root(Path(self.session["task_dir"])))
        else:
            default = "세션 시작 후 <저장 경로>/<태스크명>/success"
        self.ed_train_data.setPlaceholderText("비우면 세션 데이터 사용")
        self.ed_train_data.setToolTip(f"LeRobot 데이터셋 폴더 (meta/info.json이 있는 폴더)\n비우면: {default}")
        custom = bool(self.ed_train_data.text().strip())
        head = f"{'지정 경로' if custom else '기본 경로(세션)'}: {root}"
        self.train_eps = trainer.episode_count(root) if root else 0
        self.train_lengths, self.train_episodes, self.train_holdout, self.train_split_error = {}, None, [], ""
        if root is None:
            self.lbl_train_data.setText("데이터 폴더를 지정하거나 대시보드에서 세션을 시작하세요.")
        elif not (root / "meta" / "info.json").exists():
            self.lbl_train_data.setText(f"{head}\nLeRobot 데이터셋이 아닙니다 (meta/info.json 없음)")
        else:
            try:
                self.train_lengths = trainer.episode_lengths(root)
            except Exception as e:  # noqa: BLE001
                self._log(f"에피소드 길이를 읽지 못했습니다: {e}", error=True)
            split = f"에피소드 {self.train_eps}개"
            try:
                self.train_holdout = trainer.parse_episode_list(self.ed_holdout.text(), self.train_eps)
            except ValueError as e:
                self.train_split_error = str(e)
            if self.train_split_error:
                split += f"   ·   제외 목록 오류: {self.train_split_error}"
            elif self.train_holdout:
                self.train_episodes = [i for i in range(self.train_eps) if i not in self.train_holdout]
                shown = ", ".join(map(str, self.train_holdout))
                split = f"학습 {len(self.train_episodes)}개 / 제외 {len(self.train_holdout)}개 ({shown})"
                if not self.train_episodes:
                    self.train_split_error = "모든 에피소드를 제외했습니다"
            out = trainer.outputs_dir(self.trainer.omx_dir, self._policy())
            job = f"{self._train_task_name(root)}_{self._policy()}_<시각>"
            self.lbl_train_data.setText(f"{head}\n{split}\n결과 저장: {out}/{job}/")
        self._update_epoch_info()

    def _train_frames(self) -> int:
        eps = self.train_episodes if self.train_episodes is not None else range(self.train_eps)
        return sum(self.train_lengths.get(i, 0) for i in eps)

    def _update_epoch_info(self):
        spe = trainer.steps_per_epoch(self._train_frames(), self.sp_batch.value())
        self.btn_epochs.setEnabled(spe > 0)
        if spe == 0:
            self.lbl_epoch.setText("epoch 환산: 데이터가 없습니다")
            return
        steps, save = self.sp_steps.value(), self.sp_save_freq.value()
        # lerobot saves every save_freq steps and always at the final step.
        ckpts = steps // save + (1 if steps % save else 0)
        self.lbl_epoch.setText(
            f"≈ {steps / spe:.1f} epoch (1 epoch = {spe} step, {self._train_frames()} 프레임) · 체크포인트 {ckpts}개"
        )

    def _apply_epochs(self):
        spe = trainer.steps_per_epoch(self._train_frames(), self.sp_batch.value())
        if spe:
            self.sp_steps.setValue(max(self.sp_steps.minimum(), round(self.sp_epochs.value() * spe)))

    def _browse_train_data(self):
        start = self.train_root or self._resolve(self.ed_output.text() or "./output")
        d = QFileDialog.getExistingDirectory(self, "학습 데이터 폴더 선택", str(start))
        if d:
            self.ed_train_data.setText(d)
            self._update_train_data()

    def _reset_train_data(self):
        self.ed_train_data.clear()
        self._update_train_data()

    def _train_preflight(self) -> list[str] | None:
        """Extra arguments when a run may start now, else None (after telling the user why)."""
        if self.trainer.busy:
            return None
        s = self.ctrl.snapshot()
        if s.get("recording") or s.get("pending") or self.recorder.busy:
            QMessageBox.warning(self, "학습", "녹화·저장이 끝난 뒤에 학습을 시작하세요.")
            return None
        if not self._save_settings():
            return None
        try:
            return trainer.split_extra_args(self.ed_extra.text())
        except ValueError as e:
            QMessageBox.warning(self, "추가 인자", str(e))
            return None

    def _start_train(self):
        extra = self._train_preflight()
        if extra is None:
            return
        self._update_train_data()
        root = self.train_root
        if root is None:
            return
        if self.train_eps == 0:
            QMessageBox.warning(self, "학습", f"{root}\n에 학습할 에피소드가 없습니다.")
            return
        if self.train_split_error:
            QMessageBox.warning(self, "평가용 제외 에피소드", self.train_split_error)
            return
        omx, policy = self.trainer.omx_dir, self._policy()
        params = self._train_params()
        args = trainer.overrides(params, self.ck_aug.isChecked(), self.ck_wandb.isChecked()) + extra
        job = trainer.job_name(self._train_task_name(root), policy)
        argv, env = trainer.build_train(omx, policy, self.sp_gpu.value(), root, job, self.train_episodes, args)
        steps = trainer.last_override(args, "steps")
        total = int(steps) if steps and steps.isdigit() else params["steps"]
        meta = {
            "policy": policy,
            "job": job,
            "dataset_root": str(root),
            "total_episodes": self.train_eps,
            "holdout_episodes": self.train_holdout,
            "train_episodes": self.train_episodes,
            "steps": total,
            "command": trainer.shell_line(argv, env, omx),
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        meta_path = trainer.run_meta_path(omx, policy, job)
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        except OSError as e:
            QMessageBox.warning(self, "학습", f"실행 정보를 저장하지 못했습니다: {e}")
            return
        n = len(self.train_episodes) if self.train_episodes is not None else self.train_eps
        self._log(f"학습 시작: {trainer.POLICIES[policy]} · {root} ({n}개 에피소드) → {job}")
        self._begin_progress(total)
        self.trainer.start(argv, env, policy)

    def _resume_train(self):
        extra = self._train_preflight()
        run = self.cb_runs.currentData()
        if extra is None or not run:
            return
        run = Path(run)
        omx, policy = self.trainer.omx_dir, self._policy()
        argv, env = trainer.build_resume(omx, policy, self.sp_gpu.value(), run, extra)
        steps = trainer.last_override(extra, "steps")
        try:
            total = int(steps) if steps else int(json.loads(trainer.resume_config(run).read_text())["steps"])
        except (OSError, ValueError, KeyError):
            total = 0
        self._log(f"이어서 학습: {run}")
        self._begin_progress(total)
        self.trainer.start(argv, env, policy)

    def _begin_progress(self, total: int):
        self.train_total = int(total)
        # range (0, 0) = busy bar when the total step count is unknown
        self.pb_train.setRange(0, max(self.train_total, 0))
        self.pb_train.setValue(0)
        self.lbl_train_stat.setText("시작 중...")
        self.lbl_train_tqdm.clear()
        self.train_log.clear()

    def _attach_running_train(self):
        """Pick up a training container started before the dashboard was (re)opened."""
        attached = None
        for name, state in trainer.train_containers():
            job = name[len(trainer.CONTAINER_PREFIX):]
            policy = trainer.find_job(self.trainer.omx_dir, job)
            if policy is None:
                continue
            if attached is None:
                self.cb_policy.setCurrentIndex(self.cb_policy.findData(policy))
                meta = trainer.read_meta(self.trainer.omx_dir, policy, job)
                self._begin_progress(int(meta.get("steps") or 0))
                if self.trainer.attach(name):
                    attached = name
                    self._log(f"학습 컨테이너에 다시 연결: {name} ({state})")
            elif state == "running":
                self._log(f"다른 학습도 실행 중입니다: {name} (docker logs -f {name})")

    def _open_train_dir(self):
        cands = [self.trainer.out_dir, trainer.outputs_dir(self.trainer.omx_dir, self._policy())]
        d = next((p for p in cands if p and p.exists()), None)
        if d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ================================================================== loop
    def _tick(self):
        for q in (self.ctrl.events, self.ui_events, self.trainer.events):
            while True:
                try:
                    kind, payload = q.get_nowait()
                except queue.Empty:
                    break
                self._handle_event(kind, payload)
        for role, lbl in self.cam_labels.items():
            img = self.cameras.latest(role)
            if img is not None:
                lbl.setPixmap(to_pixmap(img, lbl.width(), lbl.height()))
            elif role not in self.cameras.roles:
                lbl.clear()
                lbl.setText("카메라 없음")
        self._refresh()

    def _handle_event(self, kind, payload):
        if kind == "log":
            self._log(payload)
        elif kind == "error":
            self._log(payload, error=True)
        elif kind == "counts":
            self.counts = payload
        elif kind == "saved":
            o = payload["outcome"]
            if o == "discard":
                self._log(f"Discard ({payload['frames']} 프레임 폐기)")
            else:
                self._log(f"{o.upper()} 저장 완료: episode {payload['episode_index']} ({payload['frames']} 프레임)")
            if self.recorder.is_open:
                self.counts = self.recorder.counts()
            self._update_train_data()
        elif kind == "record_started":
            self._log(f"녹화 시작: \"{self.last_task_text}\"")
        elif kind == "pose_captured":
            which, pose = payload
            self.poses[which] = pose
            save_poses(self.poses)
            self._log(f"{which.capitalize()} 자세 저장: " + ", ".join(f"{m}={v:.1f}" for m, v in pose.items()))
        elif kind == "servo_off_done":
            self._log("Servo OFF 완료")
            if self.session:
                self.counts = Recorder.disk_counts(Path(self.session["task_dir"]))
            self._update_train_data()
        elif kind == "upload_done":
            self.uploading = False
        elif kind == "train_log":
            self.train_log.appendPlainText(payload)
        elif kind == "train_tqdm":
            self.lbl_train_tqdm.setText(payload)
        elif kind == "train_progress":
            if self.train_total > 0:
                self.pb_train.setValue(min(payload["step"], self.pb_train.maximum()))
            ep = f"   epoch {payload['epoch']:.2f}" if "epoch" in payload else ""
            self.lbl_train_stat.setText(f"step {payload['step']}   loss {payload['loss']:.4f}{ep}")
        elif kind == "train_done":
            ok = payload == 0
            if ok:
                self._log("학습 완료")
            elif self.trainer.stop_requested:
                self._log("학습 중지됨")
            else:
                self._log(f"학습 비정상 종료 (코드 {payload}) — 학습 탭 로그를 확인하세요", error=True)
            head = "완료" if ok else ("중지됨" if self.trainer.stop_requested else "오류")
            self.lbl_train_stat.setText(f"{head}   {self.lbl_train_stat.text()}")
            self.pb_train.setRange(0, max(self.train_total, 1))
            if ok:
                self.pb_train.setValue(self.pb_train.maximum())
            self._refresh_runs()
        elif kind == "build_done":
            if payload == 0:
                self._log("학습 이미지 빌드 완료")
                self.lbl_train_stat.setText("이미지 빌드 완료")
            else:
                self._log(f"학습 이미지 빌드 실패 (코드 {payload}) — 학습 탭 로그를 확인하세요", error=True)
                self.lbl_train_stat.setText("이미지 빌드 실패")
            self._check_docker()

    def _refresh(self):
        s = self.ctrl.snapshot()
        mode = s.get("mode", Mode.DISCONNECTED)
        running = self.ctrl.running
        recording = s.get("recording", False)
        pending = s.get("pending", False)
        saving = self.recorder.busy
        active = running and mode in (Mode.MOVING, Mode.HOLD, Mode.TELEOP, Mode.FAULT)

        self.btn_session.setEnabled(not running)
        self.ed_output.setEnabled(not running)
        self.ed_task_name.setEnabled(not running)
        for b in self.settings_boxes:
            b.setEnabled(not running)
        self.btn_bringup.setEnabled(bool(self.session) and not running)
        self.btn_servo_off.setEnabled(active and not recording and mode != Mode.MOVING)
        # Poses are read from the leader, so it must be free to move (TELEOP).
        pose_ok = running and mode == Mode.TELEOP and not recording and not pending
        self.btn_init.setEnabled(pose_ok)
        self.btn_rest.setEnabled(pose_ok)
        self.btn_free.setEnabled(running and mode == Mode.HOLD and not recording and not pending)
        can_record = (
            running
            and mode in (Mode.HOLD, Mode.TELEOP)
            and bool(self.poses.get("init"))
            and not recording
            and not pending
            and not saving
        )
        self.btn_record.setEnabled(can_record)
        self.btn_success.setEnabled(recording or pending)
        self.btn_fail.setEnabled(recording or pending)
        self.btn_discard.setEnabled(recording or pending)
        self.btn_upload.setEnabled(bool(self.session) and not self.uploading and not recording and not pending and not saving)

        training = self.trainer.running
        busy = self.trainer.busy
        can_train = not busy and not recording and not pending and not saving and self.docker_ok and self.image_ok
        self.train_box.setEnabled(not busy)
        self.train_data_box.setEnabled(not busy)
        self.btn_build.setEnabled(self.docker_ok and not busy)
        self.btn_train.setEnabled(can_train and self.train_eps > 0 and not self.train_split_error)
        self.btn_train.setStyleSheet(STYLE_GREEN if self.btn_train.isEnabled() else "")
        self.cb_runs.setEnabled(not busy)
        self.btn_train_resume.setEnabled(can_train and self.cb_runs.count() > 0)
        stoppable = self.trainer.phase in ("follow", "build")
        self.btn_train_stop.setEnabled(stoppable)
        self.btn_train_stop.setStyleSheet(STYLE_RED if stoppable else "")
        if training:
            t = int(self.trainer.elapsed())
            self.lbl_train_out.setText(f"출력: {self.trainer.out_dir}\n경과 {t // 3600:d}:{t // 60 % 60:02d}:{t % 60:02d}")

        if recording:
            t = s.get("rec_seconds", 0.0)
            self.btn_record.setText(f"● 녹화 중  {int(t // 60):02d}:{t % 60:04.1f}")
            self.btn_record.setStyleSheet(STYLE_RED)
        else:
            self.btn_record.setText("녹화  [Space]")
            self.btn_record.setStyleSheet(STYLE_GREEN if can_record else "")
        self.btn_success.setStyleSheet(STYLE_BLUE if (recording or pending) else "")
        self.btn_fail.setStyleSheet(STYLE_ORANGE if (recording or pending) else "")
        self.btn_discard.setStyleSheet(STYLE_GRAY if (recording or pending) else "")
        self.btn_bringup.setStyleSheet(STYLE_GREEN if self.btn_bringup.isEnabled() else "")

        # banner
        if not self.session:
            txt, sty = "세션을 시작하세요", STYLE_GRAY
        elif not running:
            txt, sty = "BringUp 대기", STYLE_GRAY
        elif mode == Mode.CONNECTING:
            txt, sty = "연결 중...", STYLE_BLUE
        elif mode == Mode.FAULT:
            txt, sty = "FAULT — 통신 오류", STYLE_RED
        elif mode == Mode.STOPPING:
            txt, sty = "종료 중 — 두 팔을 받쳐 주세요", STYLE_ORANGE
        elif recording:
            txt, sty = f"● 녹화 중  ({s.get('rec_frames', 0)} 프레임)", STYLE_RED
        elif pending:
            txt, sty = "결과를 선택하세요 (S / F / D)", STYLE_ORANGE
        elif mode == Mode.MOVING:
            txt, sty = "자세 이동 중...", STYLE_BLUE
        elif mode == Mode.HOLD:
            if saving:
                txt, sty = "Init 자세 · 에피소드 저장 중...", STYLE_BLUE
            else:
                txt, sty = "Init 자세 · 리더암을 잡고 녹화 [Space]", STYLE_GREEN
        elif not self.poses.get("init"):
            txt, sty = "원격조종 중 · 리더암으로 자세를 잡고 Init 저장", STYLE_ORANGE
        elif saving:
            txt, sty = "원격조종 중 · 에피소드 저장 중...", STYLE_BLUE
        else:
            txt, sty = "원격조종 중 · 녹화를 누르면 Init으로 이동 후 시작", STYLE_GREEN
        self.lbl_banner.setText(txt)
        self.lbl_banner.setStyleSheet(sty)

        self.lbl_counts.setText(f"Success {self.counts.get('success', 0)}   ·   Fail {self.counts.get('fail', 0)}")
        self.lbl_loop.setText(f"루프 {s.get('loop_hz', 0):.1f} Hz" if running else "")
        self.lbl_pose.setText(
            f"Init: {'저장됨' if self.poses.get('init') else '미설정'}   ·   Rest: {'저장됨' if self.poses.get('rest') else '미설정(Init 사용)'}"
        )

        ee = s.get("ee")
        if running and ee:
            self.lbl_ee.setText(
                f"EE  x {ee[0]*1000:7.1f} mm  y {ee[1]*1000:7.1f} mm  z {ee[2]*1000:7.1f} mm   "
                f"roll {ee[3]:+.2f}  pitch {ee[4]:+.2f}  yaw {ee[5]:+.2f} rad"
            )
        else:
            self.lbl_ee.setText("EE  -")

        lead, fol = s.get("leader"), s.get("follower")
        if running and lead and fol:
            for r, m in enumerate(MOTORS):
                d = lead[m] - fol[m]
                vals = [
                    f"{lead[m]:.1f}",
                    f"{fol[m]:.1f}",
                    f"{d:+.1f}",
                    f"{s['velocity'][m]:.0f}",
                    f"{s['current'][m]:.0f}",
                    f"{s['temperature'][m]:.0f}",
                    f"{s['voltage'][m]:.1f}",
                ]
                for c, v in enumerate(vals):
                    self.table.item(r, c).setText(v)
        else:
            for r in range(len(MOTORS)):
                for c in range(len(COLS)):
                    self.table.item(r, c).setText("-")

    # ================================================================== misc
    def _log(self, msg: str, error: bool = False):
        from time import strftime

        line = f"[{strftime('%H:%M:%S')}] {'[오류] ' if error else ''}{msg}"
        self.log.appendPlainText(line)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and not event.isAutoRepeat() and self.isActiveWindow():
            key = event.key()
            focus = QApplication.focusWidget()
            editing = isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit)) and not (
                isinstance(focus, QPlainTextEdit) and focus.isReadOnly()
            )
            if key == Qt.Key_Escape and focus is not None:
                focus.clearFocus()
                return True
            if not editing:
                if key == Qt.Key_Space:
                    self._record()
                    return True
                if key == Qt.Key_S:
                    self._end("success")
                    return True
                if key == Qt.Key_F:
                    self._end("fail")
                    return True
                if key == Qt.Key_D:
                    self._end("discard")
                    return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        s = self.ctrl.snapshot()
        if self.trainer.running:
            msg = "학습은 Docker 컨테이너에서 계속 진행됩니다. 다시 열면 진행 상황에 다시 연결합니다. 종료할까요?"
            if QMessageBox.question(self, "종료", msg) != QMessageBox.Yes:
                event.ignore()
                return
        elif self.trainer.busy:
            if QMessageBox.question(self, "종료", "학습 이미지를 빌드하는 중입니다. 빌드를 중단하고 종료할까요?") != QMessageBox.Yes:
                event.ignore()
                return
        if self.ctrl.running:
            if s.get("recording") or s.get("pending"):
                QMessageBox.warning(self, "종료", "녹화 중이거나 결과 선택 대기 중입니다. 먼저 정리하세요.")
                event.ignore()
                return
            if QMessageBox.question(self, "종료", "Servo OFF 후 종료할까요?") != QMessageBox.Yes:
                event.ignore()
                return
            self._log("Servo OFF 후 종료 중...")
            QApplication.processEvents()
            self.ctrl.shutdown(timeout=60)
        self.trainer.detach()
        self.recorder.close()
        self.cameras.disconnect()
        try:
            self._collect_settings()
            save_config(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        event.accept()
