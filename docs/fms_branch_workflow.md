# 브랜치 운영 규칙 — submaster 통합 시험안

- 상태: **D16 검토 초안**, 2026-10-24. 공용 `submaster` 생성·보호 활성화·기존 PR 대상 변경은 아직 하지 않았다.
- 대상: `kernel-robot-8th/kernel-robot-repo-4` 전체. 기존 역할·메뉴별 작업 범위는 [R5](fms_dev_rules.md#r5-브랜치pr)를 유지한다.
- `submaster`는 **기능 코드와 그 코드를 검증하는 테스트를 함께 모으는 통합 시험 브랜치**다. 테스트 파일만 따로 모으지 않는다.
- 이 초안이 병합되어도 보호 설정과 팀 합의가 자동 적용되지는 않는다. 아래 도입 절차와 읽기 확인 기록까지 있어야 활성화 상태로 바꾼다.

## 1. 이전에 정한 내용과 이번에 추가하는 내용

기존 `CLAUDE.md` §8, `fms_dev_rules.md` R5에는 작업 브랜치 이름, main 직접 push 금지, PR·리뷰 규칙이 있다. `fms_decisions.md`의 D16은 Git 규칙 단일화·main 보호·CODEOWNERS를 미결로 둔다. 통합 시험 브랜치 이름이나 승격 절차는 정해져 있지 않았다.

2026-10-24 조회에서는 원격 전체 브랜치와 조회 가능한 Git 이력, Confluence 검색 결과를 대조했다. [FMS 개발 가이드 v7](https://pinkyteam4.atlassian.net/wiki/spaces/PinkyTeam4/pages/8749058), [PRD_3 v14](https://pinkyteam4.atlassian.net/wiki/spaces/PinkyTeam4/pages/3899424), [FMS 검증 계획 v3](https://pinkyteam4.atlassian.net/wiki/spaces/PinkyTeam4/pages/2916354)에도 `submaster` 명칭·운영 합의는 없었다. PRD_3에는 Git 전략 작성과 통합 QA 업무가 있다. 검색에 잡히지 않는 회의 발언까지 없었다는 뜻은 아니다.

이번 사용자 요청을 반영해 `submaster`라는 이름과 아래 절차를 제안한다. 개인 담당자·병합 담당자는 팀이 지정하며, 문서 작성자에게 공용 브랜치 변경 권한을 자동 부여하지 않는다.

## 2. 원격 현황 스냅샷

조회 기준: **2026-10-24 14:11 KST**, 이 규칙 작업 브랜치를 원격에 올리기 전. main은 `a3ce4f1102f918f63e696579e198740e54feaec6`이다. [branches API](https://api.github.com/repos/kernel-robot-8th/kernel-robot-repo-4/branches?per_page=100), [PR API](https://api.github.com/repos/kernel-robot-8th/kernel-robot-repo-4/pulls?state=all&per_page=100), [rulesets API](https://api.github.com/repos/kernel-robot-8th/kernel-robot-repo-4/rulesets?per_page=100) 및 fetch한 이력 기준이다. 아래 표의 앞섬/뒤처짐은 `git rev-list --left-right --count main...<branch>`의 커밋 수를 뒤집어 표기했다. 파일 충돌 여부나 기능 완성도를 뜻하지 않는다.

| 원격 브랜치 | HEAD | main보다 앞섬 / 뒤처짐 | PR·이력 상태 |
|---|---|---:|---|
| main | a3ce4f1 | 0 / 0 | 기본 브랜치 |
| feature/common-cobot-interfaces | 143265d | 0 / 41 | #2 병합, HEAD는 main의 조상 |
| feature/common-map-contract | 41265ed | 0 / 39 | #3 병합, HEAD는 main의 조상 |
| feature/gui-registry-menu-tree | 2f23424 | 0 / 42 | #1 병합, HEAD는 main의 조상 |
| feature/navigation | eb88c46 | 0 / 4 | HEAD는 main의 조상 |
| feature/common-docker-dev-guide | 3d2957b | 2 / 46 | #4 open Draft → main |
| feature/common-team-rules-s1 | d96a0d2 | 3 / 46 | #5 open Draft → main |
| feature/gui-registry-s1-decisions | ca410ec | 0 / 37 | #6 open Draft → 이미 병합된 menu-tree 브랜치; HEAD는 main의 조상 |
| feature/common-registry-ownership-split | 05a95ec | 1 / 0 | #7 open Draft → main |
| feature/setup-fleet-msgs-structure | 1c2002a | 18 / 58 | main과 분기; 통합 브랜치로 간주하지 않음 |
| tool/omx-ai_record_dashboard | e78dd9a | 6 / 46 | main과 분기; 기존 도구 반입·배치 검토 필요 |

원격 브랜치는 11개였고 `submaster`·`develop`는 없었다. 모든 브랜치의 API `protected=false`, repository `rulesets=[]`였다. 따라서 기존 문서의 'main 보호'는 운영 목표이며 실제 서버 설정 증거가 아니다. 이 문서 작성용 feature 브랜치는 위 스냅샷 이후 별도로 추가된다.

## 3. 활성화 후 기본 흐름

```text
submaster에서 작업 브랜치 생성
  feature/<역할>-<메뉴 ID 또는 common/registry>-<내용>
  fix/<역할>-<메뉴 ID 또는 common/registry>-<내용>
       ↓ 기능 코드 + 테스트 + 계약/문서, PR·리뷰
submaster: 여러 파트 결합, CI와 도메인 통합 시험
       ↓ submaster → main 승격 PR, 같은 후보로 최종 검증
main: 검증·리뷰를 마친 기준선
```

| 브랜치 | 출발점·PR 대상 | 용도·제약 |
|---|---|---|
| feature / fix | 최신 submaster에서 분기 → submaster | 한 메뉴·인터페이스 단위. 공용 예외는 R5. 코드·회귀 테스트·계약을 같은 PR로 올린다. |
| submaster | 도입 시 검증한 main에서 생성 | 통합 시험. 초안 PR은 올릴 수 있으나 실패한 검사·미해결 충돌·필수 리뷰 없는 PR을 병합하지 않는다. |
| main | submaster → main 승격 PR | 공유 기준선. main 병합은 배포·실물 구동 승인과 별개다. |

공용 브랜치에 직접 push·force push·이력 재작성하지 않는다. 남의 작업 브랜치도 수정하지 않는다. 레지스트리의 `branch`에는 해당 작업 브랜치를 기록하며 `submaster`로 작업 소유권을 예약하지 않는다. 통합 브랜치 병합만으로 메뉴 `done`이나 미결 결정 `decided`로 올리지 않는다.

인터페이스 변경이 선행되어야 한다는 R3는 그대로 적용한다. 도입 후에는 인터페이스 PR을 submaster에 먼저 병합한 뒤 그 HEAD에서 소비자 구현을 시작한다. 생성 파일을 손으로 고치거나 서로 다른 인터페이스 사본을 별도 수정하지 않는다.

## 4. 두 단계의 병합 조건

### 작업 PR → submaster

- 원격 base/head SHA, 메뉴·SR ID 또는 공용 계약 범위, 변경 패키지·소비자, 재현 명령을 PR에 적는다.
- 최소 작성자 외 1명 승인과 변경 영역 담당 리뷰를 받는다. 화면·데이터 계약 변경은 두 담당, 공통 인터페이스 변경은 영향받는 소비자 담당을 포함한다. 같은 사람이 자격을 충족할 수 있으나 작성자의 자기 승인은 인정하지 않는다.
- 필수 기본 검사 `fms-contract`, `fms-web`가 현재 후보에서 성공해야 한다. 이 두 검사만으로 저장소 전체 ROS·주행·팔 구현을 검증했다고 쓰지 않는다.
- ROS 변경은 대상 패키지와 영향받는 소비자의 `colcon build`, `colcon test`, `colcon test-result --verbose` 결과를 별도 첨부한다. 실행 환경이 없어 미수행이면 해당 검증은 미완이다. 문서만 바꾸는 PR은 해당 없음의 이유를 적는다.
- 맵·고정대·로봇 모델을 바꾸면 **변경 맵과 변경 고정대를 함께 넣은 월드**로 관련 시뮬레이션을 다시 실행한다. 입력/모델 버전, 시드·조건, 경로·도킹·팔 접근, 충돌/관통량, receipt/results 위치를 남긴다. 이전 맵 결과를 새 형상의 통과 증거로 재사용하지 않는다. 합성 결과와 실측은 구분한다.
- skip·미수행·알려진 실패를 PASS로 세지 않는다. 승인을 무효화할 새 코드 변경이 있으면 재검사·재리뷰한다.

### submaster → main 승격 PR

1. 병합 담당자가 이번 후보 범위와 포함 PR 목록을 고정하고 submaster 유입을 잠시 중단한다. 현재 main 변경은 먼저 main → submaster PR로 동기화한다.
2. base(main) SHA, head(submaster) SHA, GitHub의 PR merge 결과 SHA를 기록한다. GitHub PR CI는 head와 base를 합친 후보를 검사하므로 head 시험과 구분한다.
3. 그 후보에서 기본 검사와 변경 파트 간 통합 시나리오를 검증한다. ROS 메시지 호환, GUI↔관제 데이터, 해당 시 주행·팔·맵 시뮬레이션 증거와 남은 제약을 첨부한다. 물리 시험이 별도라면 승격의 범위가 합성/코드 검증임을 명시하고 실제 동작을 승인하지 않는다.
4. 작성자 외 리뷰 및 관련 담당의 확인 후 **merge commit**으로 승격한다. main↔submaster에는 squash/rebase merge를 쓰지 않아 공통 이력을 유지한다.
5. base/head가 바뀌면 기존 영수증과 승인은 새 후보를 보증하지 않는다. 다시 검증한다. 동시 승격 PR은 하나만 유지한다.
6. 병합 후 실제 main SHA와 push CI 결과를 읽어 기록한다. 시험한 merge 결과와 최종 커밋이 다르면 트리 동일성을 확인하고, 다르면 승격 완료로 선언하지 않고 재검증한다. main → submaster 동기화 PR로 이력을 맞춘 뒤 다음 작업을 시작한다.

통합 실패를 해결할 때는 원인 작업의 fix PR 또는 revert PR을 submaster에 올린다. main 긴급 수정은 팀이 명시적으로 예외를 승인한 fix → main PR만 허용하고 동일 검사·리뷰를 받는다. 이후 main → submaster PR로 반드시 동기화한다. 직접 push나 자동 배포 예외는 만들지 않는다.

## 5. 기존 브랜치·PR의 전환

현재는 submaster가 없으므로 기존 PR의 base를 바꾸지 않는다. 이 규칙·CI 준비 PR은 main을 대상으로 하는 **도입용 예외**이며, 일반 기능 PR의 우회 통로가 아니다.

- #4·#5·#7: open Draft를 유지한다. 도입 후 각 작성자가 최신 submaster와 차이를 대조하고 base를 전환할지, 필요한 변경만 새 PR로 낼지 선택한다. retarget 뒤 diff·검사·리뷰를 다시 확인하며 옛 green 결과를 승계하지 않는다.
- #6: HEAD는 이미 main에 포함됐지만 base가 이전 menu-tree 브랜치다. 작성자가 의도와 잔여 diff를 확인한 뒤 정리한다. 이 초안에서 닫거나 base를 바꾸지 않았다.
- #1·#2·#3: 이미 병합됐다. 남은 브랜치를 새 통합 시험 환경으로 사용하지 않는다. 삭제는 작성자·관리자의 별도 정리 작업이다.
- feature/navigation: HEAD가 main의 조상이다. 후속 작업은 최신 submaster에서 새 작업 단위로 시작한다.
- feature/setup-fleet-msgs-structure, tool/omx-ai_record_dashboard: 분기된 소스를 통째로 병합하지 않는다. 현행 인터페이스·폴더·장치 경계와 비교해 필요한 변경을 작업 PR로 분리하고 담당자 검토를 받는다.
- #7의 관제 담당 분리안은 별도 검토 사항이다. 이 브랜치 운영안이 #7의 승인·병합을 대신하지 않는다.

## 6. 도입과 서버 설정 확인

1. 팀이 `submaster` 명칭, 통합 병합 담당자·대리자, 위 조건과 기존 PR 전환 순서를 확인한다. D16은 지금 `open`이며 이 문서만으로 완료 처리하지 않는다.
2. 도입 PR 검토·병합 후 관리자가 기준 main의 정확한 SHA에서 submaster를 생성한다. 본 작업은 공용 브랜치를 생성하지 않는다.
3. main과 submaster 모두 PR·작성자 외 승인·담당 리뷰·새 커밋 뒤 옛 승인 무효화·토론 해결·삭제/force push 제한을 적용한다. 필수 검사 이름은 실제 성공한 `fms-contract`, `fms-web`와 일치시키고 `Require branches to be up to date before merging`을 켠다. 공유 브랜치 간 merge commit을 허용하도록 저장소의 merge commit 방법을 켜고 두 브랜치의 `Require linear history`는 켜지 않는다. 우회 주체와 예외도 기록한다.
4. workflow는 모든 PR 및 main/submaster push에서 두 기본 검사를 실행하도록 준비한다. 브랜치 이름·PR 진행 방향은 이 변경의 CI가 자동 강제하지 않는다. 서버 ruleset 또는 병합 담당자가 확인해야 한다.
5. API protected/rulesets 읽기와 실제 PR 화면으로 적용 상태를 확인한다. main에 시험 push를 보내는 방식은 사용하지 않는다. [저장소 거버넌스](fms_repository_governance.md)에 적용 시각·주체·ruleset ID·base/head·check 결과를 기록한 뒤 팀이 D16 상태를 갱신한다.

## 7. PR에 남길 최소 증거

```text
종류: 작업 통합 / main 승격 / 도입 / 승인된 긴급 수정
base 브랜치@SHA:
head 브랜치@SHA:
PR merge 결과 SHA (확인한 경우):
포함 PR / 메뉴·SR / 변경 패키지·소비자:
명령·환경·검사 링크 / 합성·실측 구분:
미수행·skip·실패 / 적용 범위 밖의 결정:
리뷰어·병합 담당자:
병합 후 main 또는 submaster SHA / push CI:
```

PR 템플릿은 이 항목을 안내한다. 미정 담당자나 실제로 실행하지 않은 검사 결과를 채워 넣지 않는다.

GitHub 동작 참고: [PR CI의 merge 결과 검사](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request), [보호 브랜치·필수 검사 설정](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches). 이 문서의 팀 운영 제안과 GitHub 서버의 실제 적용 상태는 구분한다.
