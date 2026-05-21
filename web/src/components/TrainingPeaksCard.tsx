import { useCallback, useEffect, useState } from "react";
import { api, type TrainingPeaksStatus } from "../api";
import { StatusDot } from "./StatusDot";

export function TrainingPeaksCard({ onChange }: { onChange: () => Promise<void> | void }) {
  const [status, setStatus] = useState<TrainingPeaksStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.trainingpeaksStatus());
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrMsg(null);
    try {
      const s = await api.trainingpeaksSetUrl(url);
      setStatus(s);
      setUrl("");
      setOpen(false);
      await onChange();
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const feedOk = status?.feed?.ok ?? false;
  let tone: "ok" | "warn" | "err" | "idle" = "idle";
  let statusLabel = "Loading…";
  if (status) {
    if (!status.configured) {
      tone = "warn";
      statusLabel = "Not configured";
    } else if (feedOk) {
      tone = "ok";
      const count = status.feed?.event_count ?? 0;
      statusLabel = `Active — ${count} event${count === 1 ? "" : "s"} in feed`;
    } else {
      tone = "err";
      statusLabel = `Feed unreachable${status.feed?.reason ? ` (${status.feed.reason})` : ""}`;
    }
  }

  return (
    <section className="rounded-xl border border-border bg-panel">
      <header className="flex items-center justify-between p-5">
        <div>
          <h2 className="text-lg font-medium">TrainingPeaks</h2>
          <div className="mt-1">
            <StatusDot tone={tone} label={statusLabel} />
          </div>
          {status?.configured && status.url_masked && (
            <p className="mt-2 font-mono text-xs text-muted break-all">{status.url_masked}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-muted"
        >
          {open ? "Cancel" : status?.configured ? "Change URL" : "Add URL"}
        </button>
      </header>

      {open && (
        <div className="border-t border-border p-5 space-y-4">
          <form onSubmit={handleSave} className="space-y-3">
            <Field label="iCal URL">
              <input
                type="text"
                required
                autoFocus
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="webcal://www.trainingpeaks.com/ical/…"
                className="input font-mono text-xs"
              />
            </Field>
            <p className="text-xs text-muted">
              In TrainingPeaks: Settings → Account Settings → Sharing → Calendar Feed.{" "}
              <span className="font-mono">webcal://</span> URLs are auto-converted to{" "}
              <span className="font-mono">https://</span>.
            </p>
            <button type="submit" disabled={busy} className="btn-primary">
              {busy ? "Saving…" : "Save & probe feed"}
            </button>
          </form>
          {errMsg && <p className="text-sm text-err">{errMsg}</p>}
        </div>
      )}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
