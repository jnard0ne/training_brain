import { Link, useParams } from "react-router-dom";

export default function WorkoutDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="max-w-3xl mx-auto">
      <Link to="/" className="text-accent text-sm hover:underline">
        ← Back to calendar
      </Link>
      <div className="mt-6 rounded-xl border border-border bg-panel p-6">
        <h1 className="text-xl font-semibold">Workout</h1>
        <p className="mt-2 font-mono text-xs text-muted break-all">id: {id}</p>
        <p className="mt-6 text-sm text-muted">
          Detail view coming soon — laps, mean-max curve, time-in-zone, decoupling.
        </p>
      </div>
    </div>
  );
}
