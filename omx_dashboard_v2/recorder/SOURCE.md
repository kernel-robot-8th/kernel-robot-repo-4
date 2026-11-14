# 출처
팀 수집 대시보드 `omx_recoder`를 그대로 복사한 폴더입니다.

- 저장소: https://github.com/kernel-robot-8th/kernel-robot-repo-4
- 브랜치: tool/omx-ai_record_dashboard
- 커밋: f747a25 (2026-10-26)

바꾼 것:
- `config.example.yaml`의 기본 저장 경로를 `./output` → `~/il_ws/recordings` (실행 위치와 상관없이 같은 곳에 저장)

코드(core/, ui/)는 수정하지 않았습니다. 색·모양과 추론 탭과의 충돌 방지는 상위 폴더의 `rec_embed.py`에서 바깥에서 입힙니다.
팀 저장소가 업데이트되면 core/, ui/ 폴더만 새로 복사하면 됩니다.
