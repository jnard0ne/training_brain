// Date helpers for the calendar. All dates here are "local" calendar dates —
// we deliberately don't deal with the athlete's timezone on the frontend; the
// backend already converts started_at to local before grouping into days.

export function toIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function fromIso(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

export function startOfWeek(d: Date): Date {
  // Week starts Monday.
  const c = new Date(d);
  const day = (c.getDay() + 6) % 7; // 0=Mon, 6=Sun
  c.setDate(c.getDate() - day);
  c.setHours(0, 0, 0, 0);
  return c;
}

export function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function formatRange(start: Date, end: Date): string {
  const sameYear = start.getFullYear() === end.getFullYear();
  const sameMonth = sameYear && start.getMonth() === end.getMonth();
  const fmt = (d: Date, withYear = false) =>
    d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: withYear ? "numeric" : undefined,
    });
  if (sameMonth) {
    return `${fmt(start)}–${end.getDate()}, ${start.getFullYear()}`;
  }
  if (sameYear) {
    return `${fmt(start)} – ${fmt(end)}, ${start.getFullYear()}`;
  }
  return `${fmt(start, true)} – ${fmt(end, true)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}`;
  return `${m}m`;
}

export function formatDistance(meters: number | null | undefined): string | null {
  if (meters == null || meters <= 0) return null;
  const km = meters / 1000;
  return km < 10 ? `${km.toFixed(2)} km` : `${km.toFixed(1)} km`;
}
