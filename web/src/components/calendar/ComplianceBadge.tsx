import { useRef, useState } from "react";
import type { Compliance, ComplianceLevel, ComplianceStatus } from "../../api";

// TP-style compliance buckets:
//   green/yellow/orange — completed, scored against planned duration
//   red                  — planned but not completed (past dates only)
//   grey                 — completed without a matching plan

const LEVEL_BG: Record<ComplianceLevel, string> = {
  green: "bg-emerald-500",
  yellow: "bg-amber-400",
  orange: "bg-orange-500",
  red: "bg-red-500",
  grey: "bg-neutral-500",
};

const LEVEL_FG: Record<ComplianceLevel, string> = {
  green: "text-white",
  yellow: "text-black",
  orange: "text-white",
  red: "text-white",
  grey: "text-white",
};

const TOOLTIP: Record<ComplianceStatus, Record<ComplianceLevel, string>> = {
  completed: {
    green: "Completed as planned",
    yellow: "Completed, somewhat off plan",
    orange: "Completed, far from plan",
    red: "Completed",
    grey: "Completed",
  },
  uncompleted: {
    green: "Not completed",
    yellow: "Not completed",
    orange: "Not completed",
    red: "Not completed",
    grey: "Not completed",
  },
  unplanned: {
    green: "Unplanned workout",
    yellow: "Unplanned workout",
    orange: "Unplanned workout",
    red: "Unplanned workout",
    grey: "Unplanned workout",
  },
};

export function ComplianceBadge({ compliance }: { compliance?: Compliance }) {
  if (!compliance) return null;
  const { status, level } = compliance;
  const label = TOOLTIP[status][level];

  // Custom tooltip — native `title` has a long delay and inherits the OS look.
  // Positioned via fixed coords so the workout card's overflow:hidden doesn't
  // clip it. Flips below the badge if it's near the top of the viewport.
  const ref = useRef<HTMLSpanElement>(null);
  const [tip, setTip] = useState<{ top: number; left: number; below: boolean } | null>(null);

  function show() {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const below = r.top < 56; // below the sticky header threshold
    setTip({
      top: below ? r.bottom + 6 : r.top - 6,
      left: r.left + r.width / 2,
      below,
    });
  }

  return (
    <>
      <span
        ref={ref}
        className={`inline-flex items-center justify-center w-4 h-4 rounded-full shrink-0 ${LEVEL_BG[level]} ${LEVEL_FG[level]}`}
        onMouseEnter={show}
        onMouseLeave={() => setTip(null)}
        aria-label={label}
        role="img"
      >
        {status === "completed" && <CheckIcon />}
        {status === "uncompleted" && <XIcon />}
        {status === "unplanned" && <BangIcon />}
      </span>
      {tip && (
        <span
          className="fixed z-50 pointer-events-none px-2 py-1 rounded-md bg-bg border border-border text-[11px] text-text shadow-lg whitespace-nowrap"
          style={{
            top: tip.top,
            left: tip.left,
            transform: `translate(-50%, ${tip.below ? "0" : "-100%"})`,
          }}
          role="tooltip"
        >
          {label}
        </span>
      )}
    </>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" className="w-2.5 h-2.5" fill="none" stroke="currentColor" strokeWidth="3.5" aria-hidden>
      <path d="M4 10l4 4 8-8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg viewBox="0 0 20 20" className="w-2.5 h-2.5" fill="none" stroke="currentColor" strokeWidth="3.5" aria-hidden>
      <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
    </svg>
  );
}

function BangIcon() {
  return (
    <svg viewBox="0 0 20 20" className="w-2.5 h-2.5" fill="currentColor" aria-hidden>
      <rect x="8.75" y="3" width="2.5" height="9" rx="1.25" />
      <circle cx="10" cy="15.25" r="1.4" />
    </svg>
  );
}
