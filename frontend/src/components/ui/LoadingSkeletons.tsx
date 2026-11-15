export function ResourceCardSkeletonGrid({ label }: { label: string }) {
  return (
    <div
      className="resource-card-grid resource-skeleton-grid"
      role="status"
      aria-label={`Loading ${label}`}
      aria-busy="true"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <div className="resource-card resource-card-skeleton" key={index} aria-hidden="true">
          <div className="resource-card-heading">
            <span className="loading-skeleton resource-skeleton-name" />
            <span className="loading-skeleton resource-skeleton-status" />
          </div>
          <div className="resource-skeleton-description">
            <span className="loading-skeleton" />
            <span className="loading-skeleton" />
            <span className="loading-skeleton" />
          </div>
          <div className="resource-card-footer">
            <span className="loading-skeleton resource-skeleton-metadata" />
            <span className="loading-skeleton resource-skeleton-edit" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ServerListSkeleton() {
  return (
    <div
      className="resource-card-grid server-list server-skeleton-list"
      role="status"
      aria-label="Loading MCP servers"
      aria-busy="true"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <article className="resource-card server-row server-row-skeleton" key={index} aria-hidden="true">
          <div className="resource-card-heading">
            <div className="resource-card-title-group">
              <span className="loading-skeleton server-skeleton-icon" />
              <span className="loading-skeleton server-skeleton-name" />
            </div>
          </div>
          <div className="resource-skeleton-description">
            <span className="loading-skeleton server-skeleton-description" />
            <span className="loading-skeleton server-skeleton-description secondary" />
          </div>
          <div className="resource-card-footer">
            <span className="loading-skeleton server-skeleton-access" />
            <span className="loading-skeleton server-skeleton-action" />
          </div>
        </article>
      ))}
    </div>
  );
}

export function DashboardMetricSkeletons() {
  return (
    <>
      {Array.from({ length: 5 }, (_, index) => (
        <article
          className="panel dashboard-metric dashboard-metric-skeleton"
          key={index}
          aria-hidden="true"
        >
          <span className="loading-skeleton dashboard-metric-icon" />
          <span className="dashboard-metric-copy">
            <span className="loading-skeleton dashboard-metric-label-skeleton" />
            <span className="loading-skeleton dashboard-metric-value-skeleton" />
            <span className="loading-skeleton dashboard-metric-caption-skeleton" />
          </span>
        </article>
      ))}
    </>
  );
}

export function DashboardRecentServerSkeleton() {
  return (
    <div
      className="dashboard-server-list dashboard-server-list-skeleton"
      role="status"
      aria-label="Loading recent MCP servers"
      aria-busy="true"
    >
      <div className="dashboard-table-header" aria-hidden="true">
        <span>Server</span>
        <span>Access</span>
        <span className="dashboard-created-heading">Created</span>
        <span />
      </div>
      {Array.from({ length: 5 }, (_, index) => (
        <div className="dashboard-server-row dashboard-server-row-skeleton" key={index} aria-hidden="true">
          <span className="loading-skeleton dashboard-server-mark" />
          <span className="dashboard-server-copy">
            <span className="loading-skeleton dashboard-server-name-skeleton" />
            <span className="loading-skeleton dashboard-server-description-skeleton" />
          </span>
          <span className="loading-skeleton dashboard-server-access-skeleton" />
          <span className="dashboard-server-date loading-skeleton dashboard-server-date-skeleton" />
          <span className="loading-skeleton dashboard-row-chevron-skeleton" />
        </div>
      ))}
    </div>
  );
}

export function DashboardQuickActionSkeleton() {
  return (
    <div
      className="dashboard-actions-skeleton"
      role="status"
      aria-label="Loading quick actions"
      aria-busy="true"
    >
      {Array.from({ length: 2 }, (_, index) => (
        <div className="dashboard-action dashboard-action-skeleton" key={index} aria-hidden="true">
          <span className="loading-skeleton dashboard-action-icon-skeleton" />
          <span className="dashboard-action-copy-skeleton">
            <span className="loading-skeleton dashboard-action-title-skeleton" />
            <span className="loading-skeleton dashboard-action-detail-skeleton" />
          </span>
          <span className="loading-skeleton dashboard-action-chevron-skeleton" />
        </div>
      ))}
    </div>
  );
}
