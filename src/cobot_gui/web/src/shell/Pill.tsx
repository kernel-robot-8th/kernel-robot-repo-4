import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "bad" | "muted";

const TONES: Record<Tone, string> = {
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  bad: "border-destructive/40 bg-destructive/10 text-destructive",
  muted: "border-border bg-muted text-muted-foreground",
};

/** 상태를 색과 글자로 함께 보인다 (색만으로 구분하지 않는다). */
export default function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", TONES[tone])}>
      {children}
    </span>
  );
}
