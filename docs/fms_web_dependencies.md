# FMS 웹 의존성 목록 (자동 생성)

> 자동 생성 문서다. 직접 고치지 말 것. 원본: `src/cobot_gui/web/package-lock.json`.
> 재생성: `cd src/cobot_gui/web && node scripts/gen-dependencies.mjs`. 확인: `--check`.

CLAUDE.md §9 는 허락 없이 새 의존성을 추가하지 못하게 한다. 이 문서는 허락을 받을 때 보이는 목록이다.
버전은 `package-lock.json` 이 고정한다. 설치는 `npm ci` 로만 한다.

## 요약

| 구분 | 수 |
|---|---|
| 직접 의존성 (실행 번들) | 12 |
| 실행 번들에 들어가는 패키지 (간접 포함) | 61 |
| 빌드·시험 도구 (번들에 안 들어감, 간접 포함) | 340 |
| 허용 목록 밖 라이선스 (실행 번들) | 0 |

허용 목록: MIT, ISC, Apache-2.0, BSD-2-Clause, BSD-3-Clause, 0BSD

## 빌드·시험 도구의 라이선스 분포

| 라이선스 | 패키지 수 |
|---|---|
| Apache-2.0 | 17 |
| BSD-2-Clause | 8 |
| BSD-3-Clause | 3 |
| BlueOak-1.0.0 | 1 |
| CC-BY-4.0 | 1 |
| CC0-1.0 | 1 |
| ISC | 15 |
| MIT | 279 |
| MIT-0 | 2 |
| MPL-2.0 | 12 |
| Python-2.0 | 1 |

## 실행 번들에 들어가는 패키지

| 패키지 | 버전 | 라이선스 | 직접 |
|---|---|---|---|
| @floating-ui/core | 1.7.4 | MIT |  |
| @floating-ui/dom | 1.7.5 | MIT |  |
| @floating-ui/react-dom | 2.1.7 | MIT |  |
| @floating-ui/utils | 0.2.10 | MIT |  |
| @radix-ui/primitive | 1.1.3 | MIT |  |
| @radix-ui/react-arrow | 1.1.7 | MIT |  |
| @radix-ui/react-collection | 1.1.7 | MIT |  |
| @radix-ui/react-compose-refs | 1.1.2 | MIT |  |
| @radix-ui/react-context | 1.1.2 | MIT |  |
| @radix-ui/react-dialog | 1.1.15 | MIT | 예 |
| @radix-ui/react-direction | 1.1.1 | MIT |  |
| @radix-ui/react-dismissable-layer | 1.1.11 | MIT |  |
| @radix-ui/react-focus-guards | 1.1.3 | MIT |  |
| @radix-ui/react-focus-scope | 1.1.7 | MIT |  |
| @radix-ui/react-id | 1.1.1 | MIT |  |
| @radix-ui/react-popper | 1.2.8 | MIT |  |
| @radix-ui/react-portal | 1.1.9 | MIT |  |
| @radix-ui/react-presence | 1.1.5 | MIT |  |
| @radix-ui/react-primitive | 2.1.3 | MIT |  |
| @radix-ui/react-primitive | 2.1.4 | MIT |  |
| @radix-ui/react-roving-focus | 1.1.11 | MIT |  |
| @radix-ui/react-separator | 1.1.8 | MIT | 예 |
| @radix-ui/react-slot | 1.2.3 | MIT | 예 |
| @radix-ui/react-slot | 1.2.3 | MIT | 예 |
| @radix-ui/react-slot | 1.2.3 | MIT | 예 |
| @radix-ui/react-slot | 1.2.4 | MIT | 예 |
| @radix-ui/react-slot | 1.2.3 | MIT | 예 |
| @radix-ui/react-tabs | 1.1.13 | MIT | 예 |
| @radix-ui/react-tooltip | 1.2.8 | MIT | 예 |
| @radix-ui/react-use-callback-ref | 1.1.1 | MIT |  |
| @radix-ui/react-use-controllable-state | 1.2.2 | MIT |  |
| @radix-ui/react-use-effect-event | 0.0.2 | MIT |  |
| @radix-ui/react-use-escape-keydown | 1.1.1 | MIT |  |
| @radix-ui/react-use-layout-effect | 1.1.1 | MIT |  |
| @radix-ui/react-use-rect | 1.1.1 | MIT |  |
| @radix-ui/react-use-size | 1.1.1 | MIT |  |
| @radix-ui/react-visually-hidden | 1.2.3 | MIT |  |
| @radix-ui/rect | 1.1.1 | MIT |  |
| @types/react | 19.2.13 | MIT |  |
| @types/react-dom | 19.2.3 | MIT |  |
| aria-hidden | 1.2.6 | MIT |  |
| class-variance-authority | 0.7.1 | Apache-2.0 | 예 |
| clsx | 2.1.1 | MIT | 예 |
| cookie | 1.1.1 | MIT |  |
| csstype | 3.2.3 | MIT |  |
| detect-node-es | 1.1.0 | MIT |  |
| get-nonce | 1.0.1 | MIT |  |
| lucide-react | 0.563.0 | ISC | 예 |
| react | 19.2.4 | MIT | 예 |
| react-dom | 19.2.4 | MIT | 예 |
| react-remove-scroll | 2.7.2 | MIT |  |
| react-remove-scroll-bar | 2.3.8 | MIT |  |
| react-router | 7.18.1 | MIT |  |
| react-router-dom | 7.18.1 | MIT | 예 |
| react-style-singleton | 2.2.3 | MIT |  |
| scheduler | 0.27.0 | MIT |  |
| set-cookie-parser | 2.7.2 | MIT |  |
| tailwind-merge | 3.4.0 | MIT | 예 |
| tslib | 2.8.1 | 0BSD |  |
| use-callback-ref | 1.3.3 | MIT |  |
| use-sidecar | 1.1.3 | MIT |  |
