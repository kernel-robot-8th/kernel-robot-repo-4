import { CONTRACT_NAMES } from "@/generated/messages";
import type { Menu } from "@/shell/types";

export type ContractLevel = "all" | "part" | "none" | "unnamed";

export const CONTRACT_LABELS: Record<ContractLevel, string> = {
  all: "정의 있음",
  part: "일부만 있음",
  none: "정의 없음",
  unnamed: "원천 이름 없음",
};

/**
 * 메뉴의 데이터 원천에 적힌 메시지 이름이 인터페이스 정의(cobot_interfaces)에 있는지 본다.
 * 이름은 레지스트리 data_sources 글자에서 대문자로 시작하는 낱말을 뽑아 대조한다 (근사치).
 * 정의가 있다는 말은 메시지가 정의됐다는 뜻이다. 그것을 발행하는 노드가 있다는 뜻이 아니다.
 */
export function contractOf(menu: Menu): { level: ContractLevel; found: string[]; missing: string[] } {
  const tokens = Array.from(new Set(menu.dataSources.join(" ").match(/[A-Z][A-Za-z0-9]{3,}/g) ?? []));
  const found = tokens.filter((token) => CONTRACT_NAMES.includes(token));
  const missing = tokens.filter((token) => !CONTRACT_NAMES.includes(token));
  let level: ContractLevel = "all";
  if (tokens.length === 0) level = "unnamed";
  else if (found.length === 0) level = "none";
  else if (missing.length > 0) level = "part";
  return { level, found, missing };
}
