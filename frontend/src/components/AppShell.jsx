import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import ThemeToggle from "./ThemeToggle";

const NAV_LINKS = [
  { to: "/", label: "Projects", exact: true },
  { to: "/instructions", label: "Instructions" },
  { to: "/account", label: "Account" },
];

export default function AppShell({ children, wide = false }) {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  function isActive(to, exact) {
    return exact ? location.pathname === to : location.pathname.startsWith(to);
  }

  return (
    <div className="shell">
      <header className="shell-header">
        <Link to="/" className="brand">
          <span className="brand-mark">✦</span>
          <span>AI Assistance</span>
        </Link>
        <nav className="shell-nav">
          {NAV_LINKS.map((link) => (
            <Link key={link.to} to={link.to} className={isActive(link.to, link.exact) ? "shell-nav-active" : ""}>
              {link.label}
            </Link>
          ))}
          {isAdmin && (
            <Link to="/admin/users" className={isActive("/admin", false) ? "shell-nav-active" : ""}>
              Admin
            </Link>
          )}
        </nav>
        <div className="shell-account">
          <ThemeToggle />
          <span className="account-email">{user?.email}</span>
          {isAdmin && <span className="role-badge">admin</span>}
          <button className="btn-ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className={wide ? "shell-main shell-main-wide" : "shell-main"}>{children}</main>
    </div>
  );
}
