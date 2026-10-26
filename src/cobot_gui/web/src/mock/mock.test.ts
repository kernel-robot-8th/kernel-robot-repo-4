import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MESSAGE_NAMES } from "@/generated/messages";
import { useMessages } from "@/lib/dataSource";
import { getMock } from "@/mock";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("모의 데이터", () => {
  it("메시지마다 비어 있지 않은 배열이 있다", () => {
    expect(MESSAGE_NAMES).toHaveLength(30);
    for (const name of MESSAGE_NAMES) {
      expect(getMock(name).length, name).toBeGreaterThan(0);
    }
  });

  it("없는 이름은 만드는 방법을 알려 주며 실패한다", () => {
    expect(() => getMock("NoSuchMessage" as never)).toThrow(/init-mocks/);
  });

  it("useMessages 는 모의 모드에서 서버를 부르지 않고 바로 값을 준다", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { result } = renderHook(() => useMessages("RobotStatus"));
    expect(result.current.mode).toBe("mock");
    expect(result.current.loading).toBe(false);
    expect(result.current.data?.map((robot) => robot.robot_id)).toEqual(["pinky_1", "pinky_2", "pinky_3"]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("gateway 모드", () => {
  it("/api/fms/<메시지 이름> 을 불러 배열을 받는다", async () => {
    vi.stubEnv("VITE_DATA", "gateway");
    vi.resetModules();
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ arm_id: "omx_9" }] });
    vi.stubGlobal("fetch", fetchSpy);
    const { useMessages: gatewayHook } = await import("@/lib/dataSource");
    const { result } = renderHook(() => gatewayHook("ArmMode"));
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(result.current.mode).toBe("gateway");
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/fms/ArmMode");
    expect(result.current.data).toEqual([{ arm_id: "omx_9" }]);
  });

  it("서버 오류는 모의 값으로 가리지 않고 오류로 보인다", async () => {
    vi.stubEnv("VITE_DATA", "gateway");
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, statusText: "Unavailable" }));
    const { useMessages: gatewayHook } = await import("@/lib/dataSource");
    const { result } = renderHook(() => gatewayHook("ArmMode"));
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.data).toBeNull();
    expect(result.current.error).toContain("503");
  });
});
