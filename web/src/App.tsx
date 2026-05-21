import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import AuthPage from "./pages/AuthPage";
import CalendarPage from "./pages/CalendarPage";
import WorkoutDetailPage from "./pages/WorkoutDetailPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col overflow-x-clip">
        <TopNav />
        <main className="flex-1 px-6 sm:px-10 py-6 max-w-7xl mx-auto w-full">
          <Routes>
            <Route path="/" element={<CalendarPage />} />
            <Route path="/auth" element={<AuthPage />} />
            <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

function TopNav() {
  return (
    <header className="border-b border-border bg-panel/40">
      <div className="max-w-7xl mx-auto px-6 sm:px-10 h-12 flex items-center justify-between">
        <Link to="/" className="font-medium tracking-tight">
          training_brain
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <NavTab to="/" label="Calendar" />
          <NavTab to="/auth" label="Auth" />
        </nav>
      </div>
    </header>
  );
}

function NavTab({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `px-3 py-1.5 rounded-md ${
          isActive ? "bg-bg text-text" : "text-muted hover:text-text"
        }`
      }
    >
      {label}
    </NavLink>
  );
}
