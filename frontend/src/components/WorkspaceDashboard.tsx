import { useEffect, useState, type MouseEvent } from "react";

import { listRecentServers } from "../api/servers";
import { getWorkspaceSummary } from "../api/workspace";
import useMinimumInitialLoading from "../hooks/useMinimumInitialLoading";
import type { Server, WorkspaceSummary } from "../types/server";
import Button from "./ui/Button";
import {
  DashboardMetricSkeletons,
  DashboardQuickActionSkeleton,
  DashboardRecentServerSkeleton,
} from "./ui/LoadingSkeletons";

type DashboardSettingsSection = "values" | "secrets" | "members";

type WorkspaceDashboardProps = {
  servers: Server[];
  onOpenServers: () => void;
  getSettingsHref: (section: DashboardSettingsSection) => string;
  onOpenSettings: (section: DashboardSettingsSection) => void;
  onOpenTools: (server: Server, capability?: "tools" | "prompts" | "connect") => void;
  setupGuideDismissed: boolean;
  onDismissSetupGuide: () => void;
};

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function WorkspaceDashboard({
  servers,
  onOpenServers,
  getSettingsHref,
  onOpenSettings,
  onOpenTools,
  setupGuideDismissed,
  onDismissSetupGuide,
}: WorkspaceDashboardProps) {
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  const [summaryRefreshKey, setSummaryRefreshKey] = useState(0);
  const [recentServers, setRecentServers] = useState<Server[]>([]);
  const [loadingRecentServers, setLoadingRecentServers] = useState(true);
  const [recentServersError, setRecentServersError] = useState("");
  const [recentServersRefreshKey, setRecentServersRefreshKey] = useState(0);
  const showSummarySkeleton = useMinimumInitialLoading(loadingSummary);
  const showRecentServersSkeleton = useMinimumInitialLoading(loadingRecentServers);

  useEffect(() => {
    let active = true;
    setLoadingSummary(true);
    setSummaryError("");
    void getWorkspaceSummary()
      .then((result) => {
        if (active) setSummary(result);
      })
      .catch((reason: unknown) => {
        if (active) {
          setSummary(null);
          setSummaryError(reason instanceof Error ? reason.message : "Could not load workspace totals.");
        }
      })
      .finally(() => {
        if (active) setLoadingSummary(false);
      });

    return () => {
      active = false;
    };
  }, [summaryRefreshKey]);

  useEffect(() => {
    let active = true;
    setLoadingRecentServers(true);
    setRecentServersError("");
    void listRecentServers()
      .then((result) => {
        if (active) setRecentServers(result);
      })
      .catch((reason: unknown) => {
        if (active) {
          setRecentServers([]);
          setRecentServersError(
            reason instanceof Error ? reason.message : "Could not load recent servers.",
          );
        }
      })
      .finally(() => {
        if (active) setLoadingRecentServers(false);
      });

    return () => {
      active = false;
    };
  }, [recentServersRefreshKey]);

  function retrySummary() {
    setSummaryRefreshKey((current) => current + 1);
  }

  function retryRecentServers() {
    setRecentServersRefreshKey((current) => current + 1);
  }

  const capabilitiesCount = (summary?.tool_count ?? 0) + (summary?.prompt_count ?? 0);
  const hasPublishedCapability =
    !!summary && summary.active_tool_count + summary.prompt_count > 0;
  const summaryBusy = loadingSummary || showSummarySkeleton;
  const recentServersBusy = loadingRecentServers || showRecentServersSkeleton;
  const summaryValue = (value: number | undefined): number | string =>
    loadingSummary ? "Loading" : summaryError || value === undefined ? "Unavailable" : value;

  function openSettingsLink(
    event: MouseEvent<HTMLAnchorElement>,
    section: DashboardSettingsSection,
  ) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    onOpenSettings(section);
  }

  return (
    <>
      <section className="page-heading dashboard-heading">
        <div className="page-title-group">
          <h1>Workspace overview</h1>
          <p className="subtitle">Manage endpoints and the tools available to your MCP clients.</p>
        </div>
        <Button variant="primary" className="dashboard-create-button" onClick={onOpenServers} type="button">
          <svg aria-hidden="true" viewBox="0 0 20 20">
            <path d="M10 4v12M4 10h12" />
          </svg>
          Add MCP server
        </Button>
      </section>

      <section
        className="dashboard-metrics"
        aria-label={summaryBusy ? "Loading workspace totals" : "Workspace totals"}
        aria-busy={summaryBusy}
        role={summaryBusy ? "status" : undefined}
      >
        {summaryBusy ? <DashboardMetricSkeletons /> : (
          <>
        <article className="panel dashboard-metric">
          <span className="dashboard-metric-icon server-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <rect x="3.25" y="3.25" width="13.5" height="5.5" rx="1.5" />
              <rect x="3.25" y="11.25" width="13.5" height="5.5" rx="1.5" />
              <path d="M6.5 6h.01M6.5 14h.01M10 6h3.5M10 14h3.5" />
            </svg>
          </span>
          <span className="dashboard-metric-copy">
            <span className="dashboard-metric-label">MCP servers</span>
            <strong>{summaryValue(summary?.server_count)}</strong>
            <span className="dashboard-metric-caption">Configured in this workspace</span>
          </span>
        </article>
        <article className="panel dashboard-metric">
          <span className="dashboard-metric-icon tool-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <path d="m7.25 4.25-5 5.75 5 5.75M12.75 4.25l5 5.75-5 5.75M11.5 2.75l-3 14.5" />
            </svg>
          </span>
          <span className="dashboard-metric-copy">
            <span className="dashboard-metric-label">Tools</span>
            <strong>{summaryValue(summary?.tool_count)}</strong>
            <span className="dashboard-metric-caption">
              {summary && !summaryError && !loadingSummary
                ? `${summary.active_tool_count} active`
                : "Across all MCP servers"}
            </span>
          </span>
        </article>
        <article className="panel dashboard-metric">
          <span className="dashboard-metric-icon prompt-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <path d="M3.5 4.5h13v9h-7l-4 3v-3h-2z" />
              <path d="M6.5 7.5h7M6.5 10.5h4" />
            </svg>
          </span>
          <span className="dashboard-metric-copy">
            <span className="dashboard-metric-label">Prompts</span>
            <strong>{summaryValue(summary?.prompt_count)}</strong>
            <span className="dashboard-metric-caption">Defined across all MCP servers</span>
          </span>
        </article>
        <a
          className="panel dashboard-metric dashboard-metric-link"
          href={getSettingsHref("secrets")}
          onClick={(event) => openSettingsLink(event, "secrets")}
        >
          <span className="dashboard-metric-icon secret-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <rect x="4" y="8.5" width="12" height="8.25" rx="1.5" />
              <path d="M6.75 8.5V6a3.25 3.25 0 0 1 6.5 0v2.5M10 11.5v2.25" />
            </svg>
          </span>
          <span className="dashboard-metric-copy">
            <span className="dashboard-metric-label">Server tokens</span>
            <strong>{summaryValue(summary?.secret_count)}</strong>
            <span className="dashboard-metric-caption">Protect MCP endpoints</span>
          </span>
        </a>
        <a
          className="panel dashboard-metric dashboard-metric-link"
          href={getSettingsHref("members")}
          onClick={(event) => openSettingsLink(event, "members")}
        >
          <span className="dashboard-metric-icon member-metric-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <circle cx="7" cy="6.25" r="2.5" />
              <path d="M2.75 16v-1.25a4.25 4.25 0 0 1 8.5 0V16zM13 4.25a2.5 2.5 0 0 1 0 4.75M14.25 11.25a4 4 0 0 1 3 3.875V16h-3" />
            </svg>
          </span>
          <span className="dashboard-metric-copy">
            <span className="dashboard-metric-label">Members</span>
            <strong>{summaryValue(summary?.member_count)}</strong>
            <span className="dashboard-metric-caption">Manage team access</span>
          </span>
        </a>
          </>
        )}
      </section>

      {!setupGuideDismissed && (
        <section className="dashboard-setup-guide" aria-labelledby="dashboard-setup-title">
          <div className="dashboard-setup-heading">
            <div>
              <span className="dashboard-setup-kicker">GET STARTED</span>
              <h2 id="dashboard-setup-title">Build your first MCP connection</h2>
              <p>Follow these steps to create a server, add a capability, and connect a client.</p>
            </div>
            <Button
              variant="text"
              className="dashboard-setup-dismiss"
              onClick={onDismissSetupGuide}
              type="button"
            >
              Dismiss guide
            </Button>
          </div>
          <ol className="dashboard-setup-steps">
            <li className={servers.length > 0 ? "complete" : ""}>
              <span className="dashboard-setup-number">1</span>
              <div>
                <strong>Create an MCP server</strong>
                <p>{servers.length > 0 ? "An endpoint is configured for this workspace." : "Choose a name and access mode for your endpoint."}</p>
              </div>
            </li>
            <li className={hasPublishedCapability ? "complete" : ""}>
              <span className="dashboard-setup-number">2</span>
              <div>
                <strong>Add a tool or prompt</strong>
                <p>
                  {loadingSummary
                    ? "Loading workspace capability totals."
                    : summaryError
                      ? "Capability totals are unavailable. Retry from Workspace totals."
                      : hasPublishedCapability
                        ? `${summary?.active_tool_count ?? 0} published tools and ${summary?.prompt_count ?? 0} prompts are available.`
                        : capabilitiesCount > 0
                          ? "Tool drafts are saved but not published yet. Add a prompt or configure the isolated runner."
                          : "Add a capability that your MCP client can use."}
                </p>
              </div>
            </li>
            <li>
              <span className="dashboard-setup-number">3</span>
              <div>
                <strong>Connect an MCP client</strong>
                <p>Get the right endpoint and authentication details for your client.</p>
              </div>
            </li>
          </ol>
        </section>
      )}

      {summaryError && !showSummarySkeleton ? (
        <div className="message error-message dashboard-inline-error" role="alert">
          <span>Workspace totals are unavailable: {summaryError}</span>
          <Button variant="text" onClick={retrySummary} type="button">Retry totals</Button>
        </div>
      ) : null}

      <section className="dashboard-content-grid">
        <section className="panel dashboard-panel dashboard-recent-panel">
          <div className="dashboard-panel-heading">
            <div>
              <h2>Recent MCP servers</h2>
              <p>Your latest server endpoints.</p>
            </div>
            <Button variant="text" onClick={onOpenServers} type="button">View all</Button>
          </div>

          {recentServersBusy ? (
            <DashboardRecentServerSkeleton />
          ) : recentServersError ? (
            <div className="dashboard-list-state dashboard-load-error">
              <p role="alert">{recentServersError}</p>
              <Button variant="secondary" onClick={retryRecentServers} type="button">Retry</Button>
            </div>
          ) : recentServers.length === 0 ? (
            <div className="dashboard-empty-state">
              <span className="dashboard-empty-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <rect x="4" y="4" width="16" height="6" rx="1.5" />
                  <rect x="4" y="14" width="16" height="6" rx="1.5" />
                  <path d="M7 7h.01M7 17h.01M11 7h5M11 17h5" />
                </svg>
              </span>
              <h3>Set up your first MCP server</h3>
              <p>Create a server endpoint to start connecting your tools to MCP clients.</p>
              <Button variant="secondary" onClick={onOpenServers} type="button">
                Create an MCP server
              </Button>
            </div>
          ) : (
            <div className="dashboard-server-list">
              <div className="dashboard-table-header" aria-hidden="true">
                <span>Server</span>
                <span>Access</span>
                <span className="dashboard-created-heading">Created</span>
                <span />
              </div>
              {recentServers.map((server) => (
                <button
                  className="dashboard-server-row"
                  key={server.id}
                  onClick={() => onOpenTools(server)}
                  type="button"
                  aria-label={`Open tools for ${server.name}`}
                >
                  <span className="dashboard-server-mark" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <rect x="3.25" y="3.25" width="13.5" height="5.5" rx="1.5" />
                      <rect x="3.25" y="11.25" width="13.5" height="5.5" rx="1.5" />
                      <path d="M6.5 6h.01M6.5 14h.01M10 6h3.5M10 14h3.5" />
                    </svg>
                  </span>
                  <span className="dashboard-server-copy">
                    <strong>{server.name}</strong>
                    <span>{server.description || "No description provided"}</span>
                  </span>
                  <span className={`dashboard-auth-badge${server.auth_mode === "protected" ? " protected" : ""}`}>
                    {server.auth_mode === "protected" ? "Protected" : "Standard"}
                  </span>
                  <span className="dashboard-server-date">{formatDate(server.created_at)}</span>
                  <svg className="dashboard-row-chevron" aria-hidden="true" viewBox="0 0 16 16">
                    <path d="m6 3.5 4.5 4.5L6 12.5" />
                  </svg>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="panel dashboard-panel dashboard-actions-panel">
          <div className="dashboard-panel-heading">
            <div>
              <h2>Quick actions</h2>
              <p>Continue building your workspace.</p>
            </div>
          </div>
          {recentServersBusy ? (
            <DashboardQuickActionSkeleton />
          ) : (
          <div className="dashboard-actions">
            {recentServers.length > 0 ? (
              <button
                className="dashboard-action"
                onClick={() => onOpenTools(recentServers[0])}
                type="button"
              >
                <span className="dashboard-action-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20">
                    <path d="m7 5-4 5 4 5M13 5l4 5-4 5M11.5 3l-3 14" />
                  </svg>
                </span>
                <span><strong>Build a tool</strong><small>Open tools for {recentServers[0].name}</small></span>
                <svg className="dashboard-row-chevron" aria-hidden="true" viewBox="0 0 16 16">
                  <path d="m6 3.5 4.5 4.5L6 12.5" />
                </svg>
              </button>
            ) : null}
            <button className="dashboard-action" onClick={() => onOpenSettings("secrets")} type="button">
              <span className="dashboard-action-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <rect x="4" y="8.5" width="12" height="8.25" rx="1.5" />
                  <path d="M6.75 8.5V6a3.25 3.25 0 0 1 6.5 0v2.5M10 11.5v2.25" />
                </svg>
              </span>
              <span><strong>Manage server tokens</strong><small>Protect MCP endpoints</small></span>
              <svg className="dashboard-row-chevron" aria-hidden="true" viewBox="0 0 16 16">
                <path d="m6 3.5 4.5 4.5L6 12.5" />
              </svg>
            </button>
            <button className="dashboard-action" onClick={() => onOpenSettings("values")} type="button">
              <span className="dashboard-action-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <path d="M4 5.5h12M4 10h12M4 14.5h7" />
                  <circle cx="7" cy="5.5" r="1.25" />
                  <circle cx="13" cy="10" r="1.25" />
                </svg>
              </span>
              <span><strong>Manage variables &amp; secrets</strong><small>Reuse configuration across MCP definitions</small></span>
              <svg className="dashboard-row-chevron" aria-hidden="true" viewBox="0 0 16 16">
                <path d="m6 3.5 4.5 4.5L6 12.5" />
              </svg>
            </button>
            {recentServersError ? (
              <p className="dashboard-action-hint">
                Server-specific actions are unavailable. Retry the recent servers list.
              </p>
            ) : recentServers.length === 0 ? (
              <p className="dashboard-action-hint">Add a server first to start creating tools.</p>
            ) : null}
          </div>
          )}
        </section>
      </section>
    </>
  );
}
