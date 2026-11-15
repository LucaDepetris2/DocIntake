import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";

const LINKS = [
  { to: "/", label: "Inbox", end: true },
  { to: "/?status=needs_review", label: "Review queue" },
  { to: "/alerts", label: "Deadlines" },
];

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <>
      <header className="topbar">
        <strong>DocIntake</strong>
        <nav>
          {LINKS.map((l) => (
            <NavLink key={l.label} to={l.to} end={l.end}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <span className="muted">{user?.firm_name}</span>
        <button className="link" onClick={logout}>
          Log out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
