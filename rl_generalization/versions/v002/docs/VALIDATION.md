# 검증 결과 — 2026-11-18

- pytest: 9 passed (2.12s). Gym API, deterministic reset, timeout/success 구별, 공중 헛집기, 실제 toy 부착·들기·유지·release, invalid action/config, 지터 경계/시계 오류 검증.
- CPU SAC: 400 steps, 학습 업데이트 수행, model.zip/replay.pkl 생성 및 저장 완료. 콘솔 400-step 로그의 n_updates=143(로그 시점). 완주 시 추가 업데이트 가능.
- 저장 모델 재로딩 후 독립 seed 10000~10002 평가 3회 완료, 성공 0/3. 이는 학습 성능 입증이 아닌 소프트웨어 smoke test다.
- 실제 로봇 실행, 카메라·YOLO 연결, 지터 원인 규명, 실물 학습, sim-to-real 검증은 하지 않았다.
- 테스트 의존성은 /tmp/omx_rl_v002_deps에 설치하고 기존 YOLO 환경의 CPU torch를 읽어 사용했다. 기존 환경 패키지는 변경하지 않았다. 정확한 주요 버전은 evidence/smoke_run.json에 기록.
- 모델/버퍼 검증 파일은 /tmp/omx_rl_v002_smoke에 있으며 영구 모델 산출물로 취급하지 않는다. 버전 폴더에는 설정/평가/학습 로그만 보존한다.
