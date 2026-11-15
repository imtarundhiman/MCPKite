import { useCallback, useEffect, useState, type MouseEvent } from "react";

import {
  getAuthStatus,
  getCurrentUser,
  getInvitePreview,
  login,
  logout,
  register,
} from "./api/auth";
import { ApiError, clearCsrfToken, initializeCsrfToken } from "./api/client";
import { listSecrets } from "./api/secrets";
import {
  createServer,
  deleteServer,
  listServers,
  updateServer,
} from "./api/servers";
import Button from "./components/ui/Button";
import AuthScreen from "./components/AuthScreen";
import CreateServerForm, {
  createEmptyServerDraft,
  type ServerDraft,
} from "./components/CreateServerForm";
import { AccountControls, Footer, Header } from "./components/PageChrome";
import ServerDirectory from "./components/ServerDirectory";
import ToolStudio from "./components/ToolStudio";
import WorkspaceDashboard from "./components/WorkspaceDashboard";
import WorkspaceSettings, { type SettingsSection } from "./components/WorkspaceSettings";
import type {
  AuthUser,
  CreatedSecret,
  Secret,
  Server,
  ServerUpdateInput,
} from "./types/server";

type ActiveView = "dashboard" | "servers" | "settings" | "tools";
type ActiveCapability = "tools" | "prompts" | "resources" | "connect";
type WorkspaceRoute = {
  view: ActiveView;
  serverId: string | null;
  capability: ActiveCapability;
  settingsSection: SettingsSection;
};

const initialRoute: WorkspaceRoute = {
  view: "dashboard",
  serverId: null,
  capability: "tools",
  settingsSection: "overview",
};

const SERVER_DRAFT_STORAGE_KEY = "fastmcp-server-draft-v1";

function isServerDraft(value: unknown): value is ServerDraft {
  if (typeof value !== "object" || value === null) return false;
  const draft = value as Record<string, unknown>;
  return (
    typeof draft.name === "string" &&
    draft.name.length <= 80 &&
    typeof draft.description === "string" &&
    draft.description.length <= 300 &&
    (draft.authMode === "normal" || draft.authMode === "protected") &&
    typeof draft.secretId === "string"
  );
}

function readStoredServerDraft(): { draft: ServerDraft; warning: string } {
  if (typeof window === "undefined") {
    return { draft: createEmptyServerDraft(), warning: "" };
  }
  let storedDraft: string | null;
  try {
    storedDraft = window.sessionStorage.getItem(SERVER_DRAFT_STORAGE_KEY);
  } catch {
    return {
      draft: createEmptyServerDraft(),
      warning: "Tab storage is unavailable, so server details will not survive a page refresh.",
    };
  }
  if (!storedDraft) return { draft: createEmptyServerDraft(), warning: "" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(storedDraft);
  } catch {
    parsed = null;
  }
  if (isServerDraft(parsed)) return { draft: parsed, warning: "" };
  try {
    window.sessionStorage.removeItem(SERVER_DRAFT_STORAGE_KEY);
  } catch {
    return {
      draft: createEmptyServerDraft(),
      warning: "Tab storage is unavailable, so server details will not survive a page refresh.",
    };
  }
  return {
    draft: createEmptyServerDraft(),
    warning: "A saved server draft could not be restored and was cleared.",
  };
}

function isEmptyServerDraft(draft: ServerDraft): boolean {
  return (
    draft.name === "" &&
    draft.description === "" &&
    draft.authMode === "normal" &&
    draft.secretId === ""
  );
}

function routeFromLocation(): WorkspaceRoute {
  if (window.location.pathname.startsWith("/join/")) return initialRoute;

  const params = new URLSearchParams(window.location.search);
  const viewValue = params.get("view");
  const view: ActiveView =
    viewValue === "servers" || viewValue === "settings" || viewValue === "tools"
      ? viewValue
      : "dashboard";
  const capabilityValue = params.get("capability");
  const capability: ActiveCapability =
    capabilityValue === "prompts" ||
    capabilityValue === "resources" ||
    capabilityValue === "connect"
      ? capabilityValue
      : "tools";
  const sectionValue = params.get("section");
  const settingsSection: SettingsSection =
    sectionValue === "values" || sectionValue === "secrets" || sectionValue === "members"
      ? sectionValue
      : "overview";

  return {
    view,
    serverId: view === "tools" ? params.get("server") : null,
    capability: view === "tools" ? capability : "tools",
    settingsSection: view === "settings" ? settingsSection : "overview",
  };
}

function routeHref(route: WorkspaceRoute): string {
  if (route.view === "dashboard") return "/";

  const params = new URLSearchParams({ view: route.view });
  if (route.view === "tools") {
    if (route.serverId) params.set("server", route.serverId);
    if (route.capability !== "tools") params.set("capability", route.capability);
  } else if (route.view === "settings" && route.settingsSection !== "overview") {
    params.set("section", route.settingsSection);
  }
  return `/?${params.toString()}`;
}

function inviteTokenFromLocation(): string | null {
  const match = window.location.pathname.match(/^\/join\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : null;
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [workspaceInitialized, setWorkspaceInitialized] = useState(false);
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState("");
  const [inviteWorkspaceName, setInviteWorkspaceName] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState("");
  const [route, setRoute] = useState<WorkspaceRoute>(routeFromLocation);
  const [storedDraft] = useState(readStoredServerDraft);
  const [serverDraft, setServerDraft] = useState<ServerDraft>(storedDraft.draft);
  const [draftPersistenceWarning, setDraftPersistenceWarning] = useState(storedDraft.warning);
  const [resumingServerSetup, setResumingServerSetup] = useState(false);
  const [setupGuideDismissed, setSetupGuideDismissed] = useState(false);
  const [servers, setServers] = useState<Server[]>([]);
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [createdSecret, setCreatedSecret] = useState<CreatedSecret | null>(null);
  const [loadingServers, setLoadingServers] = useState(true);
  const [managementLoadError, setManagementLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeView = route.view;
  const selectedServerId = route.serverId;
  const inviteToken = inviteTokenFromLocation();
  const selectedServer = servers.find((server) => server.id === selectedServerId) ?? null;

  function navigateTo(nextRoute: WorkspaceRoute, replace = false) {
    const href = routeHref(nextRoute);
    if (`${window.location.pathname}${window.location.search}` !== href) {
      if (replace) {
        window.history.replaceState(null, "", href);
      } else {
        window.history.pushState(null, "", href);
      }
    }
    setRoute(nextRoute);
  }

  function navigateFromLink(event: MouseEvent<HTMLAnchorElement>, nextRoute: WorkspaceRoute) {
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
    navigateTo(nextRoute);
  }

  function clearStoredServerDraft() {
    try {
      window.sessionStorage.removeItem(SERVER_DRAFT_STORAGE_KEY);
      setDraftPersistenceWarning("");
    } catch {
      setDraftPersistenceWarning("Tab storage is unavailable, so the saved server draft could not be cleared.");
    }
  }

  function updateServerDraft(draft: ServerDraft) {
    setServerDraft(draft);
    setDraftPersistenceWarning("");
  }

  useEffect(() => {
    if (!user || typeof window === "undefined") return;
    try {
      if (isEmptyServerDraft(serverDraft)) {
        window.sessionStorage.removeItem(SERVER_DRAFT_STORAGE_KEY);
      } else {
        window.sessionStorage.setItem(SERVER_DRAFT_STORAGE_KEY, JSON.stringify(serverDraft));
      }
      setDraftPersistenceWarning("");
    } catch {
      setDraftPersistenceWarning(
        "Tab storage is unavailable, so server details will not survive a page refresh.",
      );
    }
  }, [serverDraft, user]);

  useEffect(() => {
    function handlePopState() {
      setRoute(routeFromLocation());
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        await initializeCsrfToken();
        const status = await getAuthStatus();
        if (!active) return;
        setWorkspaceInitialized(status.workspace_initialized);

        if (status.workspace_initialized) {
          try {
            const currentUser = await getCurrentUser();
            if (active) setUser(currentUser);
          } catch (reason) {
            if (!(reason instanceof ApiError && reason.status === 401)) {
              throw reason;
            }
          }
        }

        if (inviteToken) {
          try {
            const preview = await getInvitePreview(inviteToken);
            if (active) setInviteWorkspaceName(preview.workspace_name);
          } catch (reason) {
            if (active) {
              setInviteError(
                reason instanceof Error ? reason.message : "This invitation is no longer valid.",
              );
            }
          }
        }
      } catch (reason) {
        if (active) {
          setBootError(reason instanceof Error ? reason.message : "Could not connect to the server.");
        }
      } finally {
        if (active) setBooting(false);
      }
    }
    void initialize();
    return () => {
      active = false;
    };
  }, [inviteToken]);

  const loadManagementData = useCallback(async () => {
    setError("");
    setManagementLoadError("");
    setLoadingServers(true);
    try {
      const [nextServers, nextSecrets] = await Promise.all([listServers(), listSecrets()]);
      setServers(nextServers);
      setSecrets(nextSecrets);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not load workspace data.";
      setError(message);
      setManagementLoadError(message);
    } finally {
      setLoadingServers(false);
    }
  }, []);

  useEffect(() => {
    if (user) void loadManagementData();
  }, [user, loadManagementData]);

  async function handleLogin(email: string, password: string) {
    const signedInUser = await login({ email, password });
    setUser(signedInUser);
  }

  async function handleRegister(
    displayName: string,
    email: string,
    password: string,
    workspaceName?: string,
    token?: string,
  ) {
    const createdUser = await register({
      email,
      password,
      display_name: displayName,
      ...(workspaceName ? { workspace_name: workspaceName } : {}),
      ...(token ? { invite_token: token } : {}),
    });
    setWorkspaceInitialized(true);
    setInviteError("");
    setUser(createdUser);
    navigateTo(initialRoute, true);
  }

  async function handleLogout() {
    try {
      await logout();
      clearCsrfToken();
      clearStoredServerDraft();
      setServerDraft(createEmptyServerDraft());
      setUser(null);
      setResumingServerSetup(false);
      setSetupGuideDismissed(false);
      setCreatedSecret(null);
      navigateTo(initialRoute, true);
      await initializeCsrfToken();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not sign out.");
    }
  }

  async function handleCreateServer(draft: ServerDraft): Promise<Server | null> {
    setError("");
    setNotice("");
    const server = await createServer({
      name: draft.name,
      description: draft.description,
      auth_mode: draft.authMode,
      secret_id: draft.authMode === "protected" ? draft.secretId : null,
    });
    setServers((current) => [...current, server]);
    setNotice("MCP server created and saved.");
    setServerDraft(createEmptyServerDraft());
    clearStoredServerDraft();
    setResumingServerSetup(false);
    if (draft.authMode === "protected") {
      try {
        setSecrets(await listSecrets());
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not refresh the server token list.");
      }
    }
    return server;
  }

  async function handleUpdateServer(
    serverId: string,
    input: ServerUpdateInput,
  ): Promise<Server> {
    const updated = await updateServer(serverId, input);
    setServers((current) => current.map((server) => server.id === serverId ? updated : server));
    try {
      setSecrets(await listSecrets());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh the server token list.");
    }
    return updated;
  }

  async function handleDeleteServer(serverId: string): Promise<void> {
    setError("");
    setNotice("");
    const result = await deleteServer(serverId);
    setServers((current) => current.filter((server) => server.id !== serverId));
    const warnings: string[] = [];

    if (result.file_cleanup_failures > 0) {
      warnings.push(
        `The server was deleted, but ${result.file_cleanup_failures} uploaded resource file(s) could not be removed from storage.`,
      );
    }
    if (result.runtime_shutdown_failed) {
      warnings.push(
        "The server was deleted and its endpoint was removed, but runtime shutdown reported an error.",
      );
    }
    try {
      setSecrets(await listSecrets());
    } catch (reason) {
      const message =
        reason instanceof Error ? reason.message : "Could not refresh the server token list.";
      warnings.push(`The server was deleted, but ${message}`);
    }

    navigateTo({ ...initialRoute, view: "servers" });
    if (warnings.length > 0) {
      setError(warnings.join(" "));
    } else {
      setNotice("MCP server deleted. Its assigned server token is now unassigned.");
    }
  }

  if (booting) {
    return (
      <div className="auth-page">
        <main className="auth-page-content">
          <div className="state-box">Loading workspace…</div>
        </main>
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="auth-page">
        <main className="auth-page-content">
          <div className="message error-message" role="alert">{bootError}</div>
        </main>
      </div>
    );
  }

  if (!user || (inviteToken && user)) {
    if (user && inviteToken) {
      return (
        <div className="shell auth-shell">
          <Header user={user} onLogout={() => void handleLogout()} />
          <main className="auth-content">
            <section className="auth-panel panel">
              <h1>Already signed in</h1>
              <p>Sign out before accepting this invitation with another account.</p>
              <Button variant="primary" onClick={() => void handleLogout()} type="button">Sign out</Button>
            </section>
          </main>
          <Footer />
        </div>
      );
    }
    return (
      <div className="auth-page">
        <main className="auth-page-content">
          <AuthScreen
            workspaceInitialized={workspaceInitialized}
            inviteToken={inviteToken}
            inviteWorkspaceName={inviteWorkspaceName}
            inviteError={inviteError}
            onLogin={handleLogin}
            onRegister={handleRegister}
          />
        </main>
      </div>
    );
  }

  return (
    <div className="workspace-shell">
      <Header user={user} onLogout={() => void handleLogout()} />
      <div className="workspace-layout">
        <aside className="workspace-sidebar">
          <nav className="workspace-nav" aria-label="Workspace sections">
            <a
              className={`sidebar-link dashboard-nav-link${activeView === "dashboard" ? " active" : ""}`}
              aria-current={activeView === "dashboard" ? "page" : undefined}
              href={routeHref(initialRoute)}
              onClick={(event) => navigateFromLink(event, initialRoute)}
            >
              <span className="sidebar-nav-icon" aria-hidden="true">
                <svg viewBox="0 0 18 18">
                  <rect x="2.5" y="2.5" width="5" height="5" rx="1" />
                  <rect x="10.5" y="2.5" width="5" height="5" rx="1" />
                  <rect x="2.5" y="10.5" width="5" height="5" rx="1" />
                  <rect x="10.5" y="10.5" width="5" height="5" rx="1" />
                </svg>
              </span>
              Dashboard
            </a>
            <a
              className={`sidebar-link${activeView === "servers" ? " active" : ""}`}
              aria-current={activeView === "servers" ? "page" : undefined}
              href={routeHref({ ...initialRoute, view: "servers" })}
              onClick={(event) => navigateFromLink(event, { ...initialRoute, view: "servers" })}
            >
              <span className="sidebar-nav-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <rect x="3" y="3" width="14" height="5.5" rx="1.5" />
                  <rect x="3" y="11.5" width="14" height="5.5" rx="1.5" />
                  <path d="M6 5.75h.01M6 14.25h.01" />
                </svg>
              </span>
              MCP servers
              <span className="sidebar-count">{servers.length}</span>
            </a>
            <a
              className={`sidebar-link sidebar-settings-link${activeView === "settings" ? " active" : ""}`}
              aria-current={activeView === "settings" ? "page" : undefined}
              href={routeHref({ ...initialRoute, view: "settings" })}
              onClick={(event) =>
                navigateFromLink(event, { ...initialRoute, view: "settings" })
              }
            >
              <span className="sidebar-nav-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <path d="M8.2 2.8h3.6l.45 1.8c.5.17.95.43 1.36.77l1.78-.48 1.8 3.12-1.32 1.3c.06.5.06.98 0 1.46l1.32 1.32-1.8 3.12-1.78-.49a6.6 6.6 0 0 1-1.36.78l-.45 1.8H8.2l-.45-1.8a6.5 6.5 0 0 1-1.36-.78l-1.78.49-1.8-3.12 1.32-1.32a6.2 6.2 0 0 1 0-1.46L2.8 8l1.8-3.12 1.78.48a6.5 6.5 0 0 1 1.36-.77l.45-1.8Z" />
                  <circle cx="10" cy="10" r="2.25" />
                </svg>
              </span>
              Settings
            </a>
          </nav>
          <div className="sidebar-bottom">
            <AccountControls
              className="sidebar-account-controls"
              user={user}
              onLogout={() => void handleLogout()}
            />
          </div>
        </aside>

        <main className={`workspace-main${activeView === "servers" ? " workspace-main-servers" : ""}`}>
          {createdSecret && activeView !== "settings" && (
            <div className="message secret-pending-notice" role="status">
              <div>
                <strong>A new server access token is ready to copy</strong>
                <p>Save it from Settings before refreshing or signing out; its value cannot be retrieved later.</p>
              </div>
              <Button
                variant="secondary"
                onClick={() =>
                  navigateTo({ ...initialRoute, view: "settings", settingsSection: "secrets" })
                }
                type="button"
              >
                Return to Settings
              </Button>
            </div>
          )}
          {activeView === "dashboard" ? (
            <WorkspaceDashboard
              servers={servers}
              onOpenServers={() => navigateTo({ ...initialRoute, view: "servers" })}
              getSettingsHref={(settingsSection) =>
                routeHref({ ...initialRoute, view: "settings", settingsSection })
              }
              onOpenSettings={(settingsSection) =>
                navigateTo({ ...initialRoute, view: "settings", settingsSection })
              }
              onOpenTools={(server, capability = "tools") => {
                navigateTo({ ...initialRoute, view: "tools", serverId: server.id, capability });
              }}
              setupGuideDismissed={setupGuideDismissed}
              onDismissSetupGuide={() => setSetupGuideDismissed(true)}
            />
          ) : activeView === "servers" ? (
            <>
              <section className="page-heading">
                <div className="page-title-group">
                  <p className="page-kicker">Workspace</p>
                  <h1>MCP servers</h1>
                  <p className="subtitle">Create endpoints and connect them to your MCP clients.</p>
                </div>
                <div className="server-count">
                  <span className="server-count-value">{servers.length}</span>
                  <span className="server-count-label">
                    <strong>Configured</strong>
                    <span>servers in this workspace</span>
                  </span>
                </div>
              </section>

              <section className="content-grid">
                <CreateServerForm
                  secrets={secrets}
                  onCreate={handleCreateServer}
                  draft={serverDraft}
                  onDraftChange={updateServerDraft}
                  onOpenSettings={() => {
                    setResumingServerSetup(true);
                    navigateTo({
                      ...initialRoute,
                      view: "settings",
                      settingsSection: "secrets",
                    });
                  }}
                  onOpenTools={(serverId) =>
                    navigateTo({
                      ...initialRoute,
                      view: "tools",
                      serverId,
                      capability: "tools",
                    })
                  }
                  error={error}
                  notice={notice}
                  persistenceWarning={draftPersistenceWarning}
                />
                <ServerDirectory
                  serverCount={servers.length}
                  onRefresh={loadManagementData}
                  getServerHref={(serverId) =>
                    routeHref({
                      ...initialRoute,
                      view: "tools",
                      serverId,
                      capability: "tools",
                    })
                  }
                  onOpenServer={(serverId) =>
                    navigateTo({
                      ...initialRoute,
                      view: "tools",
                      serverId,
                      capability: "tools",
                    })
                  }
                />
              </section>
            </>
          ) : activeView === "settings" ? (
            <>
              <section className="page-heading">
                <div className="page-title-group">
                  <p className="page-kicker">Workspace</p>
                  <h1>
                    {route.settingsSection === "values"
                      ? "Variables & secrets"
                      : route.settingsSection === "secrets"
                        ? "Server tokens"
                        : route.settingsSection === "members"
                          ? "Members"
                          : "Workspace settings"}
                  </h1>
                  <p className="subtitle">
                    {route.settingsSection === "values"
                      ? "Store workspace values for reuse in tools, prompts, and resources."
                      : route.settingsSection === "secrets"
                        ? "Create and manage bearer tokens used to protect MCP endpoints."
                        : route.settingsSection === "members"
                          ? "Manage workspace members and invitation links."
                          : "Manage workspace details, shared credentials, and team access."}
                  </p>
                </div>
              </section>
              <WorkspaceSettings
                user={user}
                onUserUpdated={setUser}
                section={route.settingsSection}
                getSectionHref={(settingsSection) =>
                  routeHref({ ...initialRoute, view: "settings", settingsSection })
                }
                onSectionChange={(settingsSection) =>
                  navigateTo({ ...route, view: "settings", settingsSection })
                }
                createdSecret={createdSecret}
                onCreatedSecretChange={setCreatedSecret}
                onSecretsUpdated={loadManagementData}
                onResumeServerSetup={
                  resumingServerSetup
                    ? () => {
                        setResumingServerSetup(false);
                        navigateTo({ ...initialRoute, view: "servers" });
                      }
                    : undefined
                }
              />
            </>
          ) : selectedServer ? (
            <ToolStudio
              key={selectedServer.id}
              server={selectedServer}
              secrets={secrets}
              onUpdateServer={handleUpdateServer}
              onDeleteServer={handleDeleteServer}
              activeCapability={route.capability}
              getCapabilityHref={(capability) =>
                routeHref({
                  ...initialRoute,
                  view: "tools",
                  serverId: selectedServer.id,
                  capability,
                })
              }
              onCapabilityChange={(capability) =>
                navigateTo({ ...route, view: "tools", capability })
              }
            />
          ) : activeView === "tools" && selectedServerId ? (
            <section className="panel tool-empty-page" role={managementLoadError ? "alert" : undefined}>
              <h1>
                {loadingServers
                  ? "Loading server…"
                  : managementLoadError
                    ? "Could not verify this server"
                    : "Server not found"}
              </h1>
              <p>
                {loadingServers
                  ? "Checking that this server is available in your workspace."
                  : managementLoadError
                    ? managementLoadError
                    : "This server may have been removed or may no longer be available in this workspace."}
              </p>
              {managementLoadError && (
                <Button
                  variant="secondary"
                  onClick={() => void loadManagementData()}
                  type="button"
                >
                  Retry
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => navigateTo({ ...initialRoute, view: "servers" })}
                type="button"
              >
                Browse servers
              </Button>
            </section>
          ) : (
            <section className="panel tool-empty-page">
              <h1>Select an MCP server</h1>
              <p>Choose a server from the left navigation to manage its tool drafts.</p>
              <Button
                variant="secondary"
                onClick={() => navigateTo({ ...initialRoute, view: "servers" })}
                type="button"
              >
                Browse servers
              </Button>
            </section>
          )}

        </main>
      </div>
      <Footer />
    </div>
  );
}
