import { useCallback, useEffect, useState } from "react";
import { api, type StravaStatus } from "../api";
import { StatusDot } from "./StatusDot";

export function StravaCard({ onChange }: { onChange: () => void }) {
  const [status, setStatus] = useState<StravaStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [showCreds, setShowCreds] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.stravaStatus());
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Listen for the OAuth callback page closing the loop.
  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      if (e.data?.type === "strava:complete") {
        refresh();
        onChange();
        if (e.data.success) setInfo("Strava connected.");
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onChange, refresh]);

  async function handleSaveCreds(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrMsg(null);
    try {
      const s = await api.stravaSaveCredentials(clientId.trim(), clientSecret.trim());
      setStatus(s);
      setClientId("");
      setClientSecret("");
      setShowCreds(false);
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleConnect() {
    setBusy(true);
    setErrMsg(null);
    setInfo(null);
    try {
      const { url } = await api.stravaAuthorizeUrl();
      const popup = window.open(url, "strava-oauth", "width=600,height=720");
      if (!popup) {
        // Popup blocked — fall back to a same-tab redirect.
        window.location.href = url;
      }
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const credsReady = (status?.has_client_id ?? false) && (status?.has_client_secret ?? false);
  const tokenOk = status?.verification?.ok ?? false;

  let tone: "ok" | "warn" | "err" | "idle" = "idle";
  let statusLabel = "Loading…";
  if (status) {
    if (!credsReady) {
      tone = "warn";
      statusLabel = "Client ID / secret needed";
    } else if (!status.has_refresh_token) {
      tone = "warn";
      statusLabel = "Not connected";
    } else if (tokenOk) {
      tone = "ok";
      statusLabel = "Connected";
    } else {
      tone = "err";
      statusLabel = `Token rejected${status.verification?.reason ? ` (${status.verification.reason})` : ""}`;
    }
  }

  return (
    <section className="rounded-xl border border-border bg-panel">
      <header className="flex items-center justify-between p-5">
        <div>
          <h2 className="text-lg font-medium">Strava</h2>
          <div className="mt-1">
            <StatusDot tone={tone} label={statusLabel} />
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-muted"
        >
          {open ? "Cancel" : tokenOk ? "Re-authenticate" : "Connect"}
        </button>
      </header>

      {open && (
        <div className="border-t border-border p-5 space-y-4">
          {!credsReady && (
            <div className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
              Strava client credentials aren't set in <span className="font-mono">.env</span>. Add
              them below — create an API app at{" "}
              <a
                href="https://www.strava.com/settings/api"
                target="_blank"
                rel="noreferrer"
                className="text-accent underline"
              >
                strava.com/settings/api
              </a>{" "}
              and set its Authorization Callback Domain to{" "}
              <span className="font-mono">localhost</span>.
            </div>
          )}

          {(showCreds || !credsReady) && (
            <form onSubmit={handleSaveCreds} className="space-y-3">
              <Field label="Client ID">
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder={status?.has_client_id ? "•••••• (leave blank to keep)" : ""}
                  className="input"
                />
              </Field>
              <Field label="Client secret">
                <input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder={status?.has_client_secret ? "•••••• (leave blank to keep)" : ""}
                  className="input"
                />
              </Field>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy || (!clientId && !clientSecret)}
                  className="btn-primary"
                >
                  {busy ? "Saving…" : "Save credentials"}
                </button>
                {credsReady && (
                  <button
                    type="button"
                    onClick={() => setShowCreds(false)}
                    className="btn-ghost"
                  >
                    Hide
                  </button>
                )}
              </div>
            </form>
          )}

          {credsReady && !showCreds && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleConnect}
                disabled={busy}
                className="btn-primary"
              >
                {busy ? "Opening Strava…" : tokenOk ? "Re-authorize on Strava" : "Authorize on Strava"}
              </button>
              <button
                type="button"
                onClick={() => setShowCreds(true)}
                className="btn-ghost"
              >
                Change credentials
              </button>
            </div>
          )}

          {info && <p className="text-sm text-ok">{info}</p>}
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
