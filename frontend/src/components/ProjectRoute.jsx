import { Navigate, Outlet, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LoadingScreen from "./LoadingScreen";

/**
 * Frontend visibility check only - purely UX. The backend independently
 * enforces this on every API call via require_project_access(), which is the
 * real security boundary. A user who forges their way past this component
 * still gets 403s from the API.
 */
export default function ProjectRoute({ projectId }) {
  const { user, loading } = useAuth();
  const params = useParams();
  const resolvedProjectId = projectId || params.projectId;

  if (loading) return <LoadingScreen />;
  const hasAccess = user?.role === "admin" || user?.projects?.includes(resolvedProjectId);
  if (!hasAccess) return <Navigate to="/forbidden" replace />;

  return <Outlet />;
}
