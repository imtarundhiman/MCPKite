export function mcpEndpointUrl(path: string): string {
  const configuredBase = import.meta.env.VITE_MCP_ENDPOINT_BASE_URL?.trim();
  const base = configuredBase
    ? configuredBase.replace(/\/+$/, "")
    : window.location.origin;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  return `${base}${normalizedPath}`;
}
