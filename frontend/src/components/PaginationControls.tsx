import { useId } from "react";

import type { PageSize } from "../types/server";

type PageControl = number | "ellipsis";

type PaginationControlsProps = {
  page: number;
  pageSize: PageSize;
  total: number;
  totalPages: number;
  itemLabel: string;
  navigationLabel: string;
  busy?: boolean;
  compact?: boolean;
  showPageSizeSelector?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: PageSize) => void;
};

function pageControls(currentPage: number, totalPages: number): PageControl[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (currentPage <= 3) return [1, 2, 3, 4, "ellipsis", totalPages];
  if (currentPage >= totalPages - 2) {
    return [1, "ellipsis", totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  }
  return [1, "ellipsis", currentPage - 1, currentPage, currentPage + 1, "ellipsis", totalPages];
}

export default function PaginationControls({
  page,
  pageSize,
  total,
  totalPages,
  itemLabel,
  navigationLabel,
  busy = false,
  compact = false,
  showPageSizeSelector = true,
  onPageChange,
  onPageSizeChange,
}: PaginationControlsProps) {
  const controlId = useId();
  const firstItem = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastItem = Math.min(page * pageSize, total);
  if (compact && total <= 10) return null;

  const pageSizeSelector = (
    <label className={`server-page-size${compact ? " server-page-size-compact" : ""}`} htmlFor={controlId}>
      {compact ? "Rows" : "Rows per page"}
      <select
        id={controlId}
        aria-label={compact ? "Rows per page" : undefined}
        value={pageSize}
        onChange={(event) => {
          const value = event.currentTarget.value;
          if (value === "10" || value === "25" || value === "50") {
            onPageSizeChange(value === "10" ? 10 : value === "25" ? 25 : 50);
          }
        }}
      >
        <option value={10}>10</option>
        <option value={25}>25</option>
        <option value={50}>50</option>
      </select>
    </label>
  );

  return (
    <footer className={`server-pagination${compact ? " server-pagination-compact" : ""}`}>
      {compact ? (
        <>
          <div className="server-pagination-compact-top">
            <p className="server-pagination-summary" aria-live="polite">
              Showing {firstItem}–{lastItem} of {total} {itemLabel}
            </p>
            {showPageSizeSelector && pageSizeSelector}
          </div>
          {totalPages > 1 && (
            <nav className="server-pagination-controls" aria-label={navigationLabel}>
              <button
                className="pagination-button icon-tooltip"
                type="button"
                disabled={busy || page <= 1}
                onClick={() => onPageChange(page - 1)}
                aria-label="Previous page"
                data-tooltip="Previous page"
              >
                <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
                  <path d="m12 4-6 6 6 6" />
                </svg>
              </button>
              <span className="pagination-page-status">
                <span>Page</span>
                <strong>{page}</strong>
                <span>of</span>
                <strong>{totalPages}</strong>
              </span>
              <button
                className="pagination-button icon-tooltip"
                type="button"
                disabled={busy || page >= totalPages}
                onClick={() => onPageChange(page + 1)}
                aria-label="Next page"
                data-tooltip="Next page"
              >
                <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
                  <path d="m8 4 6 6-6 6" />
                </svg>
              </button>
            </nav>
          )}
        </>
      ) : (
        <>
          <p className="server-pagination-summary" aria-live="polite">
            Showing {firstItem}–{lastItem} of {total} {itemLabel}
          </p>
          <div className="server-pagination-tools">
            {showPageSizeSelector && pageSizeSelector}
            <nav className="server-pagination-controls" aria-label={navigationLabel}>
              <button
                className="pagination-button"
                type="button"
                disabled={busy || page <= 1}
                onClick={() => onPageChange(page - 1)}
                aria-label="Previous page"
              >
                Previous
              </button>
              {pageControls(page, totalPages).map((control, index) =>
                control === "ellipsis" ? (
                  <span className="pagination-ellipsis" key={`ellipsis-${index}`} aria-hidden="true">
                    …
                  </span>
                ) : (
                  <button
                    className={`pagination-button pagination-page-button${control === page ? " active" : ""}`}
                    key={control}
                    type="button"
                    aria-label={`Go to page ${control}`}
                    aria-current={control === page ? "page" : undefined}
                    disabled={busy}
                    onClick={() => onPageChange(control)}
                  >
                    {control}
                  </button>
                ),
              )}
              <button
                className="pagination-button"
                type="button"
                disabled={busy || page >= totalPages}
                onClick={() => onPageChange(page + 1)}
                aria-label="Next page"
              >
                Next
              </button>
            </nav>
          </div>
        </>
      )}
    </footer>
  );
}
