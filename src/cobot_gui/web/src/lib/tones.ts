import type { Tone } from "@/shell/Pill";

/** 핑키 상태 → 색. 안전 대기(DISARMED)와 정지(HOLD·PAUSED)는 경고, 래치·링크 끊김·오류는 위험이다. */
export function robotTone(state: string): Tone {
  if (["IDLE", "NAVIGATING", "LOADING", "UNLOADING"].includes(state)) return "ok";
  if (["PAUSED", "HOLD", "DISARMED", "RECOVERING"].includes(state)) return "warn";
  return "bad";
}

export function armModeTone(mode: string): Tone {
  if (mode === "ROS_MANAGED") return "ok";
  if (mode === "LEROBOT_EXCLUSIVE") return "warn";
  return "bad";
}

export function severityTone(severity: string): Tone {
  if (severity === "RED") return "bad";
  if (severity === "AMBER") return "warn";
  return "muted";
}

export function singleWriterTone(state: string): Tone {
  if (state === "OK") return "ok";
  if (state === "VIOLATION") return "bad";
  return "warn";
}
