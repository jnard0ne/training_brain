import type { WorkoutItem } from "../../api";
import { sameDay } from "../../lib/dates";
import { WorkoutItemCard } from "./WorkoutCard";

type Props = {
  date: Date;
  items: WorkoutItem[];
  today: Date;
};

export function DayCell({ date, items, today }: Props) {
  const isToday = sameDay(date, today);

  return (
    <div
      className={[
        "rounded-lg border bg-bg/40 flex flex-col overflow-hidden min-h-[180px]",
        isToday ? "border-accent/60" : "border-border",
      ].join(" ")}
    >
      <div className="flex items-center justify-between px-2 py-1 border-b border-border/60">
        <div className="text-xs">
          <span className="text-muted">
            {date.toLocaleDateString(undefined, { weekday: "short" })}
          </span>{" "}
          <span className={isToday ? "text-accent font-medium" : "text-text"}>
            {date.getDate()}
          </span>
        </div>
        {items.length > 0 && (
          <div className="text-[10px] text-muted">{items.length}</div>
        )}
      </div>
      <div className="p-1.5 space-y-1.5">
        {items.map((item) => (
          <WorkoutItemCard key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}
