import { Route, Routes } from "react-router-dom";

import Layout from "@/components/layout/Layout";
import LiveOverviewPage from "@/menus/debug/LiveOverviewPage";
import OrderTracePage from "@/menus/debug/OrderTracePage";
import CommDiagnosticsPage from "@/menus/debug/CommDiagnosticsPage";
import VisionAnomalyPage from "@/menus/debug/VisionAnomalyPage";
import ResourceMonitorPage from "@/menus/debug/ResourceMonitorPage";
import MapLivePage from "@/menus/debug/MapLivePage";
import { lazy, Suspense } from "react";
import MenuRoute from "@/shell/MenuRoute";
import NotFound from "@/shell/NotFound";
import OverviewPage from "@/shell/OverviewPage";

const SimToolsPage = lazy(() => import("@/menus/debug/SimToolsPage"));

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* 루트 접속 시 1. 실시간 실행·배정 현황 표시 */}
        <Route index element={<LiveOverviewPage />} />
        <Route path="debug/overview" element={<LiveOverviewPage />} />
        <Route path="debug/trace" element={<OrderTracePage />} />
        <Route path="debug/comm" element={<CommDiagnosticsPage />} />
        <Route path="debug/vision" element={<VisionAnomalyPage />} />
        <Route path="debug/sim-tools" element={<Suspense fallback={<p>모의 실험장 로딩 중</p>}><SimToolsPage /></Suspense>} />
        <Route path="debug/resources" element={<ResourceMonitorPage />} />
        <Route path="debug/camera" element={<MapLivePage />} />

        {/* 기획 카탈로그 매트릭스 */}
        <Route path="overview" element={<OverviewPage />} />

        {/* 34개 SR 개별 메뉴 경로 호환 */}
        <Route path="menus/:id" element={<MenuRoute />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
