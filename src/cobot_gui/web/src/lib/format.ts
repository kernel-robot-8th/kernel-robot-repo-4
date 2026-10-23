import type { Float, Quaternion, Time } from "@/generated/messages";

export const UNMEASURED = "미측정";

/** 숫자를 단위와 함께 보인다. null(NaN, 미측정)은 0 이 아니라 '미측정' 이다. */
export function num(value: Float | undefined, digits = 1, unit = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNMEASURED;
  return `${value.toFixed(digits)}${unit}`;
}

/** 쿼터니언의 yaw(z 축 회전)를 도 단위로. 값이 하나라도 미측정이면 null. */
export function yawDeg(q: Quaternion): number | null {
  const { x, y, z, w } = q;
  if (x === null || y === null || z === null || w === null) return null;
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  return (yaw * 180) / Math.PI;
}

/** ROS 시각을 'YYYY-MM-DD HH:MM:SS' (UTC) 로. 0 이면 '없음'. */
export function timeText(time: Time): string {
  if (time.sec === 0) return "없음";
  return new Date(time.sec * 1000).toISOString().slice(0, 19).replace("T", " ") + "Z";
}
