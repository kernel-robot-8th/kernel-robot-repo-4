import { Route, Routes } from "react-router-dom";

import Layout from "@/components/layout/Layout";
import MenuRoute from "@/shell/MenuRoute";
import NotFound from "@/shell/NotFound";
import OverviewPage from "@/shell/OverviewPage";

// 라우트는 이것뿐이다. 메뉴가 늘거나 화면이 생겨도 여기를 고치지 않는다 (shell/pages.ts 가 폴더를 찾는다).
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="menus/:id" element={<MenuRoute />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
