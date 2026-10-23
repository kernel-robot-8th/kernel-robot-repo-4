// 빌드 결과(dist)가 밖에서 무언가를 불러오지 않는지 본다 (CLAUDE.md §3-7: 현장은 인터넷이 없다).
// 사용: npm run build && npm run check:dist   (외부 참조가 있으면 종료 코드 1)
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const EXTERNAL = /(?:src|href)\s*=\s*["']\s*(?:https?:)?\/\/[^"']*|url\(\s*["']?\s*(?:https?:)?\/\/[^)"']*/gi;

export function findExternalRefs(text) {
  return text.match(EXTERNAL) ?? [];
}

export function checkDist(dir) {
  const problems = [];
  if (!existsSync(join(dir, "index.html"))) {
    return [`${dir}/index.html 이 없다. 먼저 npm run build`];
  }
  const files = ["index.html"];
  const assets = join(dir, "assets");
  if (existsSync(assets)) {
    for (const name of readdirSync(assets)) if (name.endsWith(".css")) files.push(join("assets", name));
  }
  for (const file of files) {
    for (const ref of findExternalRefs(readFileSync(join(dir, file), "utf8"))) {
      problems.push(`${file}: ${ref}`);
    }
  }
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const problems = checkDist(join(dirname(fileURLToPath(import.meta.url)), "..", "dist"));
  if (problems.length > 0) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log("dist: 외부 참조 없음");
}
