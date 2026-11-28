# Isaac Sim 원격 실행 실패 회고

작성일: 2026-11-25   
대상: `team11@100.97.16.25` 원격 PC, Isaac Sim 6.2.0 WebRTC 스트리밍 시도

## 결론

이번 실패는 Isaac Sim 모델이나 강화학습 정책의 성능을 검증하다가 실패한 것이 아니다. 설치 파일을 받는 과정에서 긴 네트워크 중단이 있었고, 설치가 끝난 뒤에는 WebRTC 스트리밍 세션이 시작되지 않았다. 마지막으로 확인한 원격 PC의 메모리는 `15 GiB` 중 사용 `5.2 GiB`, 사용 가능 `9.8 GiB`, 스왑 `4.0 GiB`였다. 따라서 현재 로그만으로는 “RAM 부족으로 커널이 죽었다”고 단정할 수 없다.

프로젝트의 주 시뮬레이터는 MuJoCo로 유지한다. Isaac Sim은 16 GiB급 GPU와 원격 스트리밍 네트워크를 동시에 요구하므로, 이번 작업의 검증 경로로 사용하지 않는다.

## 확인된 시간순 기록

1. 첫 `wget` 다운로드가 SSH 연결 끊김(`client_loop: send disconnect: Broken pipe`)으로 중단됐다. 당시 부분 파일은 약 `3.1G`였다.
2. 재시작한 `wget`도 약 `197.52M`에서 다시 연결이 끊겼다.
3. `aria2c --continue=true --split=8`로 재개했다. `.aria2` 상태 파일을 보존하면서 부분 파일을 이어받았고, 속도가 수십 KiB/s까지 내려가 ETA가 수십~수백 시간으로 튀었다.
4. 다운로드는 최종적으로 완료됐다. 원격 `ID:100` 터미널에서 다음 검사가 통과했다.

   ```text
   unzip -t ~/isaacsim/isaac-sim-6.2.0.zip.new
   No errors detected in compressed data
   ```

5. 압축을 풀고 `/home/team11/isaacsim/isaac-sim-6.2.0/isaac-sim.streaming.sh`가 존재하는 것을 확인했다.
6. 원격 PC에서 Isaac Sim Full Streaming App이 로드됐다. 확인된 로그에는 다음이 있었다.

   ```text
   Isaac Sim Full Streaming Version: 6.2.0-rc.14
   Isaac Sim Full Streaming App is loaded.
   ```

7. 로컬 WebRTC 클라이언트는 `100.97.16.25`, signal `49100`, stream `47998`로 접속을 시도했다. 여섯 번의 스트림 시작 시도가 실패했고 최종 오류는 다음이었다.

   ```text
   Stream start failed
   Session start failed with error: "Sign in request timed out."
   ```

8. 이후 SSH 재접속은 가능했다. 당시 원격 PC의 상태는 다음과 같았다.

   ```text
   Mem: 15Gi total, 5.2Gi used, 1.0Gi free, 9.8Gi available
   Swap: 4.0Gi total, 636Ki used, 4.0Gi free
   GPU: RTX 5080 16GB, 230MiB used, 0% utilization
   ```

## 원인 분리

### 확정된 원인

- 대용량 설치 파일을 일반 SSH 세션에서 직접 `wget`으로 받으면서 SSH 연결이 여러 번 끊겼다.
- WebRTC 스트리밍 세션은 signal/stream 포트로 연결되지 않았고, sign-in timeout으로 종료됐다.
- Isaac Sim을 켜는 터미널과 다운로드 터미널을 혼동하면서 프로세스 확인과 중단 조작이 어려웠다.

### 가능성이 높은 원인

- `100.97.16.25`가 원격 PC의 Tailscale/사설 주소일 경우, WebRTC의 UDP stream 포트가 로컬 PC까지 열리지 않았을 수 있다.
- 원격 GUI 세션, GNOME 원격 데스크톱, Isaac Sim renderer가 동시에 실행되면서 스트리밍 초기화가 불안정했을 수 있다.
- Isaac Sim은 GPU 메모리보다 시스템 RAM과 renderer 초기화 비용의 영향을 크게 받으므로, 16 GiB RAM 환경에서 여유가 작다.

### 아직 입증되지 않은 주장

다음 로그를 확보하기 전에는 OOM killer, NVIDIA Xid, 커널 패닉을 원인으로 쓰지 않는다.

```bash
# 실행 위치: 원격 PC의 형광 초록 tmux가 아닌 일반 (ID:100)team11 셸
dmesg -T | grep -Ei 'oom|out of memory|killed process|nvrm|xid|gpu|segfault|panic'
journalctl -k -b -1 --no-pager | grep -Ei 'oom|killed process|nvrm|xid|panic'
```

`dmesg -T | gr`는 `grep` 오타라서 로그를 조회하지 못한 명령이다.

## 재발 방지

### 다운로드

- 대용량 파일은 원격 PC의 `tmux` 안에서 `aria2c --continue=true`로만 받는다.
- 다운로드 완료 전에는 `.aria2` 파일을 삭제하지 않는다.
- 완료 판정은 파일 크기가 아니라 `unzip -t`의 `No errors detected in compressed data`로 한다.

### Isaac Sim

- 다음 실행에서는 WebRTC보다 원격 PC 로컬 화면 또는 headless/offscreen 실행을 우선한다.
- 스트리밍을 써야 한다면 signal/stream 포트의 양방향 연결을 먼저 확인하고, Isaac Sim renderer만 단독으로 실행한다.
- 16 GiB RAM 원격 PC에서는 Isaac Sim과 강화학습을 같은 세션에서 동시에 실행하지 않는다.

### 프로젝트 방향

- 실제 작업 정책 학습과 접촉 보정은 MuJoCo v026에서 진행한다.
- Isaac Sim 설치 파일은 실패 원인 분석용으로만 보관한다.
- MuJoCo 결과에는 `physical grasp`, `proxy latch`, `kinematic replay`를 구분해 기록한다. 프록시 래치 성공을 실제 로봇 성공으로 표현하지 않는다.

## 회고용 한 문장

> Isaac Sim 설치 자체는 압축 검사까지 통과했지만, 16 GiB급 원격 환경에서 대용량 다운로드와 WebRTC 스트리밍을 순차적으로 운영하는 과정이 불안정했고, sign-in timeout으로 실험 화면에 도달하지 못했다. 커널 OOM 여부는 관련 로그를 확보하기 전까지 미확정으로 남긴다.

