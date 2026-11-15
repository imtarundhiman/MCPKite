import type { PageSize, PaginatedPage } from "../types/server";

export function isPaginatedPage<T>(
  value: unknown,
  isItem: (item: unknown) => item is T,
): value is PaginatedPage<T> {
  if (typeof value !== "object" || value === null) return false;
  const page = value as Record<string, unknown>;
  return (
    Array.isArray(page.items) &&
    page.items.every(isItem) &&
    typeof page.page === "number" &&
    Number.isInteger(page.page) &&
    page.page >= 1 &&
    (page.page_size === 10 ||
      page.page_size === 12 ||
      page.page_size === 25 ||
      page.page_size === 50) &&
    typeof page.total === "number" &&
    Number.isInteger(page.total) &&
    page.total >= 0 &&
    typeof page.total_pages === "number" &&
    Number.isInteger(page.total_pages) &&
    page.total_pages >= 0
  );
}

export function pageQuery(page: number, pageSize: PageSize): string {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return query.toString();
}
