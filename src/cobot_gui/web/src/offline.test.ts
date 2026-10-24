import { describe, expect, it } from "vitest";

// 현장은 인터넷이 없다(CLAUDE.md §3-7). 소스에 외부 주소가 들어가면 실패한다.
const sources = import.meta.glob<string>("/src/**/*.{ts,tsx,css}", {
  query: "?raw",
  import: "default",
  eager: true,
});

export function findExternalUrls(text: string): string[] {
  return text.match(/https?:\/\/[^\s"'`)<>]+/g) ?? [];
}

describe("외부 주소 검사", () => {
  it("검사 함수는 CDN 주소를 찾는다 (음성 대조)", () => {
    expect(findExternalUrls('<link href="https://fonts.googleapis.com/css2?family=X">')).toHaveLength(1);
    expect(findExternalUrls("@import url(http://cdn.example.com/a.css)")).toHaveLength(1);
    expect(findExternalUrls("외부 주소가 없는 문장")).toHaveLength(0);
  });

  it("소스 파일에 외부 주소가 없다", () => {
    const found: string[] = [];
    for (const [path, text] of Object.entries(sources)) {
      if (path.endsWith(".test.ts") || path.endsWith(".test.tsx")) continue;
      for (const url of findExternalUrls(text)) found.push(`${path}: ${url}`);
    }
    expect(found).toEqual([]);
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });
});
