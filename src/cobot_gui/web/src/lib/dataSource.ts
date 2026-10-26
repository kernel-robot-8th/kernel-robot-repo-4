import { useEffect, useState } from "react";

import type { MessageMap, MessageName } from "@/generated/messages";
import { fetchAPI } from "@/lib/api";
import { getMock } from "@/mock";

export type DataMode = "mock" | "gateway";

/** VITE_DATA=gateway 이면 서버(S2)에서 읽는다. 아니면 모의 데이터다. */
export const DATA_MODE: DataMode = import.meta.env.VITE_DATA === "gateway" ? "gateway" : "mock";

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  mode: DataMode;
}

/**
 * 메시지 이름(예: ArmMode) 하나를 읽는다. 메뉴 화면은 데이터를 이 길로만 읽는다.
 * mock 모드에서는 인자로 받은 모의 값을 그대로 돌려주고, 서버를 부르지 않는다.
 */
export function useResource<T>(name: string, mock: T): Resource<T> {
  const [state, setState] = useState<Omit<Resource<T>, "mode">>(() => ({
    data: DATA_MODE === "mock" ? mock : null,
    error: null,
    loading: DATA_MODE === "gateway",
  }));

  useEffect(() => {
    if (DATA_MODE !== "gateway") return;
    let cancelled = false;
    fetchAPI<T>(`/api/fms/${name}`)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ data: null, error: String(err), loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  return { ...state, mode: DATA_MODE };
}

/**
 * 인터페이스 메시지 하나(예: RobotStatus)의 최신 값 목록을 읽는다. 타입은 messages.ts 에서 온다.
 * 대상 하나(로봇·팔·카메라)마다 값 하나가 들어 있고, 대상이 하나뿐인 메시지도 길이 1 배열이다.
 * 값이 null 인 float 는 미측정이다. 0 으로 바꿔 보이지 않는다.
 */
export function useMessages<K extends MessageName>(name: K): Resource<MessageMap[K][]> {
  return useResource<MessageMap[K][]>(name, getMock(name));
}
