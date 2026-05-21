import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type CalendarPayload } from "../api";
import { WeekRow } from "../components/calendar/WeekRow";
import { addDays, formatRange, fromIso, sameDay, startOfWeek, toIso } from "../lib/dates";

// How many weeks of context to load on either side of "this week" by default.
// Generous enough to scroll comfortably without needing infinite loading yet.
const WEEKS_PAST = 12;
const WEEKS_FUTURE = 12;

export default function CalendarPage() {
  const today = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }, []);

  const thisWeek = useMemo(() => startOfWeek(today), [today]);

  const weeks = useMemo(() => {
    const arr: Date[] = [];
    for (let i = -WEEKS_PAST; i <= WEEKS_FUTURE; i++) {
      arr.push(addDays(thisWeek, i * 7));
    }
    return arr;
  }, [thisWeek]);

  const [data, setData] = useState<CalendarPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeWeek, setActiveWeek] = useState<Date>(thisWeek);

  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // One request for the whole visible range.
  useEffect(() => {
    const start = weeks[0];
    const end = addDays(weeks[weeks.length - 1], 6);
    api
      .calendar(toIso(start), toIso(end))
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [weeks]);

  // Scrollspy: whichever week intersects a thin band just below the sticky
  // header is "active." rootMargin defines that band — top offset = header
  // height (~64px), bottom offset trims everything past it.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Multiple entries may fire at once during a fast scroll. Pick the
        // topmost intersecting one.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length === 0) return;
        const iso = visible[0].target.getAttribute("data-week");
        if (iso) setActiveWeek(fromIso(iso));
      },
      { rootMargin: "-72px 0px -85% 0px", threshold: 0 },
    );
    weeks.forEach((w) => {
      const el = rowRefs.current[toIso(w)];
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [weeks]);

  // On first mount (and whenever the day rolls over), snap to "today's" week.
  useLayoutEffect(() => {
    const el = rowRefs.current[toIso(thisWeek)];
    if (el) el.scrollIntoView({ block: "start" });
  }, [thisWeek]);

  const scrollToWeek = useCallback((w: Date) => {
    const el = rowRefs.current[toIso(w)];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div>
      <header className="sticky top-0 -mx-6 sm:-mx-10 px-6 sm:px-10 pt-2 pb-3 bg-bg/95 backdrop-blur z-10 border-b border-border/40">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {formatRange(activeWeek, addDays(activeWeek, 6))}
            </h1>
            <p className="text-xs text-muted mt-0.5">
              {data?.timezone ? `Times in ${data.timezone}` : " "}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => scrollToWeek(addDays(activeWeek, -7))}
              className="btn-ghost px-3 py-1.5"
              aria-label="Previous week"
            >
              ←
            </button>
            <button onClick={() => scrollToWeek(thisWeek)} className="btn-ghost px-3 py-1.5">
              Today
            </button>
            <button
              onClick={() => scrollToWeek(addDays(activeWeek, 7))}
              className="btn-ghost px-3 py-1.5"
              aria-label="Next week"
            >
              →
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="my-4 rounded-lg border border-err/40 bg-err/10 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="space-y-3 mt-4">
        {weeks.map((w) => {
          const iso = toIso(w);
          const isThisWeek = sameDay(w, thisWeek);
          return (
            <div
              key={iso}
              data-week={iso}
              ref={(el) => {
                rowRefs.current[iso] = el;
              }}
              className={[
                "scroll-mt-24 relative isolate",
                // Full-bleed background stripe via a pseudo-element that
                // breaks out of the centered container with w-screen, sitting
                // behind the day cells via -z-10. Edge-to-edge, no borders.
                isThisWeek
                  ? "py-1.5 before:content-[''] before:absolute before:inset-y-0 before:left-1/2 before:-translate-x-1/2 before:w-screen before:bg-accent/[0.05] before:-z-10"
                  : "",
              ].join(" ")}
            >
              <WeekRow weekStart={w} data={data} today={today} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
