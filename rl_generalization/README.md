> 물리 모델 조사·미리보기: [v005](versions/v005/README.md). 기존 toy 학습 실행기는 CURRENT=v004 유지.

> 현재 버전: **v004** — 보상 역전 수정 및 실패 궤적 진단. [실행/변경 설명](versions/v004/README.md). v003 GPU 사용자 평가: 0/100 (toy).

# 신발 포장·물류로봇 적재: 위치 일반화 연구 자료

현재 버전: **v003**, 작성일 2026-11-18 (Asia/Seoul).

## 새 PC에서 시작

GPU 노트북(Linux/WSL2)에서 이 폴더로 이동한 뒤:

```bash
bash setup.sh --device cuda
source shell/aliases.bash
rl
rltrain --config configs/toy_sac.json --out runs/gpu_smoke --steps 400 --device cuda
```

CPU PC는 `--device cpu`. requirements 설치, rl 생성, 장치 확인, 테스트, bashrc 등록을 setup.sh가 수행한다. NVIDIA 드라이버는 사전 설치가 필요하다.

- [설치·단축 명령](ENVIRONMENT.md)
- [GitHub 새 브랜치 업로드 및 GPU 노트북 clone](GITHUB.md)
- [다른 PC의 Codex를 위한 인수인계](HANDOFF.md)
- [v003 코드 및 검증](versions/v003/README.md)

## 최신 구현

### 물리 시뮬레이터 경로

- NG 시행착오 영상: [v018 NG recorder](versions/v018/evidence/NG/README.md)
- 정상 모델 개선: [v019 contact-safe replay](versions/v019/README.md)
- v019 검증 결과: [latch_box/summary.json](versions/v019/evidence/latch_box/summary.json)
- 실제 영상 방향을 반영한 뚜껑 모델: [v020 robot-facing hinge](versions/v020/README.md)

v019는 손가락 충돌체 방향과 접촉 후 그리퍼·팔 정지를 보정했다. 최대 손가락-신발 침투는 0.928mm까지 줄었지만, 신발 상승은 2.06mm로 30mm 목표에 미달한다. 따라서 아직 파지 성공이나 실물 전이를 의미하지 않는다. 사용자가 직접 측정한 치수에는 약 0.1~0.2mm 오차가 있을 수 있으므로, 1mm는 넓은 진단 상한으로만 사용하고 0.3mm 이하를 더 엄격한 접촉 목표로 기록한다. 현재 v019는 0.3mm 목표를 통과하지 못했다.

이 경로는 `versions/v018`의 NG 녹화 코드와 `versions/v019`~`v020`의 정상 모델 개선 코드로 분리되어 있다. v020은 뚜껑을 `-π`로 초기화하면 OMX 방향으로 열린 상태가 되며, 신발 투입 뒤 `0`으로 닫는 staged controller는 아직 구현 전이다. 강화학습 학습은 현재 `versions/v002`~`v004`의 toy 환경에서만 실행되며, v020 물리 workcell을 RL 환경에 연결하는 작업은 다음 단계다.

- [rl 가상환경 및 Bash alias 설정](ENVIRONMENT.md)
- [v002 실행 안내](versions/v002/README.md)
- [수정 계획 및 정책 선택](versions/v002/docs/PLAN.md)
- [OMEN-11 운영 구성](versions/v002/docs/DEPLOYMENT_CONTEXT.md)
- [SAC 학습 코드](versions/v002/code/omx_rl/train.py)
- [지터 분석 도구](versions/v002/code/omx_rl/jitter.py)

기존 고정 위치 ACT는 다른 위치에서 파지 실패·지터가 발생하므로, 새 단일 신발 파지 정책을 먼저 개발한다. v003은 설치/장치 선택 개선이며 정책은 v002와 동일하다. 아래 링크는 보존한 v001 자료이며 당시 residual 우선 제안은 v002 계획으로 보완되었다.

범위는 로봇팔의 신발 집기→상자 투입→뚜껑 닫기→상자 파지·들기·운반→물류로봇 적재다. 휴먼 비전 연구는 범위 밖이다.

- [판단 및 개발 계획](versions/v001/docs/01_plan.md)
- [영상 관찰 기록](versions/v001/docs/02_video_review.md)
- [평가 설계](versions/v001/docs/03_evaluation.md)
- [자료 및 출처](versions/v001/docs/04_sources.md)
- [실험 설정 초안](versions/v001/configs/experiment_draft.json)
- [시도 기록 CSV](versions/v001/templates/trials.csv)
- [영상 요약 이미지](versions/v001/evidence/contact_sheet.jpg)
- [파일 해시 및 원본 영상 정보](versions/v001/manifest.json)

## 버전 관리 규칙

v001은 초기 자료 스냅샷이다. 후속 변경은 v002, v003 등 새 디렉터리에 복사해 수행하고 CHANGELOG.md에 변경 이유와 검증 상태를 남긴다. 각 버전은 manifest.json으로 파일 SHA-256을 고정한다. 원본 데이터·모델·영상은 수정하지 않는다.

이번에는 Git 저장소를 초기화하거나 원격 게시하지 않았다. 이 폴더의 버전 관리 방식은 버전별 디렉터리 + 변경 이력 + 해시 manifest다. 원본 영상은 복제하지 않고 경로·크기·해시로 참조한다. 공개할 때는 화면·주변 식별 정보와 공유 범위를 별도로 검토한다.

상태: v001은 자료 스냅샷. v002는 toy 학습 코드, v003은 자동 설치와 휴대성 개선이다. 실물 드라이버·좌표 추정·운영 번들 연결은 미구현이며 실물 성능은 측정하지 않았다.
