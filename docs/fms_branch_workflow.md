# 브랜치 사용법 — 팀이 지킬 핵심 규칙

**목적: 각자 만든 기능을 먼저 함께 시험하고, 통과한 코드만 main에 모은다.**

아직 제안 단계다. `submaster`는 만들지 않았고 기존 PR의 대상도 바꾸지 않았다. Git 운영 결정 D16은 계속 미결이다.

## 1. 세 가지만 기억하기

| 브랜치 | 하는 일 |
|---|---|
| `feature/...`, `fix/...` | 각자 기능을 만들거나 버그를 고친다. 테스트도 함께 올린다. |
| `submaster` | 여러 사람의 작업을 모아 함께 시험한다. 도입 후 작업 PR은 여기로 보낸다. |
| `main` | 함께 시험하고 리뷰를 마친 코드를 보관한다. |

**각자 작업 → submaster에서 함께 시험 → main에 반영**

## 2. 꼭 지킬 여섯 가지

1. main·submaster에 바로 push하지 않고 PR로 합친다. 남의 작업 브랜치는 수정하지 않는다.
2. 한 PR은 한 기능·메뉴·계약을 다룬다. 기능 코드, 테스트, 필요한 문서를 같이 올린다. 이름은 [기존 R5](fms_dev_rules.md#r5-브랜치pr)를 따른다.
3. 자동 검사 두 개(`fms-contract`, `fms-web`)를 통과하고 작성자 외 한 명 이상이 리뷰한다. 관련 화면·데이터·로봇 담당자도 변경 내용을 확인한다.
4. 주행·팔·통신을 바꾸면 관련 기능을 실제로 시험한다. 맵·고정대를 바꾸면 **변경 맵과 변경 고정대를 같이 넣고 시뮬레이션을 다시 돌린다.** 못 한 시험은 못 했다고 적는다.
5. submaster → main PR에는 **무엇을 합치는지, 시험 결과, 남은 문제**를 적는다. 시험 뒤 코드가 바뀌면 다시 검사한다. main 반영과 배포·실물 로봇 구동은 별개다.
6. 메모칸 데이터는 기능 수정과 나눠 커밋한다. 저장 버튼은 자동 커밋·GitHub 업로드가 아니다. [메모칸 확인 결과](fms_feedback_commit_review.md)를 참고한다.

## 3. 도입 순서

- 팀이 `submaster` 이름과 병합 담당자를 정한다.
- 관리자가 최신 main에서 submaster를 만들고 **두 브랜치 모두 PR·리뷰·필수 검사 보호**를 켠다. 현재 main 보호는 꺼져 있다.
- 그다음 새 작업은 submaster에서 시작하고, 기존 PR은 작성자가 변경 내용을 확인한 뒤 대상을 전환한다. 지금 열려 있는 PR은 그대로 둔다.
- main과 submaster 사이에는 merge commit으로 이력을 유지한다. 긴급 수정도 PR·시험·리뷰를 받고 두 브랜치에 맞춰 반영한다.

자동 검사를 추가하는 것만으로 보호가 켜지지는 않는다. 적용 여부는 [관리자 확인 문서](fms_repository_governance.md)에 기록한다.

## 4. 현재 브랜치 현황

2026-10-24 14:50 KST 조회: **13개**, main `a3ce4f1`. submaster·develop는 없다. 아래 상태는 그 시점 기준이다.

| 브랜치 | 지금 상태 |
|---|---|
| main | 현재 기준 코드. 메모칸 포함. 보호 꺼짐. |
| feature/navigation | 새 주행 코드 2커밋이 main보다 앞섬. 별도 검토 필요. |
| feature/vision | 비전 자료. main과 공통 출발 이력이 없어 반입 방법 확인 필요. |
| feature/common-registry-ownership-split | PR #7: 관제 담당 분리안, 검토 중. |
| feature/common-registry-integration-rules | PR #8: 이 브랜치 규칙, 검토 중. |
| feature/common-docker-dev-guide | PR #4: 개발 환경 안내, 검토 중. |
| feature/common-team-rules-s1 | PR #5: 공통 규칙, 검토 중. |
| feature/gui-registry-s1-decisions | PR #6: 코드가 이미 main에 포함됨. 작성자가 PR 정리 여부 확인. |
| feature/common-cobot-interfaces | PR #2 병합 완료. 옛 브랜치가 남아 있음. |
| feature/common-map-contract | PR #3 병합 완료. 옛 브랜치가 남아 있음. |
| feature/gui-registry-menu-tree | PR #1 병합 완료. 옛 브랜치가 남아 있음. |
| feature/setup-fleet-msgs-structure | 예전 메시지 설계. 현재 계약과 비교한 뒤 필요한 부분만 반입. |
| tool/omx-ai_record_dashboard | 팀원 팔 도구. 위치·연동 방식 검토 후 반입. |

기존에는 작업 브랜치 → main 규칙만 있었다. 앞서 확인한 저장소·Confluence에서 submaster 운영 합의는 찾지 못해 이번에 초안을 만들었다. PR #7의 담당 분리와 PR #8의 브랜치 규칙은 각각 별도 검토한다.
