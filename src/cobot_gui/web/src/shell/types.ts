// 레지스트리(menu_tree.yaml)에서 생성되는 데이터의 모양. 생성기는 src/cobot_gui/cobot_gui/gen_web_menus.py 다.

export type MenuStatus = "planned" | "in_progress" | "done" | "removed";
export type ImplLevel = "none" | "external" | "integrated";
export type DecisionStatus = "open" | "proposed" | "decided";

export interface Screen {
  id: string;
  label: string;
  name: string;
  phaseNote: string;
}

export interface Phase {
  id: string;
  title: string;
  roadmapStage: string;
}

export interface Role {
  key: string;
  name: string;
  members: string[];
}

export interface SrItem {
  id: string;
  name: string;
  priority: string;
}

export interface Decision {
  id: string;
  title: string;
  status: DecisionStatus;
  blocks: string;
  proposal: string;
  record: string;
  decidedBy: string;
  decidedOn: string;
}

export interface Menu {
  id: string;
  name: string;
  depth1: string;
  screen: string;
  alsoShownIn: string[];
  phase: string;
  status: MenuStatus;
  impl: ImplLevel;
  implRef: string;
  sr: string[];
  srOriginal: string[] | null;
  srUnconfirmed: string[];
  dataSources: string[];
  commands: string[];
  screenOwner: string;
  dataOwner: string;
  decisions: string[];
  notes: string[];
  branch: string;
}

/** 메뉴 폴더가 내보내는 화면 컴포넌트의 속성. */
export interface MenuPageProps {
  menu: Menu;
}
