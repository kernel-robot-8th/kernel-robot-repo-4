import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "bad" | "muted";

const TONES: Record<Tone, string> = {
  ok: "border-[#2e7d32]/70 bg-[#2e7d32]/25 text-emerald-300 font-semibold",
  warn: "border-[#ef6c00]/70 bg-[#ef6c00]/25 text-amber-300 font-semibold",
  bad: "border-[#c62828]/70 bg-[#c62828]/25 text-rose-300 font-semibold",
  muted: "border-border bg-neutral-800/70 text-neutral-400 font-medium",
};

/** 상태를 색과 글자로 함께 보인다 (색만으로 구분하지 않는다). */
export default function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center rounded px-2 py-0.5 text-xs", TONES[tone])}>
      {children}
    </span>
  );
}
