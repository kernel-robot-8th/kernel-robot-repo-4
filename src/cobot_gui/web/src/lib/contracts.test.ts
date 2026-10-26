import { describe, expect, it } from "vitest";

import { CONTRACT_NAMES, MESSAGE_NAMES } from "@/generated/messages";
import { contractOf } from "@/lib/contracts";
import { ACTIVE_MENUS, findMenu } from "@/lib/registry";

describe("메뉴의 데이터 계약", () => {
  it("메시지 정의가 있는 메뉴와 없는 메뉴를 가른다", () => {
    expect(contractOf(findMenu("1.1")!).level).toBe("all");
    expect(contractOf(findMenu("3.3")!).level).toBe("none"); // DatasetSummary 는 정의가 없다 (D12)
    expect(contractOf(findMenu("3.3")!).missing).toContain("DatasetSummary");
    expect(contractOf(findMenu("3.5")!).level).toBe("unnamed");
    expect(contractOf(findMenu("4.1")!).level).toBe("part");
  });

  it("모든 활성 메뉴가 네 가지 중 하나로 갈린다", () => {
    const levels = ACTIVE_MENUS.map((menu) => contractOf(menu).level);
    expect(levels).toHaveLength(34);
    expect(new Set(levels).size).toBeGreaterThanOrEqual(3);
  });

  it("계약 이름 목록은 메시지 이름을 모두 담는다", () => {
    for (const name of MESSAGE_NAMES) expect(CONTRACT_NAMES).toContain(name);
    expect(CONTRACT_NAMES).toContain("QueryAudit");
    expect(CONTRACT_NAMES).toContain("HandoverTask");
  });
});
