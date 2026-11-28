# Codex 인수인계 — 2026-11-18

새 PC의 Codex에게 이 파일, README.md, ENVIRONMENT.md를 먼저 읽도록 요청한다. 대화 전문이 아니라 결정/증거/미완료 작업을 담은 요약이다.

## 목적과 사용자 조건

PRD3 로봇팔: 신발 두 개 집기→상자 투입→뚜껑 닫기→닫힌 상자 집기·들기·운반→물류로봇 적재. 휴먼 비전 작업은 대상이 아니다. 대학원/학술/취업 포트폴리오를 위한 재현 가능한 비교가 목적.

기존 ACT는 고정된 한 배치의 시연만 학습. 사용자 보고 고정 배치 성공률 약 85% 이상(분모/작업별 여부 미확인). 다른 위치의 두 신발은 전혀 못 잡고 지터/헛집기 심함. 추가 다위치 모방 시연 수집은 어렵다. RL의 자율 실행 데이터 수집으로 확장하고 싶음. 물체 reset 가능 범위는 아직 확정 안 됨.

## 현재 결정

처음에는 ACT+residual을 추천했지만 실패 양상 확인 후 수정했다. 현재는 지터 진단→새 단일 신발 파지 SAC→위치 변화 확대→두 신발 순차 처리→기존 후속 작업 연결. 기존 ACT는 새 위치의 기본 접근 능력이 확인되지 않았으므로 작은 보정만으로 해결한다고 가정하지 않는다.

실물용 첫 후보는 상대 위치 기반 SAC와 제한된 말단 이동/그리퍼. 목표 파지점 추정, 카메라/로봇 좌표 보정, IK가 필요하며 아직 미구현. RGB 정책은 대안이지 현재 코드 구현이 아니다. 기존 ACT의 중간부터 자동 재개하는 handoff도 검증되지 않았다.

## 모델 및 운영

- Sungah/omx_shoebox_d, commit 8497dfe4fe4247f7c4a20b55b212912c4f69479a, models/act_shoebox_d_5000step; Yuzriha00/shoebox_D 50 episodes.
- Sungah/omx_move_in_success, commit d2a2cd1eedfbf29c8f409dc305fae2e75b8b3cf4, models/act_move_in_5000step; hfhfhf111/move_in_success 37 episodes.
- LeRobot 0.4.4, 6 state/action, top/wrist 640×480. chunk_size=100, 실제 n_action_steps는 실행기 확인 필요.
- OMEN-11/team11: arrange_shoe→ACT 정리→YOLO 성공 판정→ACT 싣기.
- ~/il_ws/bundles/omx_arrange_shoe_zc/v1/ 및 ~/il_ws/bundles/omx_load_zc/v1/가 운영 번들. HF에 없는 init_pose.json, success.json, YOLO, omx_fleet 필요.
- YOLO11 seg best_shoebox_D_rec_1116_2010.pt; closed_box(0), inside_box(1), shoe(2). top closed_box 3초 유지+팔 정지+끝 자세 근처.
- 정리 최대90초, 싣기35초(시간 종료이며 성공 판단 없음). move_in은 이름/원문 '밀기'와 달리 실제 들기·운반 포함.
- 영상 20261114_140159.mp4 약98초 시각 샘플 확인. 한 실행 예시이며 위치 일반화/85% 통계 근거가 아니다.

## 구현 상태

CURRENT=v004. v001 자료, v002 toy SAC/평가/지터 분석, v003 휴대 가능한 설치와 CPU/CUDA 선택.
ToyGraspEnv는 oracle 좌표·부착 상태와 임계값 파지를 쓰는 테스트 더블. 실제 로봇/URDF/IK/카메라/마찰 없음. 그 모델을 실물 배포하면 안 됨. hardware_contract.py는 Protocol만 있으며 드라이버 아님.

v002 테스트9개, 400-step SAC update/저장/재로드 완료. 독립 평가0/3이며 성능 검증 아님. v003 검증은 versions/v003/docs/VALIDATION.md 참조. venv와 패키지·학습 출력을 Git에 넣지 않음.

## 다음 작업

1. GPU 노트북에서 bash setup.sh --device cuda, CUDA 실제 연산 및 테스트 확인.
2. OMEN-11 운영 번들과 omx_fleet 실행 코드 확보. 센서/관절 단위와 제어 소유권 확인.
3. 고정/변경 배치의 raw/역정규화/실제 전송 목표, 실제 관절, timestamp, chunk 갱신 로그 수집. jitter.py 입력 스키마 사용.
4. 목표 파지점과 파지 성공을 실제로 얻을 방법 결정. YOLO bbox만으로 3D 파지점이라고 가정하지 않기.
5. 실물 환경 연결·reset·중단·제한·관측 누락 처리 후 온라인 수집. 무작위 toy 탐색을 실물에 그대로 쓰지 않기.
6. 고정/변경 위치·독립 시험 조건에서 무개입 성공률/인간 시간/실패 단계 비교. 작업A 종료 상태를 그대로 B에 연결해 별도 평가.

## 미실행

실물 RL, physics simulator, 새 시연 수집, 실제 성공률 개선 측정, YOLO 가중치 업로드, 운영번들 HF 공개는 하지 않았다. 파일/링크를 읽은 것과 모델 실행을 구분한다. 이전 버전 폴더의 해시 스냅샷은 수정하지 않고 새 버전을 추가한다.

## 2026-11-20 update
GPU access confirmed by user: team11@100.97.16.25 (not earlier 100.92.218.126). User ran v003 20k and evaluation 0/100. v004 preserves snapshots and adds reward correction, backward-compatible legacy evaluation and per-step diagnostics. See versions/v004/README.md and docs/VALIDATION.md. Remote v004 is not yet installed or executed.

Local v004 CPU seed0 20k evaluation: 0/100 task success; 100/100 ever-held, no releases, max object height <=0.03591 m vs required0.09m. Failure now lift_or_hold in this run. Do not claim learned task success. 34 tests pass.

ROS pytest entry-point pollution on remote host: run.sh test and bootstrap now set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1. Remote immediate workaround: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 bash run.sh test. No ROS dependency installation needed.

## Control audit
2026-11-20: control_audit/README.md documents static local driver path, 5 arm joints + gripper, default normalized position units, FK OMX-F reference and missing operational fleet/URDF. No robot connection. User copied remote v004 evaluations: seed0 81/100, seed1/2 0/100 (grasp failures); not real performance. Priority shifted to operational control/model verification, not more toy tuning.

Operating fleet copy audited: control_audit/FLEET_AUDIT.md. Runtime default relative limit10/ramp2 (not generic None), chain loading35s versus standalone90s; aggregate success can include unjudged load timeout. Bundle success.json and remote installed driver still needed. No hardware execution.

Bundle audit complete: control_audit/BUNDLE_AUDIT.md. 20 hashes verified, remote source driver identical to local candidate; normalized units corroborated by init poses. Default full-range calibration is not physical joint limits. Actual success.json3s/0.8 ratio/still0.7s verified. Missing patterns mostly alternate source paths, not necessarily missing dependencies.

Physical model audit v005: official OMX source commit d8344c0dbe7a00208d0301111523dde65efc174a. MuJoCo3.3.7 separate .venvs/omx_sim; 7qpos6actuators, 5 origins/axes match FK,500-step smoke finite/no warnings. Static candidate arm poses rendered; real zero/sign and gripper mapping unvalidated. CURRENT staysv004; v005 standalone preview/audit, not training. See versions/v005/README.md.

User workcell dimensions and gap2.5cm implemented in v006 static layout, config separates measured dimensions vs assumed placement. Both initial pose static checks compile/no contacts; props fixed proxies, not graspable. See versions/v006/README.md; old900 bare-robot batch is not scene verification. CURRENT staysv004.

v007: user confirms7x7cm retaining rim height1cm, box6x6 inside. Draft four walls, outer7/inner6/thickness0.5 interpretation not measured clearance. Both shoes robot-right; annotation raw values and residuals saved. Exact yellow reference edges and blue/red endpoints unresolved; positions estimates. Static scene compile/check/render passed, no new sweep launched.

v008 correction: user heights are toe0.7cm and central maximum2.5cm, NOT sole/heel blocks. Added smooth closed shoe envelope mesh, assumed rear2.2cm and toe+x. Extents/topology/scene compile/render checks passed. Static visual geometry only; no hollow upper or verified collision geometry.

v009: user reports compressible canvas upper/rigid sole, cardboard box. Visual Converse-like accents and lid seam added (noncolliding decorations). Physical compliance NOT implemented. Fleet driver uses CURRENT_POSITION but reads only Present_Position; no current/pressure logs found. See v009 README sensor audit.

v010: movable rigid shoes, hollow box and detachable free lid; static unmeasured logistics cylinder proxy. No manipulation controller or task training yet. 9 settling trials finite/no warnings. Portable /tmp/omx_workcell_v010.tar.gz prepared for detached remote tmux, 900 settling checks only. Lid topology and mobile dimensions pending; cloth/paper compliance not implemented.

v011: fixed rectangular logistics chassis + circular disk/64-wall rim. Photo diameter11.5cm; user14 interpreted inner tray floor height cm. Rim/chassis/parking provisional. Passive box drop within1mm after stiff contact assumption;9 settling checks no warnings. /tmp/omx_workcell_v011.tar.gz prepared; not remotely launched. No task controller/training.

2026-11-22: user remote logs confirm v011900/900 finite,0 warnings,38.325s, run20261120_234346_2738722. Added inspection/view_workcell.py rebuilding v009→v010→v011 into .local/inspection_v011, static GUI and three rendered views. Compiled geometry size assertions pass; dimensions.json records actual sizes. Box body6x6x5.5 excludes provisional separate cap, which increases total closed dimensions. Placement, grip calibration and materials not validated. No hardware accessed.

2026-11-22 v012 approach: simulation-only IK+actuator approach above both shoes.75/60deg selected;2.006/3.174mm tracked TCP errors, no collision threshold violations or warnings. Provisional TCP/gripper, axis-only wrist roll; no grasp/lift/RL yet. Viewer command in v012 README; per-shoe independent reset. Historical versions unchanged.

2026-11-22 v013: audited pinned HF original data/meta for shoebox50/73559 and move_in37/21284 (classification data are LFS pointers). Actual gripper current records present; fleet nonlogging is separate. All labels1 not independent success proof. Computed FK matches candidate tick mapping at link5 [0.09193,-0.0016,0], NOT v012 provisional TCP. Sample wrist joint range violations468/2477 arrange,39/728 load, elbow1 load. Do NOT blindly extend limits or map grip0..100 to sim0..1.745. Evidence/plots and kinematic arm-only viewer provided; no physical replay or hardware execution.

2026-11-22 v014: actual action physics replay incl moving gripper (uncalibrated offset). No attachments or repositioning. Defaultzero47.16 stops7.502s at negative gripper candidate; alternate46.8 sensitivity logged. Finger contact/lift detection implemented. Video ep0 top local available; contact sheet aligned0..45s shows recorded pickups. FK at first grasp differs from current nominal shoes by3.4–3.9cm; historical layout registration unresolved. Recorder FK source confirms offset. Do not call this successful grasp implementation or validated calibration.

2026-11-22 v015: reproduced untouched shoe twitching; rest test x excursion6mm, penetration6mm despite0warnings. Added flat sole-table contact proxy and masks preserving upper-arm collision, unchanged free joints/mass, no weld. Post1s stationary in4s test, transient penetration0.022mm. Existing900 finite/warning checks missed physical instability. New scene .local/stability_v015/scene; replay still uncalibrated/misaligned, not grasp-success claim.

2026-11-22 v016: alignment and mesh gap audits implemented. Experimental common TCP translation x+3.4972cm y-0.34276cm, residual0.315cm under shoe1→shoe0 hypothesis (not calibration). IK retargeted action trajectory, no object motion hacks. Horizontal only still0contact; extra z-6mm gives257 shoe1 contact steps/241 bilateral over12s, peak lift0.247mm, sustained lift FAILED. Evidence retained; no hardware/RL. User command README opens physical contact trial.

2026-11-23 v017: ran vertical depth sweep -12/-15/-18/-21mm. Apparent bilateral lift: 0,0.105,0.105,0.105m; hold0,1.448,3.626,3.622s. Every apparent lift had9.0-9.2mm finger-shoe collision penetration; validate_sweep rejects all under<=1mm criterion. Treat prior v017 lift as collision-model artifact until visual gripper mesh collision replaced with measured thin finger proxies.

2026-11-23 v018: replaced visual link6/link7 collision geoms with separate capsule finger proxies and replayed the retargeted demonstration. The `evidence_proxy` run shows apparent bilateral lift and 3.624s hold, but maximum proxy-to-shoe penetration is8.755mm (simulated normal peaks18.85/18.95N), so the lift is rejected as collision interpenetration. The additional low-proxy repeat has the same approximately9mm failure. No hardware, calibrated gripper zero/width, compliance, or grasp constraint was added. Measure the finger surfaces and registration before changing friction or training a grasp controller; do not transfer v018 offsets or forces to OMX.

2026-11-23 v019: added a provisional hinged `paper_lid` child body and a contact-triggered gripper latch replay. `evidence/compile_check.json` preserves the closed pose to8.7e-19m and verifies the hinge opens upward, but it does not validate the real lid hinge or cardboard compliance. In `evidence/latch_box_strict/summary.json`, shoe1 reached bilateral contact at7.504s, maximum finger-shoe penetration was0.928mm, and peak lift was2.060mm; shoe0 had no contact. The broad≤1mm diagnostic ceiling passes, but the stricter≤0.3mm target based on the user's0.1–0.2mm measurement uncertainty and the≥30mm lift criterion fail. This is a diagnostic, not a grasp or sim-to-real result. The v018 NG recorder files are retained in `versions/v018/evidence_proxy/` and `versions/v018/evidence/low_proxy_trial/` (`summary.json`, `force_summary.json`, `contact_diagnostics.csv`, `trajectory.csv`, and `states.npz` in each run).

2026-11-23 v020: built a robot-facing hinged-lid structural variant. The video reference has the lid initially open toward the OMX (negative-x direction); the hinge range is `-pi..0` rad (`0` closed, `-pi/2` vertical, `-pi` flat toward OMX). `evidence/compile_check.json` SHA-256 is `5b4bbcfcca041af88ce9499d329eedad6a2c834fbd1bb77d75ebe0a5e2ce3616`; it compiles with `nq=29`, preserves the closed pose with0m maximum error, and verifies the two hypothetical open poses. The model default `lid_hinge` qpos remains0rad (closed): an initial open qpos of `-pi` is not set, and the close stage/controller is not implemented. No open→insert→close→load sequence or hardware behavior is validated.
2026-11-23 video sequence audit: supplied `/home/noma/Downloads/20261114_140159.mp4` (SHA-256 `b1f9b97bbd49debb920ff48079cd2b8ef6c40342c998b074057cc401263bdb79`) was rechecked. The opening frame shows the cardboard lid already open toward the OMX, followed by shoe insertion, lid closing, and closed-box loading. `versions/v020/evidence/video_sequence_notes.json` records the sampled visual annotations. The shoebox parquet contains joint/action/auxiliary telemetry but no camera-video columns; it is used for motion replay, while the supplied MP4 is the visual source for lid orientation and task order.

2026-11-23 v021: added `versions/v021/code/sequence_check.py`. The top-camera opening pose is fitted provisionally at `lid_hinge=-2.70 rad` (about 20–30° above the fully-flat OMX-facing pose; not a calibrated hinge measurement). The headless smoke check executes the recorded order `open → pick/insert shoe0 → pick/insert shoe1 → close → lift → load stationary tray`: geometry/insertion and kinematic transport pass. Arm pickup/gripper contact remain explicitly `NOT_VALIDATED_ARM_GRASP`; this is not a learned-policy or hardware success claim. Evidence: `versions/v021/evidence/sequence_smoke_20261123_211000/summary.json`.

v021 arm connection diagnostic: `code/arm_replay_attempt.py` now drives the MuJoCo arm and gripper actuators from shoebox episode-0 actions with the provisional retarget shift. The 45-second replay is finite and reaches both shoes (`233/312` contact steps, `201/287` bilateral), but maximum penetration is `4.198 mm`, peak lift is only `1.771 mm`, and `grasp_success=false`. This confirms the arm was actually simulated; it does not validate a grasp because gripper zero, contact geometry/compliance, and attachment/lift criteria remain uncalibrated. Evidence: `versions/v021/evidence/arm_replay_45s/summary.json`.

v021 calibration sweep: 25 gripper-zero/vertical-offset trials found no combination meeting both `≤1 mm` penetration and `≥30 mm` lift. Best low-penetration case was `0.730 mm` penetration at only `0.577 mm` lift, with no bilateral hold. High-lift cases had multi-millimetre penetration and are collision artifacts. Evidence: `versions/v021/evidence/calibration_sweep_20261123_210633/summary.json`.

2026-11-23 v022: built a thin collision-proxy variant from v020, reducing each capsule radius from2mm to1mm while leaving the visual arm unchanged. Arm replay at `shift_z=-4mm` reduced maximum penetration to `0.864mm`, but peak lift was only `0.666mm`; the latch diagnostic recorded no bilateral latch and no30mm lift. Proxy thinning improves collision diagnostics but does not establish a grasp. See `versions/v022/README.md` and `evidence/latch_z0.004/summary.json`.
v022 also adds `code/preview_arm_replay.py`, an interactive MuJoCo viewer using the same arm/gripper commands as the quantitative replay, so each generated scene can be inspected visually before accepting metrics.

2026-11-23 v023: added `versions/v023/code/full_sequence_preview.py`. The
sequence now uses the explicit `shoebox_D` LeRobot median start
`[-12.97,-17.31,-0.85,43.59,-0.85,59.68]`, keeps the lid open toward the OMX,
replays the two shoe approach segments, forces normalized gripper value `0`
before lid closure, then resets to the separate `move_in_success` start
`[2.22,-34.99,14.68,40.37,1.0,58.93]` and carries the closed payload to the
stationary circular tray. Headless evidence is in
`versions/v023/evidence/full_sequence_headless/summary.json`. Arm commands are
replayed, but shoe insertion and box carry remain kinematic proxies; physical
grasp, cardboard compliance, force control and sim-to-real transfer are still
not validated.

2026-11-23 v024: added `versions/v024/code/contact_latch_explicit.py`, which
resets from the explicit shoebox_D median pose and stops the candidate gripper
target after bilateral finger contact. On the v022 thin-proxy scene with
`shift_z=-4mm`, shoe1 reached bilateral contact at7.548s with0.864mm maximum
penetration, but lift was only0.666mm; shoe0 had no bilateral contact. The
candidate condition (bilateral contact, penetration≤1mm, lift≥30mm) therefore
fails. This confirms that stopping the gripper reduces continued closing but
does not create a validated attachment. Evidence:
`versions/v024/evidence/contact_latch_explicit_test/summary.json`.

2026-11-23 v025: added `code/contact_sweep.py` to run nine explicit-pose
contact-latch trials over gripper zeros46.4/46.8/47.2 and vertical shifts
-2/-4/-6mm. All trials had zero valid candidates under bilateral contact,
penetration≤1mm, and lift≥30mm. The best lift was0.843mm (zero47.2, shift
-2mm), confirming that the current limitation is attachment/force modeling and
registration rather than a single poor gripper-zero choice. Evidence:
`versions/v025/evidence/contact_sweep_test/summary.json`.
