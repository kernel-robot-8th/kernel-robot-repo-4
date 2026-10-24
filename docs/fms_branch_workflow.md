# 브랜치 사용법 — 팀이 지킬 핵심 규칙

**목적: 각자 만든 기능을 먼저 함께 시험하고, 통과한 코드만 main에 모은다.**

**submaster 사용은 사용자 확정 사항이다.** 2026-10-24 16:21 KST에 최신 main `a3ce4f1`과 같은 커밋에서 생성했다. 기존 담당 분야 브랜치는 계속 사용하고 PR은 submaster로 보낸다. 새 분야 브랜치가 필요하면 최신 submaster에서 시작한다. 기존 PR의 대상은 작성자가 확인 후 전환한다. D16 중 보호 설정·담당 리뷰 적용은 아직 미완이다.

팀원 메시지방에는 [공유용 공지](github_team_notice.md)를 사용한다. [브랜치 생성 확인](evidence/submaster-created-20261024.json).

## 1. 세 가지만 기억하기

| 브랜치 | 하는 일 |
|---|---|
| `feature/<분야>`, `fix/...` | 담당 분야에서 기능을 만들거나 버그를 고친다. 기존 분야 브랜치를 계속 쓸 수 있다. |
| `submaster` | 여러 사람의 작업을 모아 함께 시험한다. 새 작업 PR은 여기로 보낸다. |
| `main` | 함께 시험하고 리뷰를 마친 코드를 보관한다. |

**담당 분야에서 작업 → submaster에서 함께 시험 → main에 반영**

## 2. 꼭 지킬 여섯 가지

1. main·submaster에 바로 push하지 않고 PR로 합친다. 남의 작업 브랜치는 수정하지 않는다.
2. 한 PR은 관련된 변경을 모아 리뷰할 수 있게 올린다. 기능 코드, 테스트, 필요한 문서를 같이 올린다. 팀 브랜치 이름은 분야 중심으로 정하며 작은 작업마다 브랜치를 새로 만들 필요는 없다. [R5](fms_dev_rules.md#r5-브랜치pr)의 메뉴 번호 형식은 FMS 개별 메뉴 예약용이고 팀 전체에 강제하지 않는다.
3. 자동 검사 두 개(`fms-contract`, `fms-web`)를 통과하고 작성자 외 한 명 이상이 리뷰한다. 관련 화면·데이터·로봇 담당자도 변경 내용을 확인한다.
4. 주행·팔·통신을 바꾸면 관련 기능을 실제로 시험한다. 맵·고정대를 바꾸면 **변경 맵과 변경 고정대를 같이 넣고 시뮬레이션을 다시 돌린다.** 못 한 시험은 못 했다고 적는다.
5. submaster → main PR에는 **무엇을 합치는지, 시험 결과, 남은 문제**를 적는다. 시험 뒤 코드가 바뀌면 다시 검사한다. main 반영과 배포·실물 로봇 구동은 별개다.
6. 메모칸 데이터는 기능 수정과 나눠 커밋한다. 저장 버튼은 자동 커밋·GitHub 업로드가 아니다. 데이터셋·큰 모델은 외부 저장소와 링크 공유를 우선한다. [메모칸 확인 결과](fms_feedback_commit_review.md)를 참고한다.

## 3. 적용 상태와 남은 일

- `submaster` 이름·사용 흐름 확정, 최신 main에서 생성 완료. main은 변경하지 않았다.
- 관리자는 **두 브랜치 모두 PR·리뷰·필수 검사 보호**를 켜고 병합 담당자를 확인한다. 생성 직후 main·submaster 보호는 꺼져 있다.
- 기존 분야 브랜치는 계속 사용하며, 오래된 코드는 담당자가 최신 submaster와 차이를 확인한다. 새 분야 브랜치는 submaster에서 시작한다. 기존 PR은 작성자가 확인 후 대상을 전환하고 일괄 변경하지 않는다.
- main과 submaster 사이에는 merge commit으로 이력을 유지한다. 긴급 수정도 PR·시험·리뷰를 받고 두 브랜치에 맞춰 반영한다.

자동 검사를 추가하는 것만으로 보호가 켜지지는 않는다. 적용 여부는 [관리자 확인 문서](fms_repository_governance.md)에 기록한다.

## 4. 우리 브랜치 정리 결과

2026-10-24 16:33 KST, 사용자 요청으로 완료된 원격 브랜치 4개를 정리했다. 모두 main과 submaster에 포함된 것을 확인하고, 원래 커밋 이력을 로컬 Git bundle로 보존한 뒤 삭제했다. 원격 브랜치는 **15개 → 11개**가 됐다.

| 정리한 브랜치 | 확인 내용 |
|---|---|
| feature/common-cobot-interfaces | PR #2 병합 완료 |
| feature/common-map-contract | PR #3 병합 완료 |
| feature/gui-registry-menu-tree | PR #1 병합 완료 |
| feature/gui-registry-s1-decisions | HEAD가 이미 main·submaster에 포함되어 중복 PR #6을 닫고 브랜치 삭제 |

PR #6은 새로 병합한 것이 아니라 **이미 반영된 변경의 중복 PR을 종료**한 것이다.

- **보존:** PR #4 개발 환경(미반영 2커밋), #5 공통 규칙(미반영 3커밋), #7 관제 담당 분리, #8 공지·운영 규칙. 미병합 변경은 지우지 않았다.
- **변경하지 않음:** main·submaster, 팀원 분야 브랜치인 feature/navigation·feature/vision·feature/setup-fleet-msgs-structure·omx_train·tool/omx-ai_record_dashboard.
- 기록: [정리 확인](evidence/fms-branch-cleanup-20261024.json). PR #7과 #8은 계속 별도 검토하며, 이번에 main·submaster로 병합하지 않았다.
