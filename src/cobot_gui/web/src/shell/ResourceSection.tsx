import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Resource } from "@/lib/dataSource";

/**
 * 데이터 한 덩어리를 제목과 함께 보인다. 불러오는 중, 오류, 모의 데이터 표시를 한곳에서 맡는다.
 * 모의 데이터일 때는 제목 옆에 '모의 데이터' 를 붙여 실제 값으로 오해하지 않게 한다.
 */
export default function ResourceSection<T>({
  title,
  resource,
  children,
}: {
  title: string;
  resource: Resource<T>;
  children: (data: T) => ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        {title}
        <Badge variant="outline">{resource.mode === "mock" ? "모의 데이터" : "서버"}</Badge>
      </h2>
      {resource.error && (
        <Alert variant="destructive">
          <AlertTitle>데이터를 읽지 못했습니다</AlertTitle>
          <AlertDescription>{resource.error}</AlertDescription>
        </Alert>
      )}
      {!resource.error && resource.data === null && <Skeleton className="h-24 w-full" />}
      {resource.data !== null && children(resource.data)}
    </section>
  );
}
