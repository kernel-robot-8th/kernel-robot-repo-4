# 도커로 빌드·시험하기 (처음 쓰는 사람용)

- 상태: 초안 (2026-10-22). 팀 리뷰 전이다.
- 검증: Linux PC 한 대(Ubuntu 22.04, Docker 29.2.1, amd64)에서 3·4·6·7장 명령과 5장 오류 문구 일부(도커 데몬 없음·docker 명령 없음·CRLF·사용자 번호 다름)를 실제로 돌려 확인했다 (2026-10-22).
  아직 확인하지 않은 것: 2장 설치 절차, Windows(WSL)·macOS 에서 `dev.sh` 실행, `sudo` 로 실행하기, `build-image` 의 새 기본 이미지 받기(`--pull`). `dev.ps1` 은 Windows 에서 안내 출력만 확인했다.
- 대상: 도커를 처음 쓰는 팀원. ROS 를 직접 설치한 사람은 안 써도 된다 (9장 FAQ).
- 도구: [`scripts/docker/dev.sh`](../scripts/docker/dev.sh) (Linux·macOS·WSL), [`scripts/docker/Dockerfile`](../scripts/docker/Dockerfile), [`scripts/docker/dev.ps1`](../scripts/docker/dev.ps1) (Windows 안내용)
- 오프라인 반입 목록: [`docs/fms_offline_bundle.md`](fms_offline_bundle.md)
- 팀 규칙의 정본은 [`CLAUDE.md`](../CLAUDE.md) 다. 겹치는 내용은 CLAUDE.md 를 따른다.

## 바쁜 사람용 (설치가 끝났다면)

```bash
cd <ws>                                    # 레포 루트
bash scripts/docker/dev.sh build-image     # 처음 한 번 (인터넷 필요)
bash scripts/docker/dev.sh test            # 빌드 + 시험 + 결과
```

## 목차

1. [도커가 무엇이고 왜 쓰나](#1-도커가-무엇이고-왜-쓰나)
2. [설치](#2-설치) — [Ubuntu 24.04](#21-ubuntu-2404) · [Windows](#22-windows) · [macOS](#23-macos)
3. [처음 한 번: 이미지 만들기](#3-처음-한-번-이미지-만들기)
4. [매일 쓰는 명령](#4-매일-쓰는-명령)
5. [자주 나는 오류와 해결](#5-자주-나는-오류와-해결)
6. [정리 (지우기)](#6-정리-지우기)
7. [오프라인 반입](#7-오프라인-반입)
8. [하지 말 것](#8-하지-말-것)
9. [FAQ](#9-faq)

## 1. 도커가 무엇이고 왜 쓰나

- 도커는 프로그램이 설치된 리눅스 환경을 통째로 묶어 어느 PC 에서나 똑같이 켜 주는 도구다.
- 우리 팀 이미지에는 Ubuntu 24.04 + ROS 2 Jazzy + 빌드·린트 도구가 들어 있다.
- 그래서 ROS 를 설치하지 않은 PC(Windows·macOS 포함)에서도 같은 Jazzy 환경으로 `colcon build`·`colcon test` 를 돌릴 수 있다.
- 모두 같은 환경을 쓰니 "내 PC 에서는 됐는데" 가 줄고, PR 전에 깨끗한 환경에서 시험할 수 있다.
- 이 도구는 빌드와 시험만 한다. 실물 로봇·장치는 연결하지 않는다 (8장).

말 정리:

| 말 | 뜻 |
|---|---|
| 이미지 | 설치가 끝난 환경의 틀. 한 번 만들어 두고 계속 쓴다. 이름 예: `cobot-dev:jazzy-20261022` |
| 컨테이너 | 이미지로 잠깐 켠 환경. `dev.sh` 는 명령이 끝나면 컨테이너를 지운다 (`--rm`). |
| 마운트 | 내 PC 의 레포 폴더를 컨테이너 안 `/ws` 로 같이 보는 것. 내 편집기로 고친 파일이 바로 보인다. |

## 2. 설치

> AI 에이전트는 이 장의 `sudo`·`apt` 명령을 사용자 확인 없이 실행하지 않는다 (CLAUDE.md §9).
> 명령은 바뀔 수 있다. 막히면 Docker 공식 설치 문서를 우선한다.

### 2.1 Ubuntu 24.04

공식 Docker Engine apt 저장소로 설치한다. 관리자 권한(`sudo`)이 필요하다.

```bash
# 1) 예전에 깔린 비공식 패키지가 있으면 지운다 (없으면 '설치 안 됨' 이 나와도 괜찮다)
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove "$pkg"
done

# 2) Docker 저장소 등록
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3) 설치와 확인
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker run --rm hello-world      # 'Hello from Docker!' 가 나오면 성공
```

`sudo` 없이 쓰려면 docker 그룹에 들어간다.

```bash
sudo usermod -aG docker "$USER"
# 로그아웃 후 다시 로그인한다 (또는 재부팅)
docker run --rm hello-world
```

- 보안 주의: docker 그룹에 든 사용자는 사실상 root 와 같은 권한을 갖는다. 컨테이너로 PC 의 모든 파일을 열 수 있기 때문이다.
- 그래서 docker 그룹은 **본인 개발 PC 에서만** 쓴다. 공용 PC·현장 PC 에는 넣지 않는다.
- 그룹에 넣지 않았다면 `sudo bash scripts/docker/dev.sh ...` 로 실행해도 된다. `dev.sh` 는 sudo 로 돌 때도 파일 주인을 원래 사용자로 맞춘다. `build`·`test` 가 만든 파일, `save` 가 만든 tar·`.sha256` 모두 그렇다. `save` 에 폴더를 안 적으면 원래 사용자의 홈 아래 `cobot_offline_bundle` 에 저장한다 (sudo 로 실행하기는 아직 실연 검증 전).

### 2.2 Windows

Windows 에서는 **WSL2 의 Ubuntu 안에서** `dev.sh` 를 쓴다. 레포도 WSL 안에 clone 한다.

0. 먼저 CPU 가상화가 켜져 있는지 본다. 작업 관리자(Ctrl+Shift+Esc) → 성능 → CPU 의 '가상화' 가 '사용' 이어야 한다. '사용 안 함' 이면 5장 '도커가 안 켜짐' 의 가상화 항목을 본다.
1. 관리자 PowerShell 을 열고 WSL 과 Ubuntu 24.04 를 설치한 뒤 재부팅한다.
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
2. 시작 메뉴에서 "Ubuntu 24.04" 를 연다. 처음 열 때 리눅스 사용자 이름과 암호를 만든다 (Windows 암호와 따로다).
3. Docker Desktop for Windows 를 설치한다. 설치 중 "Use WSL 2" 를 고른다.
   - 회사 PC 라면 Docker Desktop 라이선스 조건(회사 규모에 따라 유료)을 먼저 확인한다.
4. Docker Desktop → Settings → Resources → WSL integration 에서 `Ubuntu-24.04` 를 켜고 Apply 한다.
5. Ubuntu 터미널에서 확인한다. `Client` 와 `Server` 가 둘 다 나오면 된다.
   ```bash
   docker version
   ```
6. Ubuntu 터미널에서 레포를 **WSL 홈 아래에** clone 한다. `<ws>` 는 원하는 폴더 이름이다.
   ```bash
   git config --global core.autocrlf input
   cd ~
   git clone <저장소 주소> <ws>
   cd <ws>
   ```
7. 편집은 VS Code 의 "WSL" 확장으로 한다. Ubuntu 터미널의 레포 폴더에서 `code .` 를 치면 열린다.
   탐색기로 볼 때 주소는 `\\wsl.localhost\Ubuntu-24.04\home\<리눅스 사용자>\<ws>` 다.

왜 WSL 안에 clone 하나:

- 줄끝: Windows 의 Git 은 받을 때 줄끝을 CRLF 로 바꾸기도 한다. 그러면 `.sh` 가 리눅스에서 돌지 않는다. 레포는 `scripts/docker/.gitattributes` 로 이 폴더의 줄끝을 LF 로 고정해 두었지만, 다른 파일도 있으니 WSL 안에 clone 하기를 권한다.
- 속도: `C:` 드라이브(`/mnt/c`)의 파일을 컨테이너가 읽으면 많이 느리다.
- 권한: Windows 드라이브에서는 리눅스 실행 권한이 지켜지지 않는다.

`dev.ps1` 은 무엇인가:

- `dev.ps1` 은 **아무것도 실행하지 않는 안내용**이다. WSL·Docker Desktop 이 있는지, 레포가 어디 있는지 보고 다음에 칠 명령을 알려 준다.
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\docker\dev.ps1 test
  ```
  (`-ExecutionPolicy Bypass` 는 이 한 번의 실행에만 적용된다. 시스템 설정은 바뀌지 않는다.)
- PowerShell 판 `dev.sh` 를 따로 만들지 않은 이유:
  1. 모든 OS 가 같은 `dev.sh` 하나를 쓰면 방법이 하나라 덜 헷갈린다. 두 스크립트가 따로 고쳐지다 동작이 달라지는 일도 없다.
  2. PowerShell 판은 `C:` 에 clone 한 레포에서 돌리게 만든다. 바로 위의 줄끝·속도·권한 문제가 그 설정에서 난다.
  3. `save`·`load` 에 주는 경로가 Windows 경로(`D:\usb`)와 WSL 경로(`/mnt/d/usb`)로 갈려서 헷갈린다.
  4. Windows 는 기본 설정에서 `.ps1` 실행을 막기도 한다 (실행 정책).

### 2.3 macOS

1. Docker Desktop for Mac 을 설치한다. 칩에 맞는 것(Apple Silicon 또는 Intel)을 고른다.
   - 회사 PC 라면 Docker Desktop 라이선스 조건을 먼저 확인한다.
2. Docker Desktop 을 켜고 위쪽 메뉴 막대의 고래 아이콘이 멈출 때까지 기다린다.
3. 터미널에서 확인한다.
   ```bash
   docker version
   ```
4. 레포는 `/Users/<이름>/` 아래에 둔다. Docker Desktop 이 기본으로 공유하는 곳이다.

- Apple Silicon(M 칩) 에서는 이미지가 **arm64** 로 만들어진다. ROS 공식 이미지가 arm64 를 지원해서 그대로 빠르게 돈다.
- arm64 이미지 tar 는 일반 Intel/AMD PC(amd64)에서 쓰지 않는다. 반대도 같다 (7장).
- `--platform linux/amd64` 로 강제로 바꾸지 않는다. 흉내 실행이라 매우 느리다.

## 3. 처음 한 번: 이미지 만들기

레포 루트에서 한 번 실행한다. 인터넷이 필요하고 처음에는 몇 분 걸린다.

```bash
cd <ws>
bash scripts/docker/dev.sh build-image
docker image ls cobot-dev              # 만들어진 이미지 확인
```

- 이미지 이름(태그) 규칙: `cobot-dev:jazzy-<YYYYMMDD>`. 날짜는 `dev.sh` 의 `IMAGE_VERSION` 이다. 지금 값은 `bash scripts/docker/dev.sh help` 맨 아래에 나온다.
- Dockerfile 이 바뀌면 그 PR 이 날짜도 바꾼다. 그러면 `dev.sh` 가 "이미지가 없다" 고 알려 주니 다시 `build-image` 를 한다.
- 이미지 안 사용자는 지금 PC 사용자와 같은 번호(UID)로 만든다. 그래서 컨테이너가 만든 파일의 주인이 내 계정이 된다. (macOS 는 Docker Desktop 이 파일 주인을 알아서 맞춰서 1000 을 쓴다.)
- 레포 파일은 이미지에 들어가지 않는다. 빌드 재료는 `scripts/docker/` 폴더뿐이다.

## 4. 매일 쓰는 명령

모두 레포 루트(`cd <ws>`)에서 친다. 파일 편집은 평소처럼 내 PC 의 편집기로 한다. git 도 컨테이너 밖에서 한다.

| 하고 싶은 일 | 명령 |
|---|---|
| 전체 빌드 + 시험 + 결과 | `bash scripts/docker/dev.sh test` |
| 한 패키지만 빌드 + 시험 | `bash scripts/docker/dev.sh test --packages-select cobot_gui` |
| 빌드만 | `bash scripts/docker/dev.sh build` |
| 의존 패키지까지 빌드 | `bash scripts/docker/dev.sh build --packages-up-to cobot_gui` |
| 빌드는 건너뛰고 시험만 | `bash scripts/docker/dev.sh test --no-build --packages-select cobot_gui` |
| 컨테이너 안에 들어가서 직접 | `bash scripts/docker/dev.sh shell` |

`test` 가 하는 일:

1. `colcon build --symlink-install` (CLAUDE.md §5 와 같은 옵션)
2. 지난 시험 결과를 지우고 `colcon test` (린트 `ament_flake8`·`ament_pep257`·`ament_copyright` 포함)
3. `colcon test-result --verbose` 로 결과를 보여 준다.
4. 아래 중 하나라도 있으면 **실패**로 끝난다 (종료 코드 1):
   - 실패·오류가 있다.
   - skip 이 있다. skip 은 통과가 아니다. 일부러 넘길 때만 `--allow-skip` 을 붙이고 PR 에 이유를 적는다.
   - 실행된 시험이 0개다.

`shell` 로 들어가서 직접 할 때 (CLAUDE.md §5 의 명령 그대로):

```bash
bash scripts/docker/dev.sh shell
# 아래는 컨테이너 안
colcon build --symlink-install --packages-select cobot_gui
source install/setup.bash
colcon test --packages-select cobot_gui
colcon test-result --verbose
exit                                  # 나가기
```

알아 둘 것:

- 컨테이너는 기본으로 **네트워크 없이** 돈다 (`--network none`). 빌드·시험에는 인터넷이 필요 없다. 꼭 필요할 때만 `--online` 을 붙인다 (예: `bash scripts/docker/dev.sh shell --online`).
- 빌드 산출물 `build/`·`install/`·`log/` 는 레포 폴더에 생긴다. `.gitignore` 대상이라 커밋되지 않는다. 그래도 `git status` 에 보이면 커밋하지 말고 알린다.
- 옵션 순서는 상관없다. `dev.sh` 옵션(`--online`·`--no-build`·`--allow-skip`)을 빼고 나머지는 colcon 에 그대로 넘긴다.
- `build`·`test` 에는 패키지 고르기 옵션(`--packages-select`·`--packages-up-to`)만 쓴다. 다른 colcon 옵션은 `shell` 안에서 직접 쓴다.

## 5. 자주 나는 오류와 해결

**권한 거부** — `permission denied while trying to connect to the Docker daemon socket`

- Ubuntu: docker 그룹에 넣은 뒤 로그아웃·로그인을 안 했다. 다시 로그인한다. 또는 `sudo bash scripts/docker/dev.sh ...` 로 실행한다 (2.1 의 보안 주의).
- `groups` 를 쳐서 `docker` 가 보이는지 확인한다.

**도커가 안 켜짐** — `Cannot connect to the Docker daemon` / `dev.sh` 가 "docker 데몬에 연결하지 못했다"

- Windows·macOS: Docker Desktop 을 켜고 고래 아이콘이 멈출 때까지 기다린다.
- Windows: Docker Desktop → Settings → Resources → WSL integration 에서 Ubuntu 가 켜져 있는지 본다.
- Windows 가상화: CPU 가상화가 꺼져 있으면 WSL2 와 Docker Desktop 이 모두 뜨지 못한다. 흔한 문구는 `0x80370102`(WSL 설치·실행), `Virtualization support not detected`(Docker Desktop) 다.
  - 확인: 작업 관리자 → 성능 → CPU 의 '가상화' 가 '사용' 인지 본다. PowerShell 에서 `wsl --status` 를 쳐서 기본 버전이 2 인지도 본다.
  - 해결: PC 를 다시 켜면서 BIOS/UEFI 설정에 들어가 Intel 은 'VT-x'(Intel Virtualization Technology), AMD 는 'SVM'(AMD-V) 을 켠다. 들어가는 키와 메뉴 이름은 PC 제조사마다 다르다. 회사·학교 PC 는 관리자에게 묻는다.
- Ubuntu: `sudo systemctl start docker` 를 한다.

**docker 명령이 없음** — `dev.sh` 가 "docker 명령이 없다"

- 2장대로 설치한다. Windows 는 Ubuntu 터미널에서 `docker version` 이 되는지 본다.

**CRLF (줄끝)** — `$'\r': command not found`, `set: pipefail\r: invalid option name`, `/usr/bin/env: 'bash\r'`, 또는 `dev.sh` 가 "Dockerfile 의 줄끝이 CRLF 다"

- 레포를 Windows Git 으로 받아서 줄끝이 바뀌었다. 레포가 `scripts/docker/.gitattributes` 로 LF 를 고정하기 전에 받았거나, 파일을 다른 도구로 복사했을 때 난다.
- 가장 쉬운 해결: 2.2 대로 WSL 안에서 새로 clone 한다.
- 이미 받은 레포를 고치려면 (고치지 않은 내 작업이 없을 때만):
  ```bash
  git config core.autocrlf input
  rm scripts/docker/dev.sh scripts/docker/Dockerfile
  git checkout -- scripts/docker/dev.sh scripts/docker/Dockerfile
  ```

**실행 권한** — `./scripts/docker/dev.sh: Permission denied`

- 이 가이드는 늘 `bash scripts/docker/dev.sh ...` 로 실행한다. 이렇게 치면 실행 권한이 없어도 된다.

**Git Bash 에서 실행** — `dev.sh` 가 "Git Bash 에서는 쓰지 않는다"

- Git Bash 는 경로를 바꿔 넘겨서 마운트가 엉뚱한 곳으로 간다. Ubuntu(WSL) 터미널에서 실행한다.

**root 로 실행** — `dev.sh` 가 "root 사용자로는 쓰지 않는다"

- WSL 이 root 로 열린다면 일반 사용자를 만들고 기본 사용자로 정한다 (PowerShell 에서 `wsl -d Ubuntu-24.04 -u root` 로 들어가 `adduser <이름>` 후, `/etc/wsl.conf` 의 `[user]` 에 `default=<이름>` 을 적고 `wsl --shutdown`). 잘 모르면 팀에 묻는다.

**파일 주인이 root** — `clean` 이 "지우지 못했다", 또는 `build/` 에 쓰기 오류

- 예전에 컨테이너를 root 로 돌려서 root 소유 파일이 남았다. 주인을 내 계정으로 되돌린다 (내 레포 안의 산출물만 대상):
  ```bash
  sudo chown -R "$(id -u):$(id -g)" build install log
  ```

**이미지와 사용자 번호가 다름** — `dev.sh` 가 "이미지 사용자(...)와 지금 사용자(...)가 다르다"

- 다른 PC 에서 만든 이미지를 불러왔거나 계정이 바뀌었다. `build`·`test` 는 이번 실행을 맞춰서 돈다. 인터넷이 되면 `bash scripts/docker/dev.sh build-image` 로 다시 만든다.
- 이때 `shell` 은 홈 폴더가 `/tmp` 로 바뀐 채 열린다. 그래서 첫 안내 문구가 안 나오고, 프롬프트가 `I have no name!` 으로 보이고, `rosdep` 이 캐시를 못 찾는다. `colcon`·`ros2` 는 그대로 쓸 수 있다 (ROS 환경은 기본 이미지의 시작 스크립트가 잡는다). 이상하면 셸 안에서 `source /opt/ros/jazzy/setup.bash` 를 한 번 친다.

**CMake 캐시 경로 오류** — `The current CMakeCache.txt directory ... is different`

- 내 PC 에서 직접 빌드한 `build/` 와 컨테이너 빌드(`/ws/...`)가 섞였다. `bash scripts/docker/dev.sh clean` 뒤 다시 빌드한다.

**포트·볼륨**

- `dev.sh` 는 포트를 열지 않는다. "port is already allocated" 는 다른 도커 명령에서 난 것이다. 웹 화면을 컨테이너에서 띄우는 규칙은 아직 정하지 않았다 (S2 이후).
- macOS 에서 `Mounts denied` 가 나면 레포를 `/Users/` 아래로 옮기거나, Docker Desktop → Settings → Resources → File sharing 에 레포 폴더를 더한다.
- Windows 에서 컨테이너가 레포 파일을 못 보거나 매우 느리면 레포가 `C:` 에 있는 것이다. 2.2 대로 WSL 안에 clone 한다.

**디스크 부족** — `no space left on device`

```bash
docker system df                 # 무엇이 자리를 차지하는지 본다
docker image prune               # 이름 없는(낡은) 이미지 지우기
docker builder prune             # 빌드 캐시 지우기
```

- Windows·macOS 는 Docker Desktop → Settings → Resources 에서 디스크 크기를 늘릴 수 있다.

**프록시·오프라인** — `build-image` 중 `Temporary failure resolving`, `TLS handshake timeout`, 기본 이미지 받기 실패

- `build-image` 는 인터넷이 필요하다 (기본 이미지와 apt 패키지를 받는다).
- 프록시가 있는 곳: `HTTP_PROXY`·`HTTPS_PROXY`·`NO_PROXY` 환경 변수가 있으면 `dev.sh` 가 빌드에 넘긴다. 기본 이미지 받기는 도커 자체의 프록시 설정을 따른다 (Docker Desktop → Settings → Resources → Proxies, Ubuntu 는 Docker 공식 문서의 데몬 프록시 설정).
- 암호가 들어간 프록시 주소는 쓰지 않는다 (8장 비밀값).
- 인터넷이 아예 없는 곳: 인터넷 되는 PC 에서 만든 이미지를 7장대로 가져온다.

**CPU 종류가 다름** — `exec format error`

- arm64(Apple Silicon) 이미지를 amd64 PC 에서 쓰거나 그 반대다. 그 PC 에서 `build-image` 를 하거나, 같은 CPU 종류로 만든 tar 를 가져온다.

## 6. 정리 (지우기)

```bash
bash scripts/docker/dev.sh clean            # build/ install/ log/ 지우기 (지우기 전에 물어본다)
bash scripts/docker/dev.sh clean --image    # 위 + 팀 이미지도 지우기
```

- `clean` 은 레포 루트의 `build/`·`install/`·`log/` 만 지운다. 소스는 건드리지 않는다.
- 물어보지 않고 지우려면 `--yes` 를 붙인다. AI 에이전트는 사용자 확인 없이 붙이지 않는다 (CLAUDE.md §5·§9).

직접 볼 때:

```bash
docker image ls cobot-dev                     # 팀 이미지 목록
docker image rm cobot-dev:jazzy-20261022      # 한 이미지 지우기 (태그는 위 목록에서)
docker ps -a                                  # 남은 컨테이너 (dev.sh 는 --rm 이라 보통 없다)
docker container prune                        # 멈춘 컨테이너 지우기
docker builder prune                          # 빌드 캐시 지우기
```

- `docker system prune -a` 는 **다른 프로젝트 이미지까지 모두** 지운다. 공용 PC 에서는 쓰지 않는다.

## 7. 오프라인 반입

인터넷이 없는 PC 로 이미지를 옮길 때 쓴다. 번들 전체 목록과 검증 방법은 [`docs/fms_offline_bundle.md`](fms_offline_bundle.md) 에 있다.

인터넷 되는 PC (가져갈 PC 와 CPU 종류가 같아야 한다):

```bash
bash scripts/docker/dev.sh build-image
bash scripts/docker/dev.sh save ~/cobot_offline_bundle
ls ~/cobot_offline_bundle
# cobot-dev_jazzy-20261022_amd64.tar
# cobot-dev_jazzy-20261022_amd64.tar.sha256
```

- 두 파일을 **함께** USB 등으로 옮긴다. 레포 안에는 저장하지 않는다 (`dev.sh` 가 막는다. 큰 파일은 커밋 금지, CLAUDE.md §3-1).
- 파일 이름 끝의 `amd64`·`arm64` 가 CPU 종류다.

인터넷 없는 PC (도커는 설치돼 있어야 한다. 도커가 없는 오프라인 PC 용 설치 파일 묶음은 번들 문서의 A-0 이고 아직 미검증이다. 그런 PC 가 있으면 팀에 먼저 알린다):

```bash
bash scripts/docker/dev.sh load /media/<사용자>/<USB>/cobot-dev_jazzy-20261022_amd64.tar
bash scripts/docker/dev.sh test             # 기본이 네트워크 없음
```

- `load` 는 먼저 `.sha256` 으로 tar 가 깨지지 않았는지 확인한다. `.sha256` 이 없거나 값이 다르면 불러오지 않고 실패한다.
- 손으로 확인하려면 tar 가 있는 폴더에서 `sha256sum -c cobot-dev_jazzy-20261022_amd64.tar.sha256` (macOS: `shasum -a 256 -c ...`) 를 친다. `OK` 가 나와야 한다.
- 레포는 git 번들이나 USB 로 따로 옮긴다. 이미지에는 레포가 들어 있지 않다.

## 8. 하지 말 것

- **실물 장치를 컨테이너에 연결하지 않는다.** 시리얼(`/dev/ttyUSB*`·`/dev/ttyACM*`), 카메라(`/dev/video*`), `--device`, `-v /dev:/dev` 는 이 가이드 범위 밖이다. 실물 구동은 CLAUDE.md §9 (사용자 확인) 와 장치 담당 패키지 규칙을 따른다.
- **`--privileged` 를 쓰지 않는다.** 컨테이너가 PC 의 모든 장치와 커널 권한을 갖게 된다.
- **`--network host` 를 쓰지 않는다.** 컨테이너 안 ROS 노드가 실물 로봇과 같은 네트워크에 붙는다. `dev.sh` 는 기본이 네트워크 없음이고, 이미지도 ROS 탐색을 컨테이너 안(`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`)으로 묶는다.
- **이미지에 비밀값을 넣지 않는다.** Dockerfile 에 토큰·암호·실IP 를 적지 않는다. `--build-arg` 로 비밀값을 넘기지 않는다 (`docker history` 로 보인다). 레포 폴더를 통째로 이미지에 복사하지 않는다.
- **컨테이너 안에서 git push 하거나 자격 증명을 넣지 않는다.** git 은 컨테이너 밖에서 한다.
- **컨테이너 안에서 `apt install` 로 고쳐 쓰지 않는다.** 그 PC 에서만 되는 환경이 된다. 필요한 패키지는 Dockerfile PR 로 더한다 (새 의존성은 팀 허락이 먼저, CLAUDE.md §9).
- 이미지를 공개 저장소(Docker Hub 등)에 올리는 방식은 정하지 않았다. 정하기 전에는 7장의 save/load 로 나눈다.

## 9. FAQ

**Q. 도커를 꼭 써야 하나요?**
아니다. Ubuntu 24.04 에 ROS 2 Jazzy 를 직접 설치했다면 README 와 CLAUDE.md §5 대로 하면 된다. 도커는 ROS 가 없는 PC 에서 같은 환경을 쓰거나, PR 전에 깨끗한 환경에서 시험하고 싶을 때 쓴다.

**Q. 컨테이너 안에서 만든 파일은 어디에 남나요?**
`/ws` 아래는 내 레포 폴더 그 자체라 그대로 남는다. 그 밖(`/home/dev`, `/tmp` 등)은 컨테이너를 나가면 사라진다.

**Q. 이미지는 언제 다시 만드나요?**
`dev.sh` 가 "이미지가 없다" 또는 "Dockerfile 이 바뀌었다" 고 할 때, 그리고 사용자 번호가 다르다는 경고가 나올 때다. `bash scripts/docker/dev.sh build-image` 를 다시 하면 된다.

**Q. 왜 기본이 '네트워크 없음' 인가요?**
두 가지 때문이다. 하나, 빌드·시험이 인터넷 없이 되는지 늘 확인된다 (현장 PC 는 인터넷이 없다고 보고됐다). 둘, 컨테이너 안 노드가 실물 로봇과 섞일 길을 막는다.

**Q. `ROS_DOMAIN_ID` 는 어떻게 하나요?**
컨테이너는 내 PC 의 `ROS_DOMAIN_ID` 를 물려받지 않고 따로 정하지도 않는다. 도메인 규칙은 팀 결정(D2)을 따른다. 컨테이너는 바깥과 ROS 통신을 하지 않게 막혀 있어서 도메인 값과 상관없이 실물과 섞이지 않는다.

**Q. RViz·Gazebo 같은 화면 프로그램도 되나요?**
이 가이드 범위 밖이다. 이미지는 `ros-base`(화면 도구 없음)이고 화면 전달도 설정하지 않았다.

**Q. 주행·비전 패키지도 빌드되나요?**
이미지에는 ROS 기본(`ros-base`)과 빌드·린트 도구만 있다. 다른 의존성(예: Nav2, OpenCV)이 필요한 패키지는 빌드가 실패할 수 있다. `shell` 안에서 `rosdep check --from-paths src --ignore-src` 로 빠진 것을 보고, Dockerfile 에 더하는 PR 을 낸다 (팀 허락 먼저).

**Q. skip 때문에 `test` 가 실패해요.**
`colcon test-result --verbose` 출력에서 skip 된 시험 이름과 이유를 본다. 팀이 받아들인 skip 일 때만 `--allow-skip` 을 붙이고, PR 의 '빌드·시험·린트' 칸에 이유를 적는다.

**Q. 내 PC 와 도커의 린트 결과가 달라요.**
설치된 flake8 플러그인이 다르면 검사 항목이 달라진다. 양쪽에서 `python3 -m flake8 --version` 을 쳐서 플러그인 목록을 비교한다. 다르면 팀에 알린다.

**Q. 컨테이너 안에서 `apt install` 이 안 돼요.**
일부러 막았다. 컨테이너 안 사용자 `dev` 에게 sudo 권한을 주지 않았다 (sudoers 에 없다). 기본 이미지에 `sudo` 명령은 들어 있지만, `dev.sh` 가 `no-new-privileges` 로 돌려서 쳐도 실패한다 (`The "no new privileges" flag is set` 문구가 나온다). 8장을 본다.

**Q. `.venv` 는요?**
컨테이너는 `.venv` 를 쓰지 않는다. 내 PC 에 `.venv` 가 있으면 README 대로 `.venv/COLCON_IGNORE` 가 있어야 colcon 이 그 안을 뒤지지 않는다.

**Q. Windows 에서 `dev.ps1 test` 를 쳤는데 아무 일도 안 일어나요.**
정상이다. `dev.ps1` 은 안내만 하고 종료 코드 1 로 끝난다. 화면에 나온 명령을 Ubuntu(WSL) 터미널에서 친다. 이유는 2.2 에 있다.

**Q. 이미지 크기와 시간은 얼마나 되나요?**
아래는 한 환경에서 잰 값이다 (위 '검증' 의 Linux PC, 2026-10-22). 기본 이미지 `ros:jazzy-ros-base` 는 이미 받아 둔 상태였고, apt 내려받기는 초당 약 5 MB 였다. PC·네트워크마다 다르다.

| 항목 | 잰 값 |
|---|---|
| 이미지 크기 (`docker image ls cobot-dev`) | 디스크 1.43 GB, 압축 327 MB (Docker 버전에 따라 보이는 열이 다르다) |
| 처음 `build-image` | 31 초. 기본 이미지를 처음 받으면 그 시간이 더 든다 (재지 않았다) |
| Dockerfile 이 그대로일 때 다시 `build-image` | 1 초 (캐시) |
| 처음 `build` (전체) | 약 40 초. 대부분 `cobot_interfaces` 메시지 생성이다 (다른 실행에서는 65 초) |
| 그 뒤 `test` (전체, 빌드 포함) | 약 6 초 |
| `save` 로 만든 tar | 약 327 MB (326,920,192 바이트), 5 초 |
| `load` (sha256 확인 포함) | 3 초 |
