import { Link } from "react-router-dom";

export default function Forbidden() {
  return (
    <div className="status-page">
      <div className="status-mark">403</div>
      <h1>You don't have access to this project</h1>
      <p>Ask an admin to grant you permission, then refresh.</p>
      <Link to="/" className="btn-primary">
        Back to Projects
      </Link>
    </div>
  );
}
