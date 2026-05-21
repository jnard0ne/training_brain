import { useEffect, useRef, useState } from "react";
import { api, type GarminLoginStatus, type OverallStatus } from "../api";
import { StatusDot } from "./StatusDot";

type Props = {
  status: OverallStatus["garmin"] | null;
  onChange: () => Promise<void> | void;
};

export function GarminCard({ status, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState("");
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [login, setLogin] = useState<GarminLoginStatus | null>(null);
  const pollRef = useRef<number | null>(null);

  // Poll login state while a flow is in progress.
  useEffect(() => {
    const active = login?.state === "running" || login?.state === "needs_mfa";
    if (!active) {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const s = await api.garminLoginStatus();
        setLogin(s);
        if (s.state === "success") {
          setEmail("");
          setPassword("");
          setMfa("");
          await onChange();
          await api.garminReset();
          // Leave the success panel up for a beat so the user sees confirmation,
          // then collapse back to the header (which now shows "Token cached just now").
          window.setTimeout(() => {
            setOpen(false);
            setLogin(null);
          }, 2500);
        }
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : String(e));
      }
    }, 1000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [login?.state, onChange]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrMsg(null);
    try {
      const s = await api.garminLogin(email, password);
      setLogin(s);
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleMfa(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrMsg(null);
    try {
      const s = await api.garminMfa(mfa);
      setLogin(s);
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    await api.garminReset();
    setLogin(null);
    setErrMsg(null);
  }

  const connected = status?.connected ?? false;
  const tone = connected ? "ok" : "warn";
  const statusLabel = connected
    ? status?.token_updated_at
      ? `Last verified ${formatRelative(status.token_updated_at)}`
      : "Connected"
    : "Not connected";

  return (
    <section className="rounded-xl border border-border bg-panel">
      <header className="flex items-center justify-between p-5">
        <div>
          <h2 className="text-lg font-medium">Garmin Connect</h2>
          <div className="mt-1">
            <StatusDot tone={tone} label={statusLabel} />
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-muted"
        >
          {open ? "Cancel" : connected ? "Re-authenticate" : "Connect"}
        </button>
      </header>

      {open && (
        <div className="border-t border-border p-5 space-y-4">
          {!login || login.state === "idle" || login.state === "error" ? (
            <form onSubmit={handleLogin} className="space-y-3">
              <Field label="Email">
                <input
                  type="email"
                  required
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input"
                />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input"
                />
              </Field>
              <p className="text-xs text-muted">
                On success, credentials are written to{" "}
                <span className="font-mono">.env</span> so the scheduled sync can
                auto-refresh the Garmin token when it expires. Tokens cache to{" "}
                <span className="font-mono">~/.garminconnect</span>.
              </p>
              <button type="submit" disabled={busy} className="btn-primary">
                {busy ? "Starting…" : "Log in"}
              </button>
              {login?.state === "error" && (
                <p className="text-sm text-err">{login.error}</p>
              )}
            </form>
          ) : login.state === "success" ? (
            <div className="flex items-center gap-2 rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm text-ok">
              <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
                <path
                  fillRule="evenodd"
                  d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 9.7a1 1 0 1 1 1.4-1.4L8.5 12l6.8-6.7a1 1 0 0 1 1.4 0Z"
                  clipRule="evenodd"
                />
              </svg>
              Connected. Garmin token refreshed.
            </div>
          ) : login.state === "running" ? (
            <p className="text-sm">Contacting Garmin…</p>
          ) : login.state === "needs_mfa" ? (
            <form onSubmit={handleMfa} className="space-y-3">
              <Field label="MFA code">
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete="one-time-code"
                  required
                  autoFocus
                  value={mfa}
                  onChange={(e) => setMfa(e.target.value)}
                  className="input font-mono tracking-widest"
                />
              </Field>
              <p className="text-xs text-muted">
                Garmin just sent a 6-digit code to your email or phone.
              </p>
              <div className="flex gap-2">
                <button type="submit" disabled={busy} className="btn-primary">
                  {busy ? "Submitting…" : "Submit code"}
                </button>
                <button type="button" onClick={handleReset} className="btn-ghost">
                  Cancel
                </button>
              </div>
            </form>
          ) : null}

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

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
