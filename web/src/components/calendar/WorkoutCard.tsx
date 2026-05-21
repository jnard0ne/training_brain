import { Link } from "react-router-dom";
import type { ExecutedWorkout, PlannedWorkout } from "../../api";
import { formatDistance, formatDuration } from "../../lib/dates";
import { SPORT_COLOR, SPORT_LABEL, shortTitle } from "../../lib/sports";
import { ComplianceBadge } from "./ComplianceBadge";

// One card per workout. Planned = lighter background, dashed border; Executed
// = solid panel background. Both link to /workouts/:id. Compliance badge in
// the top-right reflects the matched planned↔executed pair (or the lack of one).

export function PlannedCard({ workout }: { workout: PlannedWorkout }) {
  const title = shortTitle(workout.description, workout.sport);
  const duration = formatDuration(workout.duration_planned_s);
  return (
    <Link
      to={`/workouts/${workout.id}`}
      className="block rounded-md border border-dashed border-border bg-panel/40 hover:bg-panel transition overflow-hidden"
      title={`Planned · ${SPORT_LABEL[workout.sport]} · ${duration}`}
    >
      <div className="flex">
        <div className={`w-1 ${SPORT_COLOR[workout.sport]} opacity-60`} />
        <div className="px-2.5 py-2 min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            <div className="text-xs font-medium truncate flex-1">{title}</div>
            <ComplianceBadge compliance={workout.compliance} />
          </div>
          <div className="text-[11px] text-muted mt-0.5">
            {duration}
            {workout.tss_planned ? ` · ${Math.round(workout.tss_planned)} TSS` : ""}
          </div>
        </div>
      </div>
    </Link>
  );
}

export function ExecutedCard({ workout }: { workout: ExecutedWorkout }) {
  const duration = formatDuration(workout.duration_s);
  const distance = formatDistance(workout.distance_m);
  const title = SPORT_LABEL[workout.sport];
  const subtitle = [duration, distance].filter(Boolean).join(" · ");
  return (
    <Link
      to={`/workouts/${workout.id}`}
      className="block rounded-md border border-border bg-panel hover:border-muted transition overflow-hidden"
      title={`Executed · ${title} · ${subtitle}`}
    >
      <div className="flex">
        <div className={`w-1 ${SPORT_COLOR[workout.sport]}`} />
        <div className="px-2.5 py-2 min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            <div className="text-xs font-medium truncate flex-1">{title}</div>
            <ComplianceBadge compliance={workout.compliance} />
          </div>
          <div className="text-[11px] text-muted mt-0.5 truncate">
            {subtitle}
            {workout.tss != null ? ` · ${Math.round(workout.tss)} TSS` : ""}
            {workout.tss == null && workout.relative_effort != null
              ? ` · RE ${workout.relative_effort}`
              : ""}
          </div>
        </div>
      </div>
    </Link>
  );
}
