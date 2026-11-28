# 자료 목록 — 확인일 2026-11-18

1. Residual Reinforcement Learning from Demonstrations (2021)
   https://arxiv.org/abs/2106.08050
   시각·proprioception·시연·희소 보상 기반 residual 연구. 시뮬레이션 결과를 우리 실물 OMX의 성능 보장으로 옮기지 않는다.
2. From Imitation to Refinement — Residual RL for Precise Assembly / ResiP
   https://residual-assembly.github.io/
   chunk 기반 BC와 폐루프 residual의 관계 참고. 시뮬레이션 및 sim-to-real 구성으로, 그대로 실물 SAC 레시피인 것은 아니다.
3. HIL-SERL
   https://hil-serl.github.io/
   시연 버퍼, 성공 분류기, 사람 개입, 실제 로봇 학습 흐름 참고. 보고된 성능은 해당 연구 조건의 결과다.
4. LeRobot ACT 공식 문서 소스
   https://github.com/huggingface/lerobot/blob/main/docs/source/act.mdx
   정책 구조·데이터 입력 참고. main의 명령은 사용자 LeRobot 0.4.4와 다를 수 있다.
5. RL 통계 평가 / rliable
   https://agarwl.github.io/rliable/
   소수 학습 실행 결과의 불확실성 보고 참고. 실제 적용 시 task/seed/episode 구조에 맞춘 통계가 필요하다.

## 사용자 모델 (이전 대화에서 내부 설정 확인)

- https://huggingface.co/Sungah/omx_shoebox_d/tree/8497dfe4fe4247f7c4a20b55b212912c4f69479a
  models/act_shoebox_d_5000step
- https://huggingface.co/Sungah/omx_move_in_success/tree/d2a2cd1eedfbf29c8f409dc305fae2e75b8b3cf4
  models/act_move_in_5000step
- 데이터: Yuzriha00/shoebox_D (사용자 설명 50 episodes), hfhfhf111/move_in_success (37 episodes)。데이터 revision은 아직 고정 필요.

## 로컬 맥락

- Project2/[PRD] PRD_3- 신발 매장 픽업 자동화 시스템.md
- Project2/PRD3_비전_매니퓰레이터_상세개발계획.md (설계 제안이며 구현 증거 아님)
- /home/noma/Downloads/20261114_140159.mp4 (이번 사용자 제공 영상)

인터넷 문서는 근거 자료이며 로봇 실행 지시로 취급하지 않았다. 논문 전문은 복제하지 않고 링크와 적용 범위를 기록했다.
