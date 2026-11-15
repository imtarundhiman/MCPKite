import { useState } from "react";

import type { Server } from "../types/server";
import { mcpEndpointUrl } from "../utils/mcpEndpoint";

type ConnectionTarget = "host" | "inspector";

function inspectorEndpoint(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `http://backend:8000${normalizedPath}`;
}

export default function ServerConnectionGuide({ server }: { server: Server }) {
  const [target, setTarget] = useState<ConnectionTarget>("host");
  const [feedback, setFeedback] = useState("");
  const [copyFailed, setCopyFailed] = useState(false);
  const endpoint =
    target === "inspector"
      ? inspectorEndpoint(server.endpoint_path)
      : mcpEndpointUrl(server.endpoint_path);

  async function copyEndpoint() {
    try {
      await navigator.clipboard.writeText(endpoint);
      setFeedback("Endpoint copied.");
      setCopyFailed(false);
    } catch {
      setFeedback("Copy failed. Select the endpoint and copy it manually.");
      setCopyFailed(true);
    }
  }

  return (
    <section className="connection-guide" aria-labelledby={`connection-guide-title-${server.id}`}>
      <div className="connection-guide-heading">
        <div>
          <h2 id={`connection-guide-title-${server.id}`}>Connect an MCP client</h2>
          <p>Use this server’s Streamable HTTP endpoint in the client you want to connect.</p>
        </div>
        <span className={`server-access-pill${server.auth_mode === "protected" ? " protected" : ""}`}>
          {server.auth_mode === "protected" ? "Protected access" : "Standard access"}
        </span>
      </div>

      <div className="connection-guide-field">
        <label htmlFor={`connection-target-${server.id}`}>Client environment</label>
        <select
          id={`connection-target-${server.id}`}
          value={target}
          onChange={(event) => {
            setTarget(event.target.value === "inspector" ? "inspector" : "host");
            setFeedback("");
          }}
        >
          <option value="host">Client on this machine or a reachable host</option>
          <option value="inspector">Local MCP Inspector (Docker Compose)</option>
        </select>
      </div>

      <div className="connection-endpoint">
        <span className="endpoint-label">Server endpoint</span>
        <div className="endpoint-row">
          <code className="endpoint-url">{endpoint}</code>
          <button
            className="copy-endpoint-button icon-tooltip icon-tooltip--above-right"
            onClick={() => void copyEndpoint()}
            type="button"
            aria-label={`Copy endpoint for ${server.name}`}
            data-tooltip={`Copy endpoint for ${server.name}`}
          >
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
              <rect x="7" y="6" width="9" height="11" rx="1.5" />
              <path d="M13 6V4.5A1.5 1.5 0 0 0 11.5 3h-7A1.5 1.5 0 0 0 3 4.5v9A1.5 1.5 0 0 0 4.5 15H7" />
            </svg>
          </button>
        </div>
        {feedback && (
          <p className={`endpoint-feedback${copyFailed ? " endpoint-feedback-error" : ""}`} role={copyFailed ? "alert" : "status"}>
            {feedback}
          </p>
        )}
      </div>

      <p className="connection-target-help">
        {target === "inspector" ? (
          <>
            Local development only: Inspector runs inside Docker Compose, so use the backend service name above
            instead of localhost. Open the authenticated launch URL printed by{" "}
            <code>docker compose logs inspector</code>, then add this endpoint as a Streamable HTTP server.
          </>
        ) : (
          "Use the endpoint above for clients running on this machine or another host that can reach it. The Docker-only Inspector address is not for host clients."
        )}
      </p>

      <div className="connection-auth-guidance">
        <h3>Authentication</h3>
        {server.auth_mode === "protected" ? (
          <>
            <p>This server requires the bearer token assigned in its access settings. It is separate from reusable workspace secrets and your Studio sign-in.</p>
            <dl>
              <div><dt>Header</dt><dd><code>Authorization</code></dd></div>
              <div><dt>Value</dt><dd><code>Bearer &lt;your-secret&gt;</code></dd></div>
            </dl>
            <p className="form-note">Use the server token value saved when it was created. Studio cannot retrieve it again.</p>
          </>
        ) : (
          <p>No bearer token is required for this server’s current access mode.</p>
        )}
      </div>
    </section>
  );
}
