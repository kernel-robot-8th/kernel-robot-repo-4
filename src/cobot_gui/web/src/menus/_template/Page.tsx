// 새 메뉴 화면의 복사용 틀이다. 이 폴더(_template)는 화면으로 쓰이지 않는다.
//
// 쓰는 법
//   1. 이 폴더를 menus/<메뉴 ID 의 . 를 _ 로>/ 로 복사한다 (예: 메뉴 1.1 → menus/1_1/Page.tsx).
//   2. 라우터와 사이드바는 고치지 않는다. 폴더에 Page.tsx 가 생기면 틀 페이지 대신 쓰인다.
//   3. 데이터는 useResource("<메시지 이름>", 모의 값) 으로만 읽는다. 서버는 직접 부르지 않는다.
//   4. 이 폴더 밖에서는 components/ui, lib, shell/types, shell/MenuHeader 만 가져다 쓴다.
//      다른 메뉴 폴더를 가져다 쓰지 않는다 (홈랩으로 폴더째 옮기기 위해서다).
//   5. 명령을 보내는 버튼은 게이트웨이(S2)와 안전 검토 전까지 만들지 않는다.
import { useResource } from "@/lib/dataSource";
import MenuHeader from "@/shell/MenuHeader";
import type { MenuPageProps } from "@/shell/types";

const MOCK = { example: "모의 값" };

export default function Page({ menu }: MenuPageProps) {
  const { data } = useResource("ExampleMessage", MOCK);
  return (
    <div className="max-w-4xl space-y-6">
      <MenuHeader menu={menu} kind="page" />
      <pre className="rounded-none border bg-muted p-3 text-xs">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
