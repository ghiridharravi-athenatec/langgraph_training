import { useParams } from "react-router-dom";
import AppShell from "../components/AppShell";

export default function ProjectPlaceholder() {
  const { projectId } = useParams();

  return (
    <AppShell>
      <div className="empty-state">
        <h1>IN DEVELOPMENT</h1>
        <p className="muted">
          This feature is being prepared. Check back soon.
        </p>
      </div>
    </AppShell>
  );
}
