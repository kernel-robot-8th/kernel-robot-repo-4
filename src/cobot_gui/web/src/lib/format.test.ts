import { describe, expect, it } from "vitest";

import { num, timeText, yawDeg, UNMEASURED } from "@/lib/format";

describe("format", () => {
  it("null(미측정)은 0 이 아니라 '미측정' 으로 보인다", () => {
    expect(num(null)).toBe(UNMEASURED);
    expect(num(undefined)).toBe(UNMEASURED);
    expect(num(Number.NaN)).toBe(UNMEASURED);
    expect(num(0, 1, " %")).toBe("0.0 %");
    expect(num(78.46, 1, " %")).toBe("78.5 %");
  });

  it("쿼터니언에서 yaw 를 도로 구한다", () => {
    expect(yawDeg({ x: 0, y: 0, z: 0, w: 1 })).toBeCloseTo(0);
    expect(yawDeg({ x: 0, y: 0, z: 0.7071, w: 0.7071 })).toBeCloseTo(90, 0);
    expect(Math.abs(yawDeg({ x: 0, y: 0, z: 1, w: 0 }) ?? 0)).toBeCloseTo(180, 0);
    expect(yawDeg({ x: 0, y: 0, z: null, w: 1 })).toBeNull();
  });

  it("시각은 UTC 로 보이고 0 은 '없음' 이다", () => {
    expect(timeText({ sec: 0, nanosec: 0 })).toBe("없음");
    expect(timeText({ sec: 1792718100, nanosec: 0 })).toBe("2026-10-23 01:15:00Z");
  });
});
