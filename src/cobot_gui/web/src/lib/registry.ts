import { DECISIONS, MENUS, PHASES, ROLES, SCREENS, SR_CATALOG } from "@/generated/menus";
import type { ControlArea, DecisionStatus, ImplLevel, Menu, MenuStatus } from "@/shell/types";

export const IMPL_LABELS: Record<ImplLevel, string> = {
  none: "없음",
  external: "외부 구현 (통합 전)",
  integrated: "통합됨",
};

export const STATUS_LABELS: Record<MenuStatus, string> = {
  planned: "계획",
  in_progress: "진행 중",
  done: "완료",
  removed: "없앰",
};

export const DECISION_LABELS: Record<DecisionStatus, string> = {
  open: "미결",
  proposed: "추천안 있음",
  decided: "확정",
};

/** 없앤 메뉴를 뺀 메뉴 목록. ID 숫자 순서다. */
export const ACTIVE_MENUS: Menu[] = MENUS.filter((menu) => menu.status !== "removed");

export function findMenu(id: string | undefined): Menu | undefined {
  return ACTIVE_MENUS.find((menu) => menu.id === id);
}

/** 1Depth 대분류 순서대로 묶는다. */
export function menuGroups(): { title: string; menus: Menu[] }[] {
  const groups: { title: string; menus: Menu[] }[] = [];
  for (const menu of ACTIVE_MENUS) {
    let group = groups.find((item) => item.title === menu.depth1);
    if (!group) {
      group = { title: menu.depth1, menus: [] };
      groups.push(group);
    }
    group.menus.push(menu);
  }
  return groups;
}

export function screenText(screenId: string): string {
  const screen = SCREENS.find((item) => item.id === screenId);
  return screen ? `${screen.label} ${screen.name}` : "—";
}

export function phaseTitle(phaseId: string): string {
  const phase = PHASES.find((item) => item.id === phaseId);
  return phase ? `${phase.id} ${phase.title}` : phaseId;
}

export function roleText(key: string): string {
  const role = ROLES.find((item) => item.key === key);
  if (!role) return "미정";
  return role.members.length ? `${role.name} (${role.members.join(", ")})` : role.name;
}

export function srName(id: string): string {
  return SR_CATALOG.find((item) => item.id === id)?.name ?? "";
}

export function decisionOf(id: string) {
  return DECISIONS.find((item) => item.id === id);
}

/** 메뉴 ID 를 메뉴 폴더 이름으로 바꾼다. 3.7 → 3_7 */
export function folderOf(id: string): string {
  return id.replace(".", "_");
}

export const CONTROL_AREA_LABELS: Record<ControlArea, string> = {
  operational: "로봇 수행 관제",
  anomaly: "이상 감지 관제",
};

export function controlOwnerText(key: string): string {
  const role = ROLES.find((item) => item.key === key);
  return role?.members.length ? roleText(key) : `${roleText(key)} (개인 담당 미정)`;
}
