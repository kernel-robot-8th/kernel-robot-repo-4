import { Suspense, createElement } from "react";
import { useParams } from "react-router-dom";

import { findMenu } from "@/lib/registry";
import MenuPlaceholder from "@/shell/MenuPlaceholder";
import NotFound from "@/shell/NotFound";
import { pageFor } from "@/shell/pages";
import { Skeleton } from "@/components/ui/skeleton";

/** /menus/:id 하나로 모든 메뉴를 받는다. 메뉴 폴더에 Page.tsx 가 있으면 그것을, 없으면 틀 페이지를 보인다. */
export default function MenuRoute() {
  const { id } = useParams();
  const menu = findMenu(id);
  if (!menu) return <NotFound />;
  const Page = pageFor(menu.id);
  if (!Page) return <MenuPlaceholder menu={menu} />;
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full max-w-4xl" />}>
      {createElement(Page, { menu })}
    </Suspense>
  );
}
