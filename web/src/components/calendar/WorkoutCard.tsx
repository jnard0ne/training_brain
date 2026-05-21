import { Link } from "react-router-dom";
import type { WorkoutItem } from "../../api";
import { formatDistance, formatDuration } from "../../lib/dates";
import { SPORT_COLOR, SPORT_LABEL, shortTitle } from "../../lib/sports";
import { ComplianceBadge } from "./ComplianceBadge";

// One card per logical workout. Matched (planned+executed) pairs render as
// a single solid card with the planned title and executed stats. Planned-only
// uses a dashed border. Unplanned executions render solid.

export function WorkoutItemCard({ item }: { item: WorkoutItem }) {
  const sport = item.sport;
  const stripeColor = SPORT_COLOR[sport];

  let title: string;
  let stats: string;
  let dashed = false;
  let stripeFaded = false;

  if (item.kind === "completed") {
    title = shortTitle(item.planned.description, sport);
    const duration = formatDuration(item.executed.duration_s);
    const distance = formatDistance(item.executed.distance_m);
    const parts = [duration, distance].filter(Boolean);
    if (item.executed.tss != null) parts.push(`${Math.round(item.executed.tss)} TSS`);
    else if (item.executed.relative_effort != null) parts.push(`RE ${item.executed.relative_effort}`);
    stats = parts.join(" · ");
  } else if (item.kind === "planned") {
    title = shortTitle(item.planned.description, sport);
    const duration = formatDuration(item.planned.duration_planned_s);
    const parts = [duration];
    if (item.planned.tss_planned) parts.push(`${Math.round(item.planned.tss_planned)} TSS`);
    stats = parts.filter(Boolean).join(" · ");
    dashed = true;
    stripeFaded = true;
  } else {
    title = SPORT_LABEL[sport];
    const duration = formatDuration(item.executed.duration_s);
    const distance = formatDistance(item.executed.distance_m);
    const parts = [duration, distance].filter(Boolean);
    if (item.executed.tss != null) parts.push(`${Math.round(item.executed.tss)} TSS`);
    else if (item.executed.relative_effort != null) parts.push(`RE ${item.executed.relative_effort}`);
    stats = parts.join(" · ");
  }

  return (
    <Link
      to={`/workouts/${item.id}`}
      className={[
        "block rounded-md overflow-hidden transition",
        dashed
          ? "border border-dashed border-border bg-panel/40 hover:bg-panel"
          : "border border-border bg-panel hover:border-muted",
      ].join(" ")}
      title={`${SPORT_LABEL[sport]} · ${stats || title}`}
    >
      <div className="flex">
        <div className={`w-1 ${stripeColor} ${stripeFaded ? "opacity-60" : ""}`} />
        <div className="px-2.5 py-2 min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            <div className="text-xs font-medium truncate flex-1">{title}</div>
            <ComplianceBadge compliance={item.compliance ?? undefined} />
          </div>
          {stats && (
            <div className="text-[11px] text-muted mt-0.5 truncate">{stats}</div>
          )}
        </div>
      </div>
    </Link>
  );
}
