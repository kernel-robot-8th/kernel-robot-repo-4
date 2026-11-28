# v004 — 2026-11-20
- Preserve v003; add staged reward and legacy-compatible trajectory diagnostics.
- Add remote three-seed experiment and reward/reachability regression checks.

# 변경 이력

## v003 — 2026-11-18

- Linux/WSL2 설치 스크립트: rl 생성, torch CPU/CUDA 선택, 장치 연산/의존성/테스트 검증, bashrc 백업·중복 방지 등록.
- 절대경로 제거, CURRENT 기반 단축 명령 및 실행 wrapper.
- 학습·평가에 --device auto/cpu/cuda 추가.
- GitHub reinforcement-learning 브랜치 명령, export 도구, HANDOFF.md 추가. push는 수행하지 않음.
- 기존 스냅샷 유지. 새 CPU 설치 검증과 GPU 실측을 구분.

## 환경 설정 — 2026-11-18

- 프로젝트 `.venvs/rl`에 Python venv 생성, 프롬프트 `rl`.
- `shell/aliases.bash` 및 ENVIRONMENT.md 추가. v001/v002 스냅샷은 유지.
- ~/.bashrc는 수정하지 않음. 새 환경의 학습 패키지는 미설치.

## v002 — 2026-11-18

- 고정 위치 밖의 지터·헛집기 보고 반영: 새 단일 신발 파지 SAC 정책으로 계획 변경.
- toy Gymnasium 환경, SAC 학습/저장, 독립 평가, 지터 CSV 분석, 테스트 구현.
- OMEN-11 운영 번들·YOLO 성공 조건과 현재 미확보 자료 명시.
- 지정 커밋 HF 코드/설정 참조본 보존; 실제 가중치/로봇 드라이버 미포함.
- 실물 제어/학습은 수행하지 않음. 검증 결과는 v002/docs/VALIDATION.md 참조.

## v001 — 2026-11-18

- 사용자 제공 ACT 실행 영상의 메타데이터와 5초 간격 시각 샘플 확인.
- 고정 위치 IL의 85% 이상 성공률과 위치 일반화를 구분.
- 기존 ACT+Residual 우선 권고를 보완: 넓은 위치 변화에는 다위치 시연·기본 정책 확장이 우선.
- 위치·방향 커리큘럼, 비교군, 독립 평가, 실행 기록 필드 제안.
- 1차 문헌 링크와 적용 한계를 정리. 실제 모델 개선 결과 없음.
