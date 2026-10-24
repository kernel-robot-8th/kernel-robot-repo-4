import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="max-w-xl space-y-3">
      <h1 className="text-2xl font-bold">찾을 수 없는 메뉴입니다</h1>
      <p className="text-sm text-muted-foreground">
        메뉴 ID 는 레지스트리(menu_tree.yaml)에 있는 것만 열립니다. 없앤 메뉴도 열리지 않습니다.
      </p>
      <Link to="/" className="text-sm text-primary underline">
        개요로 돌아가기
      </Link>
    </div>
  );
}
