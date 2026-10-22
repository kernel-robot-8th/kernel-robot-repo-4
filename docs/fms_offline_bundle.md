# FMS 오프라인 설치 번들 목록

- 상태: 초안 (2026-10-22). 팀 리뷰 전이다.
- 검증: A 는 Linux PC 한 대(Ubuntu 22.04, Docker 29.2.1, amd64)에서 `save`·`load` 와 음성 대조를 실제로 돌려 확인했다 (5.4 기록). A-0·B 는 아직 만들지도 검증하지도 않았다.
- S1 범위 (초안, 관제 담당 공지 전): S1 출구 검사 6 은 A 만 보고, A-0·B·C 는 S2 로 옮기자고 추천한다 (5장).
- 무엇: 로드맵 S1 출구 검사 6(오프라인 설치)이 보는 번들의 목록과 확인 방법.
- 근거: [`docs/fms_roadmap.md`](fms_roadmap.md) S1 출구 검사 6, 설계서 §2.3 '오프라인 설치' 행과 §9.1 P0 (레포 밖 초안, 출처 표시).
- 왜: 현장 LAN 에는 인터넷이 없다고 보고됐다 (설계서 §2.3, 현장 실측 D18 전). 설치물을 미리 들고 가지 않으면 현장에서 아무것도 설치할 수 없다.
- 도커 사용법: [`docs/dev_docker_guide.md`](dev_docker_guide.md)
- apt 설치·`sudo` 는 사용자 확인 뒤에만 한다 (CLAUDE.md §9). AI 에이전트도 같다.

## 1. 한눈에

| 묶음 | 무엇 | 쓰는 곳 | 단계 | 상태 |
|---|---|---|---|---|
| A | 개발·시험 도커 이미지 tar + `.sha256` | 인터넷 없는 PC 에서 빌드·시험 | S1 | `dev.sh save`·`load` 로 만든다. Linux PC 한 대에서 검증 (5.4) |
| A-0 | 도커 엔진 설치 파일(.deb) + `SHA256SUMS` | 도커가 없는 인터넷 없는 Ubuntu PC | S2 (초안) | 목록 초안, 미검증 |
| B | ROS 2 Jazzy apt 패키지(.deb) + `SHA256SUMS` | 현장 PC 에 ROS 직접 설치 | S2 (초안) | 목록·방법 초안, 미검증 |
| C | fastapi·uvicorn, MediaMTX, chrony, 웹 라이브러리 | P1 관제 기동 | S2 | 미정 |

## 2. A — 개발·시험 이미지

| 파일 | 만드는 법 | 확인 |
|---|---|---|
| `cobot-dev_jazzy-<YYYYMMDD>_<amd64 또는 arm64>.tar` | `bash scripts/docker/dev.sh save <레포 밖 폴더>` | 아래 `.sha256` |
| 위 이름 + `.sha256` | 같은 명령이 함께 만든다 | `dev.sh load` 가 불러오기 전에 확인한다 |
| (선택) `<ws>.bundle` + `<ws>.bundle.sha256` | `git bundle create <ws>.bundle --all` 후 `sha256sum <ws>.bundle > <ws>.bundle.sha256` | `sha256sum -c`, 받는 쪽은 `git clone <ws>.bundle <ws>` |

- 이미지에는 레포가 들어 있지 않다. 레포는 git 번들 등으로 따로 옮긴다.
- 태그 날짜는 `dev.sh` 의 `IMAGE_VERSION` 이다. 번들과 레포의 `dev.sh` 가 같은 날짜여야 한다. 다르면 `load` 가 "태그가 없다" 로 실패한다.
- 가져갈 PC 와 CPU 종류(`amd64`·`arm64`)가 같아야 한다.
- 번들은 레포에 커밋하지 않는다 (큰 파일 금지, CLAUDE.md §3-1). `dev.sh save` 는 레포 안 폴더를 거부한다.

### A-0 — 도커 엔진 (.deb, 도커가 없는 PC 만)

| 파일 | 받는 곳 | 상태 |
|---|---|---|
| `containerd.io_<버전>_<arch>.deb` | Docker 공식 문서 'Install from a package' 의 Ubuntu noble 저장소 | 버전 미정 |
| `docker-ce_<버전>_<arch>.deb` | 같음 | 버전 미정 |
| `docker-ce-cli_<버전>_<arch>.deb` | 같음 | 버전 미정 |
| `docker-buildx-plugin_<버전>_<arch>.deb` | 같음 | 버전 미정 |
| `docker-compose-plugin_<버전>_<arch>.deb` | 같음 | 버전 미정 |
| `SHA256SUMS` | 받은 뒤 `sha256sum *.deb > SHA256SUMS` | — |

- 버전 기준 후보: A 를 검증한 PC 의 Docker 29.2.1 (`docker-ce`·`docker-ce-cli`). 나머지 .deb 의 버전은 그 버전과 함께 받을 때 정한다 (미정).
- 설치: `sha256sum -c SHA256SUMS` 뒤 `sudo apt-get install --no-download ./*.deb` [추정, 미검증].
- 깨끗한 Ubuntu 에 빠진 의존성(예: `iptables`)이 있으면 설치가 실패한다. 그때는 그 .deb 도 번들에 더한다 [추정].

## 3. B — 현장 PC (ROS 2 Jazzy 직접 설치)

- 현장 PC 를 직접 설치로 돌릴지 컨테이너로 돌릴지는 이 문서가 정하지 않는다. 지금 README 는 직접 설치다. 아래는 직접 설치 기준이다.
- A 의 도커 이미지는 빌드·시험 전용이다. 실물 장치를 열지 않으므로 현장 실행용이 아니다.

| 패키지 | 왜 | 상태 |
|---|---|---|
| `ros-jazzy-ros-base` | ROS 2 Jazzy 기본 | 초안 |
| `ros-jazzy-desktop` | README '처음 설치하기' 의 설치 대상. 현장 PC 에 RViz 등 화면 도구가 필요하면 | 미정 (`ros-base` 와 둘 중 하나) |
| `ros-dev-tools` | 현장 PC 에서 `colcon build` 를 할 때 | 초안 |
| `python3-yaml` | `cobot_gui` 실행 의존성 | 초안 |
| 팀 패키지의 rosdep 의존성 | 각 패키지 `package.xml` 에서 나온다 | S1 PR 머지 뒤 다시 뽑는다 |
| 위 패키지들의 의존 .deb 전부 + `SHA256SUMS` | 아래 방법으로 모은다 | 미검증 |

뽑는 방법 (초안, 실행 검증 때 명령을 확정한다):

1. 팀 패키지 의존성을 apt 이름으로 본다. 설치는 하지 않는다. 도커 셸 안에서 해도 된다.
   ```bash
   rosdep install --from-paths src --ignore-src -r --simulate
   ```
2. 인터넷 되는 깨끗한 Ubuntu 24.04(VM 또는 `ubuntu:24.04` 컨테이너)에 ROS apt 저장소를 등록하고, 위 목록을 `apt-get install --download-only` 로 받는다. `.deb` 는 `/var/cache/apt/archives/` 에 모인다.
3. 받은 `.deb` 를 한 폴더에 모으고 `sha256sum *.deb > SHA256SUMS` 를 만든다.
4. 현장 PC: `sha256sum -c SHA256SUMS` 가 모두 `OK` 인지 본 뒤 `sudo apt-get install --no-download ./*.deb`.

주의 [추정, 검증 필요]:

- 번들을 만든 Ubuntu 보다 현장 PC 의 기본 패키지가 오래됐으면 버전이 안 맞아 설치가 실패할 수 있다. 현장 PC 와 같은 상태의 VM 에서 번들을 만드는 쪽이 안전하다.

## 4. C — S2 이후 (미정)

S1 에서는 만들지 않는다. 결정과 범위가 정해지면 이 표를 채운다.

| 항목 | 왜 | 기다리는 것 | 메모 |
|---|---|---|---|
| fastapi·uvicorn | 웹 게이트웨이 | D8 결정 (의존성 허락) | apt `python3-fastapi`·`python3-uvicorn` 이 있는지는 [추정]. 확인: `apt-cache policy python3-fastapi python3-uvicorn` |
| MediaMTX 릴리스 바이너리 + sha256 | 시청용 영상 팬아웃 | S2 범위, 버전 미정 | 공식 릴리스의 체크섬과 대조한다 |
| chrony + 설정 파일 | 장비 간 공통 시계 | S2 범위. 네트워크 설정이라 팀 합의가 먼저 (CLAUDE.md §9) | apt `chrony` |
| 웹 프론트 라이브러리(vendoring) 목록 + sha256 | 관제 화면 | D8 결정 | 목록 없음 |

## 5. 검증 방법 (S1 출구 검사 6)

- 로드맵 검사 6 (지금 문구): 네트워크를 끊은 깨끗한 VM 에 번들만으로 설치되고, 번들에서 파일 하나를 빼면 설치가 실패해야 한다.
- 추천 범위 (초안, 관제 담당이 S1 결정과 함께 공지하면 확정):
  - S1 의 검사 6 은 **A 만** 본다. 5.1(네트워크 없이 빌드·시험)과 5.2(음성 대조)를 모두 통과해야 한다.
  - A-0·B·C 는 S2 출구 검사로 옮긴다. 담당은 관제 (초안).
  - 이유: A 만 실제로 만들어 확인했다. B 는 현장 PC 를 직접 설치로 돌릴지 컨테이너로 돌릴지(3장)가 정해져야 목록이 정해진다. A-0 는 도커가 없는 오프라인 PC 가 있을 때만 필요하다. C 는 D8 후속 결정과 S2 범위다.
- 로드맵(`docs/fms_roadmap.md`)의 검사 6 문구는 S1 결정 PR 에서 함께 고친다. 고치기 전까지 두 문서가 다르면 로드맵이 정본이다.
- 결과(명령, 종료 코드, 이미지 태그, sha256, CPU 종류, 날짜)는 PR 에 붙인다. skip 은 통과가 아니다.

### 5.1 A — 네트워크 없이 빌드·시험이 되는가

인터넷 없는 PC 또는 네트워크를 끊은 VM 에서 한다. `<폴더>` 는 번들을 둔 곳이다.

```bash
docker image rm cobot-dev:jazzy-20261022 || true      # 깨끗한 상태에서 시작 (없으면 오류가 나도 괜찮다)
bash scripts/docker/dev.sh load <폴더>/cobot-dev_jazzy-20261022_amd64.tar
bash scripts/docker/dev.sh test                       # 기본이 --network none
echo "rc=$?"                                          # rc=0, 실패 0, skip 0 이어야 통과
```

컨테이너에 정말 네트워크가 없는지 대조한다:

```bash
bash scripts/docker/dev.sh shell
python3 -c "import socket; socket.create_connection(('packages.ros.org', 443), 3)"
# 오류(gaierror 또는 Network is unreachable)가 나야 정상이다. 연결되면 검사 실패다.
exit
```

### 5.2 A — 파일 하나를 빼면 실패하는가

```bash
T=<폴더>/cobot-dev_jazzy-20261022_amd64.tar
N="$(basename "$T")"

# (1) .sha256 을 빼면 load 가 실패해야 한다
mkdir -p /tmp/bundle_neg1 && cp "$T" /tmp/bundle_neg1/
bash scripts/docker/dev.sh load "/tmp/bundle_neg1/$N"; echo "rc=$?"     # rc=1 이어야 한다

# (2) tar 를 빼면 load 가 실패해야 한다
mkdir -p /tmp/bundle_neg2 && cp "$T.sha256" /tmp/bundle_neg2/
bash scripts/docker/dev.sh load "/tmp/bundle_neg2/$N"; echo "rc=$?"     # rc=1 이어야 한다

# (3) tar 를 1바이트 바꾸면 load 가 실패해야 한다
mkdir -p /tmp/bundle_neg3 && cp "$T" "$T.sha256" /tmp/bundle_neg3/
printf 'X' | dd of="/tmp/bundle_neg3/$N" bs=1 seek=1000 conv=notrunc
bash scripts/docker/dev.sh load "/tmp/bundle_neg3/$N"; echo "rc=$?"     # rc=1 이어야 한다

# (4) .sha256 이 다른 파일 이름을 가리키면 load 가 실패해야 한다
mkdir -p /tmp/bundle_neg4 && cp "$T" /tmp/bundle_neg4/other.tar && cp "$T.sha256" /tmp/bundle_neg4/other.tar.sha256
bash scripts/docker/dev.sh load /tmp/bundle_neg4/other.tar; echo "rc=$?"  # rc=1 이어야 한다

# 끝나면 /tmp/bundle_neg1 ~ 4 는 지운다 (원본 번들은 건드리지 않았다)
```

### 5.3 B — 현장 PC 설치 (초안, 미검증)

1. 깨끗한 Ubuntu 24.04 VM 의 네트워크를 끊는다.
2. 번들 폴더에서 `sha256sum -c SHA256SUMS` 가 모두 `OK` 다.
3. `sudo apt-get install --no-download ./*.deb` 가 성공한다.
4. `source /opt/ros/jazzy/setup.bash && ros2 pkg list` 가 패키지 목록을 보인다.
5. 음성 대조 두 가지:
   - `SHA256SUMS` 는 그대로 두고 `.deb` 하나를 빼면 `sha256sum -c` 가 실패해야 한다.
   - 의존 관계가 있는 `.deb` 하나(예: `ros-jazzy-rclpy_*.deb`)를 빼고 `SHA256SUMS` 에서도 그 줄을 지우면 3번이 의존성 부족으로 실패해야 한다.

### 5.4 A 검증 기록 (2026-10-22)

- 환경: Linux PC 한 대 (Ubuntu 22.04, Docker 29.2.1, amd64). 그 PC 의 다른 이미지와 겹치지 않게 이미지 태그 이름만 바꿔 돌렸다. tar 파일 이름은 `cobot-dev_jazzy-20261022_amd64.tar` 그대로다.
- 이 기록은 **검사 6 자체가 아니다.** 인터넷이 되는 PC 에서 컨테이너만 네트워크 없이 돌렸다. 네트워크를 끊은 깨끗한 VM 에서 하는 검사 6 은 아직 하지 않았다.

| 무엇 | 결과 |
|---|---|
| `save <레포 밖 폴더>` | rc=0, 5 초. tar 326,920,192 바이트와 `.sha256` 생성 |
| `sha256sum -c` (손 확인) | `OK` |
| 레포 안 폴더에 `save` | rc=1 (거부), 폴더도 남지 않음 |
| 같은 폴더에 다시 `save` | rc=1 (덮어쓰기 거부) |
| 5.2 (1) `.sha256` 없음 | rc=1 |
| 5.2 (3) tar 1바이트 손상 | rc=1. 바꾸기 대신 1바이트 잘라내기로 돌렸다 |
| 5.2 (4) 다른 이름을 가리키는 `.sha256` | rc=1 |
| 5.2 (2) tar 없음 | 이 PC 에서는 돌리지 않았다. 가짜 docker 로 돌린 스크립트 시험에서만 rc=1 |
| 이미지 태그를 지운 뒤 정상 `load` | rc=0, 3 초 |
| 불러온 이미지로 `test --packages-select cobot_gui` (네트워크 없음) | rc=0, `42 tests, 0 errors, 0 failures, 0 skipped` |
| 컨테이너 안 네트워크 장치 | `lo` 하나뿐. 5.1 의 python 연결 시험은 돌리지 않았다 |
