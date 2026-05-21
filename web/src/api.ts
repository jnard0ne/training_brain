// Thin fetch wrapper. Hits /api/* relative paths — Vite proxies to FastAPI in
// dev; in prod the FastAPI server serves both the static bundle and the API.

export type GarminLoginState = "idle" | "running" | "needs_mfa" | "success" | "error";

export type OverallStatus = {
  garmin: {
    connected: boolean;
    token_updated_at: string | null;
    login_state: GarminLoginState;
    login_error: string | null;
  };
  strava: {
    has_client_id: boolean;
    has_client_secret: boolean;
    has_refresh_token: boolean;
  };
  trainingpeaks: {
    configured: boolean;
  };
};

export type TrainingPeaksStatus = {
  configured: boolean;
  url_masked: string | null;
  feed: { ok: boolean; reason?: string; event_count?: number } | null;
};

export type StravaStatus = {
  has_client_id: boolean;
  has_client_secret: boolean;
  has_refresh_token: boolean;
  verification: { ok: boolean; reason?: string; expires_at?: number } | null;
};

export type GarminLoginStatus = {
  state: GarminLoginState;
  error: string | null;
  token_exists: boolean;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      detail = await resp.text();
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  status: () => req<OverallStatus>("/api/status"),
  garminLogin: (email: string, password: string) =>
    req<GarminLoginStatus>("/api/garmin/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  garminLoginStatus: () => req<GarminLoginStatus>("/api/garmin/login/status"),
  garminMfa: (code: string) =>
    req<GarminLoginStatus>("/api/garmin/login/mfa", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  garminReset: () =>
    req<GarminLoginStatus>("/api/garmin/login/reset", { method: "POST" }),
  stravaStatus: () => req<StravaStatus>("/api/strava/status"),
  stravaSaveCredentials: (client_id: string, client_secret: string) =>
    req<StravaStatus>("/api/strava/credentials", {
      method: "POST",
      body: JSON.stringify({
        client_id: client_id || null,
        client_secret: client_secret || null,
      }),
    }),
  stravaAuthorizeUrl: () =>
    req<{ url: string; redirect_uri: string }>("/api/strava/authorize_url"),
  trainingpeaksStatus: () => req<TrainingPeaksStatus>("/api/trainingpeaks/status"),
  trainingpeaksSetUrl: (url: string) =>
    req<TrainingPeaksStatus>("/api/trainingpeaks/url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  calendar: (start: string, end: string) =>
    req<CalendarPayload>(
      `/api/calendar?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    ),
};

export type Sport = "swim" | "bike" | "run" | "strength" | "mobility" | "brick" | "other";

export type ComplianceStatus = "completed" | "uncompleted" | "unplanned";
export type ComplianceLevel = "green" | "yellow" | "orange" | "red" | "grey";
export type Compliance = { status: ComplianceStatus; level: ComplianceLevel };

export type PlannedWorkout = {
  id: string;
  sport: Sport;
  duration_planned_s: number | null;
  tss_planned: number | null;
  description: string;
  compliance?: Compliance;
};

export type ExecutedWorkout = {
  id: string;
  sport: Sport;
  started_at: string;
  started_local: string;
  duration_s: number | null;
  distance_m: number | null;
  tss: number | null;
  avg_hr: number | null;
  avg_power: number | null;
  avg_pace_s_per_km: number | null;
  elevation_gain_m: number | null;
  relative_effort: number | null;
  garmin_activity_id: number | null;
  strava_activity_id: number | null;
  compliance?: Compliance;
};

export type CalendarPayload = {
  timezone: string;
  start: string;
  end: string;
  days: Record<string, { planned: PlannedWorkout[]; executed: ExecutedWorkout[] }>;
};
