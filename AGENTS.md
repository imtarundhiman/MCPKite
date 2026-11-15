# Repository Instructions

## Build and test

Run project commands inside Docker Compose containers. Do not execute project
scripts or runtimes such as `python`, `pytest`, `npm`, `npx`, `alembic`, or
`uvicorn` directly on the host. The host may be used for file inspection,
editing, Git operations, and invoking the Docker Compose CLI.

Run Docker Compose commands from the repository root:

```bash
# Backend test suite (tests use temporary SQLite databases)
docker compose run --rm -T --no-deps \
  -v "$PWD/backend/tests:/app/tests:ro" \
  -v "$PWD/backend/requirements-test.txt:/app/requirements-test.txt:ro" \
  backend sh -c 'pip install -r /app/requirements-test.txt && env -u TOOL_RUNNER_URL -u TOOL_RUNNER_TOKEN_FILE PYTHONPATH=/app pytest -q /app/tests'

# One backend test
docker compose run --rm -T --no-deps \
  -v "$PWD/backend/tests:/app/tests:ro" \
  -v "$PWD/backend/requirements-test.txt:/app/requirements-test.txt:ro" \
  backend sh -c 'pip install -r /app/requirements-test.txt && env -u TOOL_RUNNER_URL -u TOOL_RUNNER_TOKEN_FILE PYTHONPATH=/app pytest -q /app/tests/test_servers.py::test_create_and_list_server'

# Frontend TypeScript check and production build
docker compose run --rm -T --no-deps frontend npm run build

# Apply migrations to the Compose database (backend service must be running)
docker compose exec -T backend alembic upgrade head

# Build and run the complete Docker Compose stack; backend startup applies migrations
docker compose up --build
```

The Compose application uses PostgreSQL. Backend tests mount their test files
and test-only requirements into a one-off backend container; the external tool
runner variables are unset so tests exercise the local test configuration.
For backend development, start the Compose services instead of running Uvicorn
or migrations on the host. Add other project scripts to the appropriate
container command; do not install or run project tooling directly on the host.

## Manual MCP tool smoke test

For end-to-end verification of a saved tool, follow the
[MCP Inspector workflow in README.md](README.md#test-a-saved-tool-with-mcp-inspector).
Confirm the tool is listed and invoke it with safe, representative arguments;
a successful connection alone does not verify tool execution. Inspector runs
inside Docker and must use the `backend:8000` endpoint, while host clients use
`localhost:8000`. Protected servers require the server's bearer token, not Studio
login credentials. Never commit or share the authenticated Inspector launch URL,
bearer tokens, or workspace secret values.

## Architecture

- `frontend/` is a React + TypeScript application built with Vite. `src/App.tsx`
  coordinates the left workspace navigation, server list, tool-draft selection,
  load/error/notice state, and create/copy actions. `src/components/ToolStudio.tsx`
  manages Python tool drafts for an individual server: new drafts start blank,
  selecting a saved tool loads its source, and `src/components/PythonCodeEditor.tsx`
  provides the lazy-loaded CodeMirror 6 Python editor. The shared editor offers
  syntax highlighting, line numbers, and indentation in create/edit and
  maximized views. The maximized editor is a full-viewport native dialog that
  shares the same draft state as the inline editor; closing it or pressing
  Escape preserves the draft. The bounded tool-list panel scrolls its rows
  independently of its heading and pagination.
  `PromptStudio` and `ResourceStudio` own their respective capability views.
  Tools, Prompts, and Resources each render inside their own `.panel` below
  `WorkspaceTabs`; keep the navigation outside the content panels. Connect
  retains its separate connection-guide panel.
  `src/api/tools.ts` owns the typed management calls.
  `src/api/servers.ts` owns management API calls and response validation;
  `src/types/server.ts` contains shared types. `CreateServerForm` owns draft
  field controls and its saving state, while `App.tsx` owns and persists the
  controlled server setup draft in tab-scoped `sessionStorage`. Clear it after
  successful creation and sign-out; never persist secret values.
  `ServerDirectory` renders loading, empty, refresh, and server-card states;
  cards link directly to their Tools workspace, and the registry list is an
  accessible keyboard-focusable region. `PageChrome` contains the shared
  header and footer.
  `src/components/ui/` contains the shared `Button` and `WorkspaceTabs`
  modules; `PaginationControls` is shared by server, tool, prompt, and resource
  listings.
  The browser calls `/api/v1/servers`; Vite proxies `/api` and `/mcp` during
  development, while the frontend Nginx container proxies those paths to
  FastAPI in Compose.
- `backend/app/main.py` owns the FastAPI app factory, sandbox configuration,
  runner client, and lifespan;
  `backend/app/api/routes/` defines health, authentication, workspace, secrets,
  and server management endpoints;
  `backend/app/schemas.py` contains request/response models;
  `backend/app/services/workspaces.py` owns workspace-scoped summary counts
  used by the dashboard;
  `backend/app/services/servers.py` coordinates persistence and runtime
  publication; `backend/app/services/tools.py` persists workspace-scoped tool
  drafts and `backend/app/tool_contracts.py` statically validates their source
  and derives input schemas without executing it; `backend/app/services/auth.py`
  owns account/session behavior;
  `backend/app/tool_executor.py` calls the isolated runner, and
  `backend/app/mcp_runtime.py` owns FastMCP app creation, dynamic tool
  registration, lifespan tasks, and per-server bearer-token enforcement.
  `runner/app/main.py` is the trusted Docker controller; it alone has Docker
  socket access and creates one-off execution containers. It stages each
  request in a temporary volume, mounted read-only by the sandbox and removed
  after the call. The sandbox image runs the saved source as a non-root user;
  `runner/app/egress_proxy.py` provides filtered public HTTP/HTTPS egress.
  SQLAlchemy's async engine persists definitions in PostgreSQL; Alembic owns
  the production schema.
- FastMCP app instances and their lifespan tasks are process-local, not stored
  in the database. On startup, the backend loads definitions and recreates
  their mounts; creating a server starts its FastMCP app, persists its
  definition, and then publishes its route and in-memory registry entry.
- Managed MCP endpoints use stateless Streamable HTTP. They are protocol
  endpoints for MCP clients, not browser pages; a browser navigation `GET` is
  not an MCP request. Keep the endpoint URL and trailing slash intact for
  client configuration.
- Browser management APIs authenticate with short-lived JWT access cookies and
  rotating, database-backed refresh sessions. Mutating requests require the
  CSRF cookie/header pair; do not move authentication tokens into browser
  localStorage. Workspace-scoped reads and writes must include the authenticated
  workspace ID in their database queries.
- Secret values are shown only when created and only their hashes are persisted.
  A `ServerSecret.server_id` is unique; preserve the one-secret-per-server
  assignment invariant when changing server security settings. A protected
  server's ASGI bearer guard must be synchronized with its persisted secret
  under the guard lock.
- `AUTH_JWT_SECRET` must be stable across production restarts, and
  `AUTH_COOKIE_SECURE=true` must be used behind HTTPS. See [README.md](README.md)
  for the authentication, invitation, and deployment settings.
- Keep backend settings in `backend/.env` and public Vite settings in
  `frontend/.env`; maintain the matching `.env.example` templates. The backend
  loads its dotenv file for local runs and Compose injects it into the service.
  The frontend Docker build reads `frontend/.env` through Vite. Vite embeds
  `VITE_*` values into the browser bundle, so never put secrets in the frontend
  environment file. Credentialed CORS must use explicit origins.

## Repository-specific conventions

- Keep the backend at one Uvicorn worker. Dynamic FastMCP mounts and lifecycle
  tasks live in that worker's memory; additional workers would not share the
  same runtime endpoints. Supporting multiple workers requires changing the
  runtime/routing architecture, not just the Uvicorn setting.
- In server creation, preserve the no-`await` publication block after the
  database commit: it keeps mount and registry updates atomic relative to
  concurrent requests on the single-worker event loop. If persistence fails,
  stop the already-started FastMCP lifespan task.
- Keep database model changes and Alembic migrations in sync. Use the
  `initialize_schema=True`/`create_all` path only for isolated tests; production
  startup applies Alembic migrations in the backend container.
- MCP transport behavior is configured in `create_fastmcp_app`; protocol
  regression tests should exercise `initialize`, `tools/list`, and `tools/call`
  through the mounted path. Responses may be Server-Sent Events, so tests parse
  the `data:` message rather than assuming a JSON response body.
- Python source is untrusted. Never execute it in FastAPI or the trusted runner
  process. Only the ephemeral sandbox container may execute a tool definition;
  it must have no Docker socket, host mounts, or credentials. The per-call
  internal network must include only the sandbox and its egress proxy; the
  proxy must resolve hostnames, reject every non-public resolved address, and
  connect to the validated IP to prevent DNS rebinding. Run network-boundary
  tests before changing this topology. Sandbox and proxy limits are
  deployment-operator settings, not workspace-user inputs.
- FastMCP tool definitions must preserve the callable signature, annotations,
  and docstring so the MCP client receives the declared JSON schema. Exercise
  `tools/list` and `tools/call` through the mounted Streamable HTTP endpoint,
  including mutation and runner-failure behavior.
- Keep frontend API response shape checks and HTTP error messages in
  the corresponding module under `src/api/`; components should consume typed
  data and report user actions through props rather than duplicating
  fetch/validation logic. Dashboard totals come from the authenticated,
  workspace-scoped `/api/v1/workspace/summary` endpoint; do not reintroduce
  per-server request fan-out.
- Use `src/components/ui/Button.tsx` for standard primary, secondary, text, and
  danger actions. Preserve native button attributes such as `type`, `disabled`,
  and accessibility labels. Keep specialized icon buttons, server toggles, and
  row/action cards purpose-built when their behavior or layout differs.
- Use `src/components/ui/WorkspaceTabs.tsx` for page and capability navigation.
  Keep the shared underline treatment across screens, provide a meaningful
  `ariaLabel`, and supply URL-backed `href` values while preserving each
  caller's SPA route behavior through `onSelect`. These are navigation links,
  not ARIA tabs; preserve standard modified-click/new-tab behavior and current
  page state.
- Reuse `PaginationControls` for paginated listings and the `.panel` class in
  `styles.css` for shared surfaces. Keep capability tabs outside their content
  panels; do not add redundant wrappers or duplicate shared styles. Extract a
  module when repeated structure or behavior provides meaningful reuse; leave
  genuinely one-off layouts purpose-built.
- Keep the Tool editor's native maximized dialog synchronized with the inline
  textarea. Preserve its close/Escape behavior, focus restoration, and save
  feedback; do not discard unsaved code when returning to the form.
- For large workspace listings, expose a dedicated authenticated page endpoint
  with the shared `items`, `page`, `page_size`, `total`, and `total_pages`
  response shape. Keep existing full-list endpoints when other screens rely on
  them, scope every query to the authenticated workspace, use stable ordering,
  and clamp stale page requests after records are removed.
- Keep shared UI responsive and keyboard accessible: retain visible focus,
  active-state indication, touch target sizes, and no horizontal overflow.
- For user-facing forms, reuse `src/components/ui/FormPrimitives.tsx` for
  required/optional labels, inline field errors, required-field notes, and
  focusable error summaries. Validate user input on blur and submit, preserve
  existing backend constraints and optional-field semantics, and map structured
  `ApiError.fieldIssues` to fields without treating client validation as a
  substitute for FastAPI schema and service validation. Managed forms must use
  React-driven validation (`noValidate` plus explicit rules); do not use
  browser constraint-validation attributes or native validity APIs as the
  validation mechanism.
