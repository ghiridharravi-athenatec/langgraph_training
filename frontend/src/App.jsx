import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminRoute from "./components/AdminRoute";
import ProjectRoute from "./components/ProjectRoute";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Dashboard from "./pages/Dashboard";
import ProjectView from "./pages/ProjectView";
import Instructions from "./pages/Instructions";
import AdminUsers from "./pages/AdminUsers";
import Forbidden from "./pages/Forbidden";
import NotFound from "./pages/NotFound";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />

        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/instructions" element={<Instructions />} />
          <Route path="/forbidden" element={<Forbidden />} />

          <Route element={<ProjectRoute />}>
            <Route path="/projects/:projectId" element={<ProjectView />} />
          </Route>

          <Route element={<AdminRoute />}>
            <Route path="/admin/users" element={<AdminUsers />} />
          </Route>
        </Route>

        <Route path="/404" element={<NotFound />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </AuthProvider>
  );
}
