import { useParams } from "react-router-dom";
import RagChatbot from "./RagChatbot";
import TracesProject from "./Traces";
import ProjectPlaceholder from "./ProjectPlaceholder";

/**
 * Maps a project id to its dedicated UI. Any newly registered project renders
 * the generic placeholder until it gets a real page - registering a project
 * never requires touching routing.
 */
export default function ProjectView() {
  const { projectId } = useParams();

  if (projectId === "ragchatbot") return <RagChatbot />;
  if (projectId === "guardrail-traces") return <TracesProject />;
  return <ProjectPlaceholder />;
}
