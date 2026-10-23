// package-lock.json 에서 docs/fms_web_dependencies.md 를 만든다 (새 의존성 허락 요청용 목록).
// 같은 lock 에서는 늘 같은 바이트가 나온다. --check 는 파일을 쓰지 않고 차이만 본다.
// 실행 번들에 들어가는 패키지의 라이선스가 허용 목록 밖이면 --check 가 실패한다.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ALLOWED = ["MIT", "ISC", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD"];
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const DOC = join(root, "..", "..", "..", "docs", "fms_web_dependencies.md");

export function build(lock, pkg) {
  const direct = new Set([...Object.keys(pkg.dependencies ?? {}), ...Object.keys(pkg.devDependencies ?? {})]);
  const prod = [];
  const devLicenses = {};
  let devCount = 0;
  for (const [key, value] of Object.entries(lock.packages)) {
    if (!key) continue;
    const name = key.split("node_modules/").pop();
    const license = value.license ?? "(없음)";
    if (value.dev) {
      devCount += 1;
      devLicenses[license] = (devLicenses[license] ?? 0) + 1;
    } else {
      prod.push({ name, version: value.version, license, direct: !!pkg.dependencies?.[name] });
    }
  }
  prod.sort((a, b) => a.name.localeCompare(b.name));
  const outside = prod.filter((item) => !ALLOWED.includes(item.license));
  const lines = [
    "# FMS 웹 의존성 목록 (자동 생성)",
    "",
    "> 자동 생성 문서다. 직접 고치지 말 것. 원본: `src/cobot_gui/web/package-lock.json`.",
    "> 재생성: `cd src/cobot_gui/web && node scripts/gen-dependencies.mjs`. 확인: `--check`.",
    "",
    "CLAUDE.md §9 는 허락 없이 새 의존성을 추가하지 못하게 한다. 이 문서는 허락을 받을 때 보이는 목록이다.",
    "버전은 `package-lock.json` 이 고정한다. 설치는 `npm ci` 로만 한다.",
    "",
    "## 요약",
    "",
    "| 구분 | 수 |",
    "|---|---|",
    `| 직접 의존성 (실행 번들) | ${Object.keys(pkg.dependencies ?? {}).length} |`,
    `| 실행 번들에 들어가는 패키지 (간접 포함) | ${prod.length} |`,
    `| 빌드·시험 도구 (번들에 안 들어감, 간접 포함) | ${devCount} |`,
    `| 허용 목록 밖 라이선스 (실행 번들) | ${outside.length} |`,
    "",
    `허용 목록: ${ALLOWED.join(", ")}`,
    "",
    "## 빌드·시험 도구의 라이선스 분포",
    "",
    "| 라이선스 | 패키지 수 |",
    "|---|---|",
    ...Object.entries(devLicenses).sort().map(([license, count]) => `| ${license} | ${count} |`),
    "",
    "## 실행 번들에 들어가는 패키지",
    "",
    "| 패키지 | 버전 | 라이선스 | 직접 |",
    "|---|---|---|---|",
    ...prod.map((item) => `| ${item.name} | ${item.version} | ${item.license} | ${item.direct ? "예" : ""} |`),
    "",
  ];
  return { text: lines.join("\n"), outside };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const lock = JSON.parse(readFileSync(join(root, "package-lock.json"), "utf8"));
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  const { text, outside } = build(lock, pkg);
  if (outside.length > 0) {
    console.error(`허용 목록 밖 라이선스: ${outside.map((i) => `${i.name} (${i.license})`).join(", ")}`);
    process.exit(1);
  }
  if (process.argv.includes("--check")) {
    const current = existsSync(DOC) ? readFileSync(DOC, "utf8") : null;
    if (current !== text) {
      console.error("불일치: docs/fms_web_dependencies.md 가 package-lock.json 과 다르다. 재생성: node scripts/gen-dependencies.mjs");
      process.exit(1);
    }
    console.log("일치: docs/fms_web_dependencies.md");
  } else {
    writeFileSync(DOC, text, "utf8");
    console.log(`썼다: ${DOC}`);
  }
}
