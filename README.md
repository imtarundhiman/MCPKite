# MCPKite

A small React + FastAPI app for creating and listing FastMCP HTTP servers.
Server definitions are stored in PostgreSQL.

## Documentation portal

Browse the [MCPKite documentation](docs/index.html) for getting started,
server and client setup, tools, prompts, resources, workspace settings,
deployment, and troubleshooting.

To publish it with GitHub Pages, open the repository's **Settings → Pages**,
choose **Deploy from a branch**, select the `main` branch and `/docs` folder,
then save. The site is served from the repository's GitHub Pages URL. The
documentation is plain HTML and CSS and can also be opened locally at
`docs/index.html`.

## Run with Docker Compose

Requirements: Docker with the Compose plugin.

Create the service-specific environment files before the first run:

```bash
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
cp -n .env.example .env
```

Edit the local files as needed. `backend/.env` holds backend settings,
`frontend/.env` holds public Vite development settings, and the root `.env`
holds the PostgreSQL password, required pgAdmin login email and password,
public MCP endpoint base URL, and deployment-operator sandbox and
resource-storage settings used by Compose.
The local `.env` files are ignored by Git.
Never put credentials or other secrets in `frontend/.env`; Vite embeds its
values in the browser bundle.
Set `WORKSPACE_SECRET_ENCRYPTION_KEY` in `backend/.env` to a base64-encoded
32-byte key before saving reusable secrets; generate one with
`openssl rand -base64 32`. Keep a secure backup of this key with the database
backup. If it is lost, encrypted workspace secrets cannot be decrypted.

```bash
docker compose up --build
```

The frontend runs in Vite development mode with the source directory mounted into
the container. Changes to frontend code are reflected in the browser immediately
through hot module replacement; keep [http://localhost:8080](http://localhost:8080)
open while editing. Backend Python changes automatically restart the API.
Rebuild the relevant container only after changing its dependencies or Dockerfile:

```bash
docker compose up --build --renew-anon-volumes -d frontend backend
```

The API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs). PostgreSQL data is stored in the `postgres-data` Docker volume, and the backend reconstructs FastMCP endpoints from the database after restart.

MCP Inspector starts with the Compose stack at [http://localhost:6274](http://localhost:6274). For its authenticated launch URL, read the token-bearing URL in `docker compose logs inspector` and open that URL in your browser. The endpoint shown and copied in MCPKite uses `http://localhost:8000` for clients running on your host. In Inspector, add a Streamable HTTP server using `http://backend:8000` followed by the server's `endpoint_path` from MCPKite (for example, `http://backend:8000/mcp/<server-id>/`). Use `backend`, not `localhost`, because Inspector connects from its container. For a protected endpoint, enter `Authorization: Bearer <server-secret>` in that server's Headers settings; this is the MCP bearer secret, not your MCPKite login.

MCPKite also provides a per-server **Connect** tab and a **Connect client**
disclosure in the server registry. Select the client environment there to copy the
appropriate endpoint. Protected servers require the secret value from its one-time
creation screen as a bearer token; MCPKite cannot retrieve that value later.

## Database access with pgAdmin

pgAdmin starts with the default Compose stack at
[http://localhost:5050](http://localhost:5050), bound to the local machine only.
Set `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in the root `.env`
before starting Compose, then use them to sign in.

Register a server in pgAdmin with these connection settings:

| Setting | Value |
| --- | --- |
| Host name/address | `db` |
| Port | `5432` |
| Maintenance database | `mcp_platform` |
| Username | `mcp` |
| Password | The value of `POSTGRES_PASSWORD` in the root `.env` |

Use `db` as the hostname because pgAdmin connects to PostgreSQL over the
Compose network. pgAdmin's settings and registered servers persist in the
`pgadmin-data` Docker volume.

## Test a saved tool with MCP Inspector

Use this workflow to verify that a saved tool is discoverable and returns the
expected result:

1. In MCPKite, open the server's Tools workspace and save the tool.
2. Open MCP Inspector at [http://localhost:6274](http://localhost:6274). Use the
   authenticated launch URL printed by `docker compose logs inspector`; that URL
   contains a token, so keep it private.
3. Add a **Streamable HTTP** server using the endpoint path shown in MCPKite's
   **Connect** tab. Inspector runs inside Docker, so use
   `http://backend:8000/<endpoint-path>` (for example,
   `http://backend:8000/mcp/<server-id>/`). Host-based clients use
   `http://localhost:8000` instead.
4. For a protected server, add an `Authorization` header with value
   `Bearer <server-token>`. Use the one-time token saved when the server was
   created, not your MCPKite login or a workspace secret. Standard-access servers
   do not need this header.
5. Connect in Inspector, open **Tools**, confirm your tool appears, and call it
   with valid, safe arguments matching its input schema. Check that the returned
   content matches the expected result. If the tool needs a workspace variable or
   secret, configure it in **Settings → Variables & secrets** first; never return
   the secret value as test output.
6. If the tool is missing or the call fails, check the endpoint path and access
   header, then inspect `docker compose logs backend` locally for server or
   execution errors. Redact credentials before sharing diagnostic output.

## Workspace dashboard and navigation

The dashboard loads server, tool, active-tool, and prompt totals from the
authenticated, workspace-scoped `GET /api/v1/workspace/summary` endpoint. It
shows loading and unavailable states separately from a real zero count, with a
retry action when totals cannot be retrieved.

Workspace and server-capability navigation is URL-backed, so the current view
can be refreshed, shared, and revisited with browser back/forward. A server
setup draft is retained in the current tab across refreshes and while navigating
to Settings to create a secret. The draft is cleared after successful server
creation or sign-out; secret values are never stored in the draft.

Server registry cards link directly to their Tools workspace. The registry
supports keyboard focus and announces refresh progress and results. The
Inspector endpoint using `http://backend:8000` is for the local Docker Compose
network only; clients running on the host should use the host-facing endpoint
shown by MCPKite.

## Form validation

User-facing forms mark required fields, identify optional values, and validate
with React on blur and submit; they do not rely on browser-native constraint
validation. Inline feedback and an accessible error summary identify invalid
values, and API field errors are mapped to their controls when the server
provides a field location. FastAPI request schemas and service checks remain
authoritative; file uploads also validate the selected MIME type, extension,
and size before upload.

Inspector's host port is bound to loopback only, and its container shares a dedicated network with the backend rather than the database network. It can also connect to externally hosted MCP servers. Inspector's catalog and credentials are intentionally not stored in a persistent volume, so saved servers and entered secrets are discarded when the Inspector container is recreated. Do not expose port 6274 beyond the local machine.

The development database password defaults to `mcp_local_dev`; override it by setting `POSTGRES_PASSWORD` in the environment. Do not use the development default in a production deployment.

## Binary MCP resources

The per-server **Resources** capability supports text at static URIs and URI
templates, plus uploaded binary files at static URIs. Text template variables
use matching `{{document_id}}` placeholders in the content and workspace
values can be referenced as `${NAME}`. Values are substituted as plain text
and no user-authored code is executed. Binary files
are limited to 50 MiB, remain in private object storage, and are read by MCP
clients through `resources/read`; file bytes and object keys are not returned
by the management API. Binary uploads support a curated set of document, text
and structured-data, and image formats. The selected MIME type is checked
against the file extension and reported MIME type; generic
`application/octet-stream` is not accepted as a stored upload type. Existing
files with older MIME types remain readable and keep their type during
metadata-only edits. Text-resource MIME types are not editable in the UI;
new text resources use `text/plain`, and existing text MIME types are preserved.
Supported file extensions are `.txt`, `.md`/`.markdown`, `.csv`, `.json`,
`.xml`, `.pdf`, `.rtf`, `.doc`/`.docx`, `.xls`/`.xlsx`, `.ppt`/`.pptx`, `.png`,
`.jpg`/`.jpeg`, `.gif`, `.webp`, and `.svg`.
Resources also support MCP `audience` and `priority` annotations; `lastModified`
is managed by the server.

Choose one storage provider for the deployment:

| Variable | Purpose |
| --- | --- |
| `RESOURCE_STORAGE_PROVIDER` | `s3` for Amazon S3-compatible storage, or `azure_blob` for Azure Blob Storage. |
| `RESOURCE_S3_BUCKET` | Private S3 bucket name. |
| `RESOURCE_S3_REGION` | AWS region for the bucket. |
| `RESOURCE_S3_ENDPOINT_URL` | Optional S3-compatible endpoint; leave empty for Amazon S3. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Optional paired credentials; when unset, the AWS SDK credential chain is used. |
| `RESOURCE_AZURE_CONNECTION_STRING` | Azure Blob connection string. Required when Azure Blob is selected. |
| `RESOURCE_AZURE_CONTAINER` | Private Azure Blob container name. |
| `AZURITE_INIT_CONNECTION_STRING` | Optional local-only connection string used to create the container in Azurite. |

Compose starts S3Mock and Azurite for local development. S3Mock creates the
configured bucket and persists its objects in a named volume; it implements
the S3 operations used by this app and is not intended for production. Local
defaults in the root `.env.example` use development-only credentials; never
use those credentials in a hosted deployment. To try Azurite, set
`RESOURCE_STORAGE_PROVIDER=azure_blob` in the root `.env`, and set
`RESOURCE_AZURE_CONNECTION_STRING` and `AZURITE_INIT_CONNECTION_STRING` there
to the local Azurite connection string using the Compose endpoint
`http://azurite:10000/devstoreaccount1`. Keep both values in the ignored local
`.env`; do not commit them. The initializer skips Azurite setup when its
connection string is empty, so the default S3 setup needs no Azure credentials.
For Amazon S3, set the provider to `s3`, configure the bucket and region, and
set `RESOURCE_S3_ENDPOINT_URL` to an empty value or remove it so the AWS SDK
uses its normal endpoint. For Azure Blob Storage deployments, provide a
production connection string and container name outside the local Compose
configuration. Keep the bucket/container private and grant the backend only
the object read/write permissions it needs.

## Accounts, workspace, and MCP credentials

The first account created becomes the workspace owner. When upgrading an existing
installation, the first signup adopts the server definitions already in the
database into that workspace. Later accounts need a one-time invitation link,
which the owner can create and revoke from **Settings**. Workspace members share
servers, variables, and secrets; only the owner can invite or remove members.

Create a server token from **Settings → Server tokens** to protect an MCP
endpoint. Its generated bearer token is shown only once; the database stores
only its hash. A token can be assigned to one server at a time. Protected endpoints require
`Authorization: Bearer <token>`; switching a server to normal mode detaches the
token. Assigned tokens must be detached before they can be deleted.

Deleting a server requires confirmation and permanently removes its tools,
prompts, resources, and uploaded resource files. Its assigned server token is
kept as an unassigned token, and workspace variables and secrets are unaffected.
Deleting an individual file resource also removes its stored file.

## Workspace variables and secrets

Use **Settings → Variables & secrets** to save values shared by the current
workspace. The listing is paginated. Ordinary variables are visible in Settings;
secret values are encrypted at rest and are never returned by the management API
after saving.
To change a secret, replace it with a new value. The deployment-managed
`WORKSPACE_SECRET_ENCRYPTION_KEY` is required to save or use secrets.

Reference a saved value in a prompt or text resource with `${NAME}`; existing
prompt arguments and resource URI parameters keep their `{{argument}}` syntax.
The Tools, Prompts, and Resources editors include guidance for using these
references. In Python tools, read a value with `os.environ["NAME"]`. Only the
current workspace's values are sent to the isolated tool sandbox for each call,
and changes apply on subsequent calls without restarting the server.

Treat secret references in prompts and resources carefully: the resolved value
is part of the prompt/resource response and is visible to the MCP client that
requests it. Do not reference secrets in artifacts intended for untrusted
clients. Server tokens are separate one-time bearer credentials for protecting
MCP endpoints; they are not reusable workspace configuration.

## Sandboxed Python tools

Tools saved in the builder are published to MCP clients only when the isolated
runner is healthy. Every invocation creates a short-lived sandbox container.
Tool code does not execute in FastAPI or in the runner process. The sandbox has
a non-root user, a read-only root filesystem, no host mounts or deployment
credentials, dropped Linux capabilities, no-new-privileges, and deployment-configured CPU,
memory, PID, temporary-filesystem, and execution-time limits. It can reach the
public Internet only through a per-call proxy; the proxy permits HTTP on port
80 and HTTPS on port 443, resolves destinations itself, rejects non-public IP
addresses, and connects to the validated IP. The runner stages each request in
a short-lived Docker volume that the sandbox can read but not modify; the
volume is removed after the call. The current workspace's saved values are
available to tool code through `os.environ`. Runtime package installation is not
available.

The runner is intentionally not exposed as a host port. It is authenticated
with a random token stored in a Compose-managed volume and is reachable only
over the internal control network. **The runner has access to the Docker
daemon socket**, which grants substantial control over the Docker host. Run
this stack only on a host and deployment you trust, and do not expose or share
the Docker socket or runner API with untrusted users.

All execution and proxy limits are deployment-operator settings in the root
`.env` file; workspace users cannot change them:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TOOL_SANDBOX_CPU_LIMIT` | `1` | CPU quota per sandbox and proxy container. |
| `TOOL_SANDBOX_MEMORY_MIB` | `256` | Sandbox memory limit in MiB. |
| `TOOL_SANDBOX_PIDS_LIMIT` | `32` | Maximum sandbox processes/threads. |
| `TOOL_SANDBOX_TIMEOUT_SECONDS` | `10` | Maximum time for one tool call. |
| `TOOL_SANDBOX_TMPFS_MIB` | `32` | Size limit for the sandbox temporary filesystem. |
| `TOOL_SANDBOX_MAX_CONCURRENT_RUNS` | `4` | Maximum simultaneous tool calls in the runner. |
| `TOOL_SANDBOX_QUEUE_TIMEOUT_SECONDS` | `2` | Maximum time a call waits for a runner slot. |
| `TOOL_SANDBOX_MAX_SOURCE_BYTES` | `20000` | Maximum UTF-8 bytes in a saved function. |
| `TOOL_SANDBOX_MAX_PARAMETERS` | `64` | Maximum annotated function parameters. |
| `TOOL_SANDBOX_MAX_INPUT_BYTES` | `65536` | Maximum serialized arguments per call. |
| `TOOL_SANDBOX_MAX_OUTPUT_BYTES` | `262144` | Maximum serialized result per call. |
| `TOOL_SANDBOX_PROXY_MAX_CONNECTIONS` | `128` | Maximum simultaneous proxy connections per invocation. |
| `TOOL_SANDBOX_PROXY_IDLE_TIMEOUT_SECONDS` | `15` | Proxy DNS, connection, and idle-read timeout. |
| `TOOL_SANDBOX_PROXY_MAX_TUNNEL_BYTES` | `10485760` | Maximum bytes transferred through a proxy connection. |
| `TOOL_SANDBOX_PROXY_MAX_HEADER_BYTES` | `65536` | Maximum HTTP proxy request-header size. |

Change a value in the root `.env` before starting or recreating the Compose
services. Local backend-only development does not start the runner; tools stay
as unpublished drafts in that mode.

Configure backend settings in `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_JWT_SECRET` | Generated at startup | Persistent signing key, at least 32 bytes. Set this before deployment so restarts do not invalidate sessions. |
| `AUTH_ACCESS_TOKEN_TTL_SECONDS` | `900` | Lifetime of the short-lived access cookie. |
| `AUTH_SESSION_TTL_SECONDS` | `14400` | Maximum sign-in session lifetime and refresh-cookie lifetime. |
| `AUTH_COOKIE_SECURE` | `false` | Set to `true` when the app is served over HTTPS. |
| `CORS_ALLOWED_ORIGINS` | Values in `backend/.env.example` | Comma-separated exact browser origins allowed to call the API with cookies. Do not use `*`. |

Configure public browser settings in `frontend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api/v1` | API URL prefix used by the browser. The default is same-origin through the Vite development proxy or the production reverse proxy. |
| `VITE_DEV_API_PROXY_TARGET` | `http://localhost:8000` | Backend target used by Vite's `/api` and `/mcp` development proxies. Compose sets this to `http://backend:8000`. |
| `VITE_MCP_ENDPOINT_BASE_URL` | `http://localhost:8000` | Public base URL shown and copied for MCP server endpoints. The default suits local development; set it to the externally reachable MCP origin for hosted builds. |

Compose continues to read `POSTGRES_PASSWORD` from the root `.env` (default
`mcp_local_dev`); replace the development default in production. When the UI
and API use different ports, add the UI's exact origin to
`CORS_ALLOWED_ORIGINS`. The frontend sends credentialed requests. Keep the UI
and API on the same site so the existing `SameSite=Lax` authentication cookies
work; cross-site cookie authentication is not supported.

The root `.env` also accepts `VITE_MCP_ENDPOINT_BASE_URL` for the frontend
Compose runtime and Docker build; its local default is `http://localhost:8000`.
Configure this to the public MCP endpoint origin for hosted deployments. If the
setting is omitted from a non-Compose frontend build, the UI origin is used instead.

Use HTTPS, a strong persistent JWT key, and a non-default database password in
production. Set `AUTH_COOKIE_SECURE=true` when serving over HTTPS. Browser
management requests use HttpOnly authentication cookies and CSRF protection.
The default local settings are for development only.

Managed MCP endpoints use stateless Streamable HTTP, so clients do not need to retain an `MCP-Session-Id` between requests. The current generated tools do not keep per-client session state.

To stop the app, run `docker compose down`. To remove saved server definitions as well, run `docker compose down --volumes`.

## Local development without containers

Use Python 3.12 or newer. Start PostgreSQL with `docker compose up -d db`, then start the backend from `backend/`:

```bash
cp -n .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
alembic upgrade head
uvicorn app.main:app --reload
```

In another terminal, start the frontend from `frontend/`:

```bash
cp -n .env.example .env
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite loads
`frontend/.env` and proxies `/api` and `/mcp` to the backend target configured
by `VITE_DEV_API_PROXY_TARGET`.

## Frontend UI patterns

The frontend keeps repeated controls consistent through shared modules:

- `frontend/src/components/ui/Button.tsx` provides primary, secondary, text,
  and danger action styles. Use it for standard actions; keep specialized
  controls such as icon buttons and server toggles purpose-built.
- `frontend/src/components/ui/WorkspaceTabs.tsx` provides the shared underline
  navigation used by Settings and server capabilities. Keep tab labels,
  selected values, and selection behavior in the calling screen.
- `frontend/src/components/PaginationControls.tsx` is shared by the server,
  tool, prompt, and resource listings.
- `frontend/src/styles.css` defines shared design tokens and the `.panel`
  surface style. Add page-specific classes for layout differences rather than
  duplicating the shared surface styles.
- Each Tools, Prompts, and Resources view has its own `.panel` surface below
  the capability navigation. The tabs remain outside those panels; Connect
  keeps its separate connection-guide panel.

Reuse a shared module when the structure and behavior match; leave genuinely
one-off layouts purpose-built.

In the per-server **Tools** builder, **New tool** opens an empty Python code
canvas; selecting a saved tool loads its existing source. Use **Maximize** to
open a full-viewport editor. Closing it or pressing Escape returns to the form
without discarding unsaved code. The embedded Python editor provides syntax
highlighting, line numbers, and indentation for both new and saved tools. The
tool list scrolls independently when it exceeds its available height.

The per-server **Resources** capability publishes text resources at static
URIs or URI templates such as `docs://{document_id}`, and private binary files
at static URIs. It uses the configured S3 or Azure Blob provider for files and
keeps the existing stateless Streamable HTTP transport. Resource subscriptions
and pushed change notifications are not enabled in this release.

## Tests

Tests use a temporary SQLite database. From `backend/`, install the test dependencies and run:

```bash
pip install -r requirements-test.txt
PYTHONPATH=. pytest
```

## Runtime and trust boundaries

FastAPI uses one Uvicorn worker because FastMCP apps are mounted in that process's in-memory route registry. Async database operations allow overlapping API requests and concurrent server creation without a global request lock. Each request saves its own server record, then publishes the mounted app and in-memory registry entry without yielding to another request. Tool drafts execute only in the separate sandbox runner described above; do not move execution into FastAPI or grant sandbox containers Docker access, host mounts, or credentials.

## License

This project is licensed under the [MIT License](./LICENSE).
