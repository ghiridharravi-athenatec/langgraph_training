import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="status-page">
      <div className="status-mark">404</div>
      <h1>Page not found</h1>
      <Link to="/" className="btn-primary">
        Back to Projects
      </Link>
    </div>
  );
}
