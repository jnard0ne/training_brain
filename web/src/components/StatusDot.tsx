type Tone = "ok" | "warn" | "err" | "idle";

const COLOR: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  err: "bg-err",
  idle: "bg-muted",
};

export function StatusDot({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`inline-block h-2 w-2 rounded-full ${COLOR[tone]}`} />
      <span className="text-muted">{label}</span>
    </span>
  );
}
