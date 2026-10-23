import { num, UNMEASURED } from "@/lib/format";
import type { Float } from "@/generated/messages";

/** 측정값을 단위와 함께 보인다. null(미측정)은 0 이 아니라 '미측정' 표시다. */
export default function Measured({ value, digits = 1, unit = "" }: { value: Float; digits?: number; unit?: string }) {
  if (num(value) === UNMEASURED) {
    return <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{UNMEASURED}</span>;
  }
  return <span className="tabular-nums">{num(value, digits, unit)}</span>;
}
