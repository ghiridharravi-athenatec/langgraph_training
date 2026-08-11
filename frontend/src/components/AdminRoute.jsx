import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LoadingScreen from "./LoadingScreen";

export default function AdminRoute() {
  const { isAdmin, loading } = useAuth();

  if (loading) return <LoadingScreen />;
  if (!isAdmin) return <Navigate to="/forbidden" replace />;

  return <Outlet />;
}
