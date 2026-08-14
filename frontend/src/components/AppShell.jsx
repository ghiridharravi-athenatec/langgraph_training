import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function AppShell({ children, wide = false }) {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <header className="shell-header">
        <Link to="/" className="brand">
          <span className="brand-mark">✦</span>
          <span>AI Assistance</span>
        </Link>
        <nav className="shell-nav">
          <Link to="/">Projects</Link>
          <Link to="/instructions">Instructions</Link>
          {isAdmin && <Link to="/admin/users">Admin</Link>}
        </nav>
        <div className="shell-account">
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
