import { useEffect, useRef, useState } from "react";

import { listServerRegistryPage } from "../api/servers";
import PaginationControls from "./PaginationControls";
import type { PageSize, Server, ServerRegistryPage } from "../types/server";
import useMinimumInitialLoading from "../hooks/useMinimumInitialLoading";
import Button from "./ui/Button";
import { ServerListSkeleton } from "./ui/LoadingSkeletons";
import { ResourceCardLayout } from "./ui/ResourceManagement";

type ServerDirectoryProps = {
  serverCount: number;
  onRefresh: () => Promise<void>;
  getServerHref: (serverId: string) => string;
  onOpenServer: (serverId: string) => void;
};

function ServerCard({
  server,
  getServerHref,
  onOpenServer,
}: {
  server: Server;
  getServerHref: (serverId: string) => string;
  onOpenServer: (serverId: string) => void;
}) {
  const isProtected = server.auth_mode === "protected";
  const accessLabel = isProtected
    ? "Protected access. A bearer token is required."
    : "Standard access. No bearer token is required.";

  return (
    <ResourceCardLayout
      className="server-row"
      name={server.name}
      description={server.description.trim()}
      nameClassName="server-card-name"
      icon={
        <div className="server-icon" aria-hidden="true" title="MCP server">
          <svg viewBox="0 0 20 20" fill="none">
            <rect x="3.25" y="3.25" width="13.5" height="5.25" rx="1.25" />
            <rect x="3.25" y="11.5" width="13.5" height="5.25" rx="1.25" />
            <path d="M6 5.9h.01M6 14.15h.01" />
          </svg>
        </div>
      }
      footerLeading={
        <span
          className={`server-access-pill server-registry-access icon-tooltip icon-tooltip--above-left${
            isProtected ? " protected" : ""
          }`}
          role="img"
          aria-label={accessLabel}
          tabIndex={0}
          data-tooltip={accessLabel}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <rect x="4" y="9" width="12" height="8" rx="1.5" />
            {isProtected ? (
              <path d="M6.5 9V6.5a3.5 3.5 0 0 1 7 0V9" />
            ) : (
              <path d="M6.5 9V6.5a3.5 3.5 0 0 1 6.7-1.8" />
            )}
            <path d="M10 12v2" />
          </svg>
        </span>
      }
      footerAction={
        <a
          className="secondary-button resource-card-edit server-card-details icon-tooltip icon-tooltip--above-right"
          href={getServerHref(server.id)}
          aria-label={`View details for ${server.name}`}
          data-tooltip={`View details for ${server.name}`}
          onClick={(event) => {
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
            onOpenServer(server.id);
          }}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path d="M2.5 10s2.7-4.5 7.5-4.5 7.5 4.5 7.5 4.5-2.7 4.5-7.5 4.5S2.5 10 2.5 10Z" />
            <circle cx="10" cy="10" r="2" />
          </svg>
        </a>
      }
    />
  );
}

export default function ServerDirectory({
  serverCount,
  onRefresh,
  getServerHref,
  onOpenServer,
}: ServerDirectoryProps) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(10);
  const [refreshKey, setRefreshKey] = useState(0);
  const [registryPage, setRegistryPage] = useState<ServerRegistryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState("");
  const refreshInProgress = useRef(false);
  const showInitialSkeleton = useMinimumInitialLoading(loading);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    if (!refreshInProgress.current) setRefreshMessage("");
    void listServerRegistryPage(page, pageSize)
      .then((result) => {
        if (!active) return;
        setRegistryPage(result);
        if (result.page !== page) setPage(result.page);
        if (refreshInProgress.current) setRefreshMessage("Server registry refreshed.");
      })
      .catch((reason: unknown) => {
        if (active) {
          const message =
            reason instanceof Error ? reason.message : "Could not load the server registry.";
          setLoadError(message);
          if (refreshInProgress.current) {
            setRefreshMessage(`Could not refresh the server registry: ${message}`);
          }
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          if (refreshInProgress.current) {
            refreshInProgress.current = false;
            setRefreshing(false);
          }
        }
      });

    return () => {
      active = false;
    };
  }, [page, pageSize, refreshKey, serverCount]);

  async function handleRefresh() {
    if (refreshInProgress.current) return;
    refreshInProgress.current = true;
    setRefreshing(true);
    setRefreshMessage("");
    try {
      await onRefresh();
      setRefreshKey((current) => current + 1);
    } catch (reason) {
      const message =
        reason instanceof Error ? reason.message : "Could not refresh the server registry.";
      refreshInProgress.current = false;
      setRefreshing(false);
      setRefreshMessage(`Could not refresh the server registry: ${message}`);
    }
  }

  const total = registryPage?.total ?? 0;
  const currentPage = registryPage?.page ?? page;
  const totalPages = registryPage?.total_pages ?? 0;

  return (
    <section className="panel list-panel" aria-labelledby="list-title">
      <div className="list-heading">
        <div>
          <h2 id="list-title">Server registry</h2>
          <p>Endpoints available to your MCP clients</p>
        </div>
        <button
          className="refresh-button icon-tooltip icon-tooltip--below-right"
          onClick={() => void handleRefresh()}
          type="button"
          disabled={refreshing}
          aria-label={refreshing ? "Refreshing servers" : "Refresh servers"}
          aria-busy={refreshing}
          data-tooltip={
            refreshing ? "Refreshing the server registry" : "Refresh the server registry"
          }
        >
          {refreshing ? (
            <span className="spinner dark-spinner" aria-hidden="true" />
          ) : (
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
              <path d="M16.5 8A6.5 6.5 0 0 0 5 5.7L3.5 7.2" />
              <path d="M3.5 3.5v3.7h3.7" />
              <path d="M3.5 12A6.5 6.5 0 0 0 15 14.3l1.5-1.5" />
              <path d="M16.5 16.5v-3.7h-3.7" />
            </svg>
          )}
        </button>
      </div>
      {refreshMessage && (
        <p className="server-refresh-status" role="status">
          {refreshMessage}
        </p>
      )}

      {showInitialSkeleton ? (
        <ServerListSkeleton />
      ) : loadError ? (
        <div className="empty-state" role="alert">
          <h3>Could not load the server registry</h3>
          <p>{loadError}</p>
          <Button variant="secondary" onClick={() => void handleRefresh()} type="button">
            Retry
          </Button>
        </div>
      ) : !registryPage || registryPage.total === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20" fill="none">
              <rect x="3.25" y="3.25" width="13.5" height="5.25" rx="1.25" />
              <rect x="3.25" y="11.5" width="13.5" height="5.25" rx="1.25" />
              <path d="M6 5.9h.01M6 14.15h.01" />
            </svg>
          </div>
          <h3>Your server registry is empty</h3>
          <p>Create a server to publish an endpoint for your MCP clients.</p>
        </div>
      ) : (
        <>
          <div
            className="resource-card-grid server-list"
            role="region"
            aria-labelledby="list-title"
            aria-busy={loading || refreshing}
            tabIndex={0}
          >
            {registryPage.items.map((server) => (
              <ServerCard
                key={server.id}
                server={server}
                getServerHref={getServerHref}
                onOpenServer={onOpenServer}
              />
            ))}
          </div>
          <PaginationControls
            page={currentPage}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            itemLabel="servers"
            navigationLabel="Server registry pages"
            busy={loading}
            showPageSizeSelector={false}
            onPageChange={setPage}
            onPageSizeChange={(nextSize) => {
              setPageSize(nextSize);
              setPage(1);
            }}
          />
        </>
      )}
    </section>
  );
}
