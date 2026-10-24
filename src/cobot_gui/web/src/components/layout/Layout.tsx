import { Outlet } from "react-router-dom";

import Sidebar from "./Sidebar";
import FeedbackPanel from "@/components/feedback/FeedbackPanel";

export default function Layout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Sidebar />
      <main className="min-h-screen px-5 pb-10 pt-20 lg:ml-72 lg:px-8 lg:py-8 xl:mr-96">
        <Outlet />
      </main>
      <FeedbackPanel />
    </div>
  );
}
