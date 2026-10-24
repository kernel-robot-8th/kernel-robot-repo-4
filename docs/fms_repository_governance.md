# 저장소 보호와 검수 적용 상태

- 2026-10-22 조회: main `913eb15`, API protected=false, repository rulesets=[]였다.
- 조회 계정은 push 권한이 있고 admin/maintain 권한은 없다. 따라서 이 변경은 문서·CODEOWNERS 초안·검사 workflow를 준비하며 서버의 보호 설정을 활성화했다고 주장하지 않는다.
- 관련 결정: D16. 보호 설정 활성화와 팀 리뷰가 끝나기 전에는 이 문서의 상태를 '완료'로 바꾸지 않는다.

## 2026-10-24 재조회와 submaster 도입안

- 2026-10-24 14:11 KST: main `a3ce4f1102f918f63e696579e198740e54feaec6`, 원격 브랜치 11개, 전부 API protected=false, rulesets=[]였다. submaster·develop는 없었다. 이 규칙 작성용 feature 브랜치는 스냅샷 이후 추가한다.
- 기존 규칙은 feature/fix → main이며 submaster 합의 기록은 확인한 Git 이력·문서·Confluence 검색에서 찾지 못했다. D16 아래 [통합 시험 브랜치 운영안](fms_branch_workflow.md)을 추가했다. 공용 브랜치 생성, 보호 활성화, 타인 PR 변경은 하지 않았다.
- 도입 후에는 main과 submaster를 모두 보호하고 필수 검사 `fms-contract`, `fms-web`를 실제 성공한 이름으로 지정한다. workflow의 submaster push 검사 준비는 서버의 브랜치 보호나 PR 방향 강제를 뜻하지 않는다.
- D16은 open이다. 관리자 적용 기록·API 읽기 확인·팀 검토가 끝나기 전에는 적용 완료로 기록하지 않는다.

## 관리자가 적용하고 확인할 항목

1. 도입 후 main과 submaster 대상 ruleset 또는 branch protection을 Active로 설정한다. 직접 push·삭제·force push를 제한하고 PR을 요구한다.
2. 작성자 외 승인 1명 이상, 새 커밋 뒤 옛 승인 무효화, 토론 해결을 요구한다. 우회 계정·관리자 예외는 별도로 기록한다.
3. 이 변경의 CI가 실제 실행된 뒤 정확한 check 이름 `fms-contract`, `fms-web`를 필수 검사로 등록하고 base 최신화 조건을 켠다. 공유 브랜치 간 merge commit은 허용하며 linear history 요구는 켜지 않는다. 이름만 적거나 로컬 pytest만 통과한 것은 GitHub 필수 검사 활성화가 아니다.
4. CODEOWNERS의 계정과 해당 사용자의 저장소 권한을 팀이 확인한 뒤 code owner review를 요구한다. 작성자는 자기 PR을 승인할 수 없으므로 공통 규칙에 작성자 외 검토자가 있어야 한다.
5. 보호 API/ruleset 읽기와 실제 PR 화면으로 재확인한다. main에 시험용 직접 push나 로봇 명령을 보내는 음성 대조는 하지 않는다.

## CODEOWNERS 초안의 범위

계정은 현재 커밋 작성자에서 확인했다: rkd1rjs2(현재 FMS PR), cdwlsgh1-source(main·주행 README), sakim0128·JiHyeokHeo(OMX 대시보드). 이것은 리뷰 요청 경로 제안이며 팀원 역할·책임 승인을 대신하지 않는다. GitHub 계정이 확인되지 않은 팀원을 추정해서 넣지 않았다.

## CI와 실행 증거

`fms-contract`는 메뉴·SR 정본·브랜치 규칙·문서 생성의 Python 시험이다. ROS/colcon 빌드, 도메인 스파이크, 물리 시뮬레이션, 센서·실물 검증은 포함하지 않는다. 그 결과는 해당 패키지 PR의 별도 증거로 남긴다. PR 본문의 기존 시험 숫자는 이전 SHA의 기록이며 새 SHA에 자동 승계하지 않는다.

CI가 준비됐더라도 S1 결정 검사 `--require-decided D1,D2,D3,D4,D5,D8`는 모두 proposed인 동안 1을 내야 한다. 문서 검사 통과와 결정 승인·병합·설정 활성화는 각각 다른 상태다.
