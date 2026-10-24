import { lazy } from "react";
import type { ComponentType, LazyExoticComponent } from "react";

import { folderOf } from "@/lib/registry";
import type { MenuPageProps } from "@/shell/types";

// src/menus/<메뉴 ID 의 . 를 _ 로>/Page.tsx 가 있으면 틀 페이지 대신 그 화면을 쓴다.
// 라우터나 이 파일을 고치지 않고 폴더만 만들면 된다. _template 은 복사용이라 제외한다.
const modules = import.meta.glob<{ default: ComponentType<MenuPageProps> }>("../menus/*/Page.tsx");

const PAGES: Record<string, LazyExoticComponent<ComponentType<MenuPageProps>>> = {};
for (const [path, loader] of Object.entries(modules)) {
  const folder = path.match(/menus\/([^/]+)\/Page\.tsx$/)?.[1];
  if (folder && !folder.startsWith("_")) {
    PAGES[folder] = lazy(loader);
  }
}

export function pageFor(menuId: string) {
  return PAGES[folderOf(menuId)];
}

export function hasMenuPage(menuId: string): boolean {
  return folderOf(menuId) in PAGES;
}
