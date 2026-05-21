import { useCallback, useEffect, useState } from "react";
import { api, type OverallStatus } from "./api";
import { GarminCard } from "./components/GarminCard";
import { StravaCard } from "./components/StravaCard";
import { TrainingPeaksCard } from "./components/TrainingPeaksCard";

export default function App() {
  const [status, setStatus] = useState<OverallStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="min-h-screen p-6 sm:p-10 max-w-3xl mx-auto">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">training_brain</h1>
        <p className="text-muted text-sm mt-1">
          Connect your sources. Re-authenticate when sync fails.
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-lg border border-err/40 bg-err/10 px-4 py-3 text-sm">
          Couldn't reach the backend: <span className="font-mono">{error}</span>
        </div>
      )}

      <div className="space-y-4">
        <GarminCard status={status?.garmin ?? null} onChange={refresh} />
        <TrainingPeaksCard onChange={refresh} />
        <StravaCard onChange={refresh} />
      </div>
    </div>
  );
}
