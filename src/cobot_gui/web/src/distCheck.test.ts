import { describe, expect, it } from "vitest";

import { findExternalRefs } from "../scripts/dist-check.mjs";

describe("dist 외부 참조 검사", () => {
  it("CDN 스크립트·스타일·글꼴 주소를 찾는다 (음성 대조)", () => {
    expect(findExternalRefs('<script src="https://cdn.example.com/a.js"></script>')).toHaveLength(1);
    expect(findExternalRefs('<link href="//fonts.example.com/x.css">')).toHaveLength(1);
    expect(findExternalRefs("a{background:url(https://example.com/a.png)}")).toHaveLength(1);
  });

  it("같은 서버의 자원은 통과시킨다", () => {
    expect(findExternalRefs('<script src="/assets/index.js"></script>')).toHaveLength(0);
    expect(findExternalRefs("a{background:url(/assets/a.png)}")).toHaveLength(0);
  });
});
