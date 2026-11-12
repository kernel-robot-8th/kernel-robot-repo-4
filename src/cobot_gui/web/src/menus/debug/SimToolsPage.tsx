import { findMenu } from "@/lib/registry";
import Page from "@/menus/6_5/Page";

export default function SimToolsPage() {
  return <Page menu={findMenu("6.5")!} />;
}
