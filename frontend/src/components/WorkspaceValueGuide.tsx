type WorkspaceValueGuideContext = "tool" | "prompt" | "resource";

const guideContent: Record<
  WorkspaceValueGuideContext,
  { example: string; explanation: string; caution: string }
> = {
  tool: {
    example: [
      "import os",
      "",
      'base_url = os.environ["OPENAI_BASE_URL"]',
      'api_key = os.environ["OPENAI_API_KEY"]',
    ].join("\n"),
    explanation:
      "In Python tools, read variables and secrets from os.environ using their exact saved names.",
    caution:
      "Use the secret inside the tool to authenticate requests, and do not include it in the tool result.",
  },
  prompt: {
    example: "Summarize {{report}} for ${AUDIENCE}.",
    explanation:
      "Use ${NAME} for a workspace variable or secret. Declared prompt arguments use {{argument}} instead.",
    caution:
      "A secret referenced here is inserted into the prompt returned to the MCP client. Only do this when that client should receive it; use a tool for API credentials.",
  },
  resource: {
    example: "Service endpoint: ${OPENAI_BASE_URL}",
    explanation:
      "Use ${NAME} in text content for a workspace variable or secret. URI placeholders such as {{document_id}} are separate.",
    caution:
      "Substituted values are visible to the client reading the resource. Only text resources support workspace value substitution.",
  },
};

export default function WorkspaceValueGuide({
  context,
}: {
  context: WorkspaceValueGuideContext;
}) {
  const content = guideContent[context];

  return (
    <details className="workspace-value-guide">
      <summary>Using workspace variables &amp; secrets</summary>
      <div className="workspace-value-guide-content">
        <p>
          First save a value in{" "}
          <a href="/?view=settings&section=values">Workspace Settings → Variables &amp; secrets</a>.
          Names are case-sensitive. Variable values can be viewed there; secret values stay hidden
          after saving.
        </p>
        <pre><code>{content.example}</code></pre>
        <p>{content.explanation}</p>
        <p className="workspace-value-guide-caution">{content.caution}</p>
      </div>
    </details>
  );
}
