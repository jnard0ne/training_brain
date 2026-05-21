import type { Sport } from "../api";

// TP-ish palette. Each sport gets a stripe color used as the left bar on a
// workout card. Use Tailwind arbitrary-value classes to avoid pulling in
// extra theme tokens.
export const SPORT_COLOR: Record<Sport, string> = {
  swim: "bg-cyan-500",
  bike: "bg-amber-500",
  run: "bg-emerald-500",
  strength: "bg-zinc-500",
  mobility: "bg-purple-500",
  brick: "bg-orange-500",
  other: "bg-neutral-600",
};

export const SPORT_LABEL: Record<Sport, string> = {
  swim: "Swim",
  bike: "Bike",
  run: "Run",
  strength: "Strength",
  mobility: "Mobility",
  brick: "Brick",
  other: "Other",
};

export function shortTitle(description: string, sport: Sport): string {
  // Planned descriptions often start with "Run: <name>" or "Swim: <name>" then
  // multi-line structure. Grab the first line, drop the leading "Sport: " if
  // present, and truncate aggressively.
  const firstLine = (description || "").split("\n")[0].trim();
  if (!firstLine) return SPORT_LABEL[sport];
  const prefix = new RegExp(`^${SPORT_LABEL[sport]}:\\s*`, "i");
  return firstLine.replace(prefix, "").trim() || SPORT_LABEL[sport];
}
