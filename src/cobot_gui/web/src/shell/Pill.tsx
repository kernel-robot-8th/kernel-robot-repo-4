import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "bad" | "muted";

const TONES: Record<Tone, string> = {
  ok: "bg-[#2e7d32] text-white font-bold border border-[#2e7d32]",
  warn: "bg-[#ef6c00] text-white font-bold border-[#ef6c00]",
  bad: "bg-[#c62828] text-white font-bold border-[#c62828]",
  muted: "bg-[#616161] text-white font-bold border-[#616161]",
};

/** 상태를 색과 글자로 함께 보인다 (색만으로 구분하지 않는다). */
export default function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 text-xs rounded-none", TONES[tone])}>
      {children}
    </span>
  );
}
