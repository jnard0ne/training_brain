import type { CalendarPayload } from "../../api";
import { addDays, toIso } from "../../lib/dates";
import { DayCell } from "./DayCell";

export function WeekRow({
  weekStart,
  data,
  today,
}: {
  weekStart: Date;
  data: CalendarPayload | null;
  today: Date;
}) {
  const days: Date[] = [];
  for (let i = 0; i < 7; i++) days.push(addDays(weekStart, i));
  return (
    <div className="grid grid-cols-7 gap-2">
      {days.map((d) => {
        const iso = toIso(d);
        const day = data?.days[iso] ?? { planned: [], executed: [] };
        return (
          <DayCell
            key={iso}
            date={d}
            planned={day.planned}
            executed={day.executed}
            today={today}
          />
        );
      })}
    </div>
  );
}
