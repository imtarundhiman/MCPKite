import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MutableRefObject,
} from "react";

import { createTool, deleteTool, listToolPage, updateTool } from "../api/tools";
import { ApiError, getApiFieldErrors } from "../api/client";
import type { PythonCodeEditorHandle } from "./PythonCodeEditor";
import ServerConnectionGuide from "./ServerConnectionGuide";
import PromptStudio from "./PromptStudio";
import ResourceStudio from "./ResourceStudio";
import PaginationControls from "./PaginationControls";
import useMinimumInitialLoading from "../hooks/useMinimumInitialLoading";
import Button from "./ui/Button";
import {
  ResourceCard,
  ResourceCardGrid,
  ResourceModal,
} from "./ui/ResourceManagement";
import { ResourceCardSkeletonGrid } from "./ui/LoadingSkeletons";
import WorkspaceTabs from "./ui/WorkspaceTabs";
import ServerDetailsHeader from "./ServerDetailsHeader";
import WorkspaceValueGuide from "./WorkspaceValueGuide";
import {
  FieldError,
  FieldLabel,
  FormErrorSummary,
  RequiredFieldsNote,
} from "./ui/FormPrimitives";
import type {
  PageSize,
  Secret,
  Server,
  ServerUpdateInput,
  ToolDefinition,
  ToolDefinitionPage,
} from "../types/server";

const PythonCodeEditor = lazy(() => import("./PythonCodeEditor"));

type ToolCodeFieldProps = {
  id: string;
  source: string;
  onSourceChange: (source: string) => void;
  onSourceBlur?: () => void;
  error?: string;
  editorViewRef?: MutableRefObject<PythonCodeEditorHandle | null>;
};

function ToolCodeField({
  id,
  source,
  onSourceChange,
  onSourceBlur,
  error,
  editorViewRef,
}: ToolCodeFieldProps) {
  const labelId = `${id}-label`;
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;

  return (
    <div className="tool-code-field">
      <div className="tool-code-toolbar">
        <FieldLabel
          htmlFor={id}
          required
          onClick={() => editorViewRef?.current?.focus()}
        >
          Python function
        </FieldLabel>
      </div>
      <Suspense
        fallback={
          <div className="code-editor code-editor-loading" role="status">
            Loading Python editor…
          </div>
        }
      >
        <PythonCodeEditor
          ref={editorViewRef}
          id={id}
          labelId={labelId}
          helpId={helpId}
          errorId={error ? errorId : undefined}
          isInvalid={Boolean(error)}
          source={source}
          onSourceChange={onSourceChange}
          onBlur={onSourceBlur}
        />
      </Suspense>
      <p className="form-note tool-source-help" id={helpId}>
        One top-level function; annotate every parameter and include a docstring. The
        deployment operator configures the source-size limit. Workspace values are available
        through <code>os.environ["NAME"]</code>; never return secret values from a tool.
      </p>
      <WorkspaceValueGuide context="tool" />
      <FieldError id={errorId} message={error} />
    </div>
  );
}

function ToolEditor({ server }: { server: Server }) {
  const [toolPage, setToolPage] = useState<ToolDefinitionPage | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(12);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedTool, setSelectedTool] = useState<ToolDefinition | null>(null);
  const [source, setSource] = useState("");
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [listError, setListError] = useState("");
  const [notice, setNotice] = useState("");
  const editorViewRef = useRef<PythonCodeEditorHandle | null>(null);
  const tools = toolPage?.items ?? [];
  const total = toolPage?.total ?? 0;
  const totalPages = toolPage?.total_pages ?? 0;
  const showInitialSkeleton = useMinimumInitialLoading(loading);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setListError("");
    listToolPage(server.id, page, pageSize)
      .then((result) => {
        if (!active) return;
        setToolPage(result);
        if (result.page !== page) setPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setListError(reason instanceof Error ? reason.message : "Could not load tools.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [server.id, page, pageSize, refreshKey]);

  function chooseTool(tool: ToolDefinition) {
    setSelectedTool(tool);
    setSource(tool.source);
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function startNewTool() {
    setSelectedTool(null);
    setSource("");
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function handleSourceChange(nextSource: string) {
    setSource(nextSource);
    setFieldErrors((current) => ({ ...current, source: "" }));
    setError("");
  }

  function handleSourceBlur() {
    if (!source.trim()) {
      const message = "Enter a Python function before saving.";
      setFieldErrors({ source: message });
      setError(message);
    }
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFieldErrors({});
    setFieldIssues([]);
    if (!source.trim()) {
      setFieldErrors({ source: "Enter a Python function before saving." });
      setError("Enter a Python function before saving.");
      editorViewRef.current?.focus();
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = selectedTool
        ? await updateTool(server.id, selectedTool.id, source)
        : await createTool(server.id, source);
      setSelectedTool(saved);
      if (selectedTool) {
        setToolPage((current) =>
          current
            ? {
                ...current,
                items: current.items.map((tool) => (tool.id === saved.id ? saved : tool)),
              }
            : current,
        );
      } else {
        setPage(Math.max(1, Math.ceil((total + 1) / pageSize)));
        setRefreshKey((current) => current + 1);
      }
      setNotice(
        saved.execution_status === "active"
          ? "Tool saved and published to MCP clients."
          : "Tool definition saved as a draft.",
      );
      setIsEditorOpen(false);
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setError(reason instanceof Error ? reason.message : "Could not save tool definition.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selectedTool) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await deleteTool(server.id, selectedTool.id);
      const nextTotal = Math.max(total - 1, 0);
      setPage(Math.min(page, Math.max(1, Math.ceil(nextTotal / pageSize))));
      setRefreshKey((current) => current + 1);
      setSelectedTool(null);
      setSource("");
      setIsEditorOpen(false);
      setNotice("Tool deleted.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the tool draft.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="tool-studio panel capability-content-panel">
      <header className="page-heading tool-page-heading">
        <div className="page-title-group">
          <h2 className="sr-only">Tools</h2>
          <p className="subtitle">Define an annotated Python function for this MCP server.</p>
        </div>
        <Button variant="secondary" onClick={startNewTool} type="button">
          New tool
        </Button>
      </header>

      {notice && <div className="message success-message resource-page-notice" role="status">{notice}</div>}
      {tools.some((tool) => tool.execution_status === "disabled") && (
        <div className="message tool-runtime-notice" role="note">
          <strong>Sandbox execution is not configured.</strong> These definitions are saved as
          drafts and are not published to MCP clients.
        </div>
      )}
      {toolPage && total === 0 && (
        <div className="message tool-runtime-notice" role="note">
          <strong>Tool publishing requires the isolated runner.</strong> If the runner is unavailable
          in this deployment, a saved tool remains a draft and is not published to MCP clients.
        </div>
      )}

      {showInitialSkeleton ? (
        <ResourceCardSkeletonGrid label="tools" />
      ) : listError ? (
        <div className="resource-list-error" role="alert">
          <p>{listError}</p>
          <Button
            variant="secondary"
            onClick={() => setRefreshKey((current) => current + 1)}
            type="button"
          >
            Retry
          </Button>
        </div>
      ) : !toolPage || total === 0 ? (
        <div className="resource-empty-state">
          <h2>No tools yet</h2>
          <p>Create a Python function to make a tool available to your MCP clients.</p>
          <Button variant="secondary" onClick={startNewTool} type="button">
            Create your first tool
          </Button>
        </div>
      ) : (
        <>
          <ResourceCardGrid label="Saved tools" busy={loading}>
            {tools.map((tool) => (
              <ResourceCard
                key={tool.id}
                name={tool.name}
                description={tool.description}
                status={tool.execution_status === "active" ? "Published" : "Draft"}
                statusTone={tool.execution_status === "active" ? "published" : "draft"}
                metadata="Python function"
                editLabel={tool.name}
                onEdit={() => chooseTool(tool)}
              />
            ))}
          </ResourceCardGrid>
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            itemLabel="tools"
            navigationLabel="Tool pages"
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

      <ResourceModal
        open={isEditorOpen}
        title={selectedTool ? `Edit ${selectedTool.name}` : "Create a tool"}
        description="Use a single function with typed parameters and a descriptive docstring."
        onClose={() => setIsEditorOpen(false)}
      >
        <form
          id="tool-editor-form"
          noValidate
          onSubmit={(event) => void handleSave(event)}
        >
          <RequiredFieldsNote />
          <ToolCodeField
            id="tool-source"
            source={source}
            error={fieldErrors.source}
            onSourceChange={handleSourceChange}
            onSourceBlur={handleSourceBlur}
            editorViewRef={editorViewRef}
          />
          <FormErrorSummary
            message={error}
            fieldIssues={fieldIssues}
            formId="tool-editor-form"
            fieldIdMap={{ source: "tool-source" }}
          />
          {selectedTool && (
            <div className="tool-schema">
              <div className="tool-schema-heading">
                <h3>Input schema preview</h3>
                <span className="draft-badge">
                  {selectedTool.execution_status === "active" ? "Published" : "Draft"}
                </span>
              </div>
              <pre>{JSON.stringify(selectedTool.input_schema, null, 2)}</pre>
            </div>
          )}
          <div className="resource-modal-actions">
            {selectedTool && (
              <Button
                variant="text"
                className="danger-text-button"
                disabled={saving}
                onClick={() => void handleDelete()}
                type="button"
              >
                Delete tool
              </Button>
            )}
            <div className="resource-modal-action-group">
              <Button
                variant="secondary"
                onClick={() => setIsEditorOpen(false)}
                type="button"
              >
                Cancel
              </Button>
              <Button variant="primary" className="tool-save-button" disabled={saving || loading} type="submit">
                {saving ? "Saving…" : selectedTool ? "Save changes" : "Create tool"}
              </Button>
            </div>
          </div>
        </form>
      </ResourceModal>
    </section>
  );
}

type ServerCapability = "tools" | "prompts" | "resources" | "connect";

type ToolStudioProps = {
  server: Server;
  secrets: Secret[];
  onUpdateServer: (
    serverId: string,
    input: ServerUpdateInput,
  ) => Promise<Server>;
  onDeleteServer: (serverId: string) => Promise<void>;
  activeCapability: ServerCapability;
  getCapabilityHref: (capability: ServerCapability) => string;
  onCapabilityChange: (capability: ServerCapability) => void;
};

export default function ToolStudio({
  server,
  secrets,
  onUpdateServer,
  onDeleteServer,
  activeCapability,
  getCapabilityHref,
  onCapabilityChange,
}: ToolStudioProps) {
  const [hasOpenedPrompts, setHasOpenedPrompts] = useState(activeCapability === "prompts");
  const [hasOpenedResources, setHasOpenedResources] = useState(
    activeCapability === "resources",
  );
  const [hasOpenedConnection, setHasOpenedConnection] = useState(activeCapability === "connect");

  useEffect(() => {
    if (activeCapability === "prompts") setHasOpenedPrompts(true);
    if (activeCapability === "resources") setHasOpenedResources(true);
    if (activeCapability === "connect") setHasOpenedConnection(true);
  }, [activeCapability]);

  return (
    <section className="server-workspace">
      <ServerDetailsHeader
        server={server}
        secrets={secrets}
        onUpdateServer={onUpdateServer}
        onDeleteServer={onDeleteServer}
      />
      <WorkspaceTabs
        ariaLabel="Server capabilities"
        activeValue={activeCapability}
        items={[
          { value: "tools", label: "Tools", href: getCapabilityHref("tools") },
          { value: "prompts", label: "Prompts", href: getCapabilityHref("prompts") },
          { value: "resources", label: "Resources", href: getCapabilityHref("resources") },
          { value: "connect", label: "Connect", href: getCapabilityHref("connect") },
        ]}
        onSelect={(capability) => {
          if (capability === "prompts") setHasOpenedPrompts(true);
          if (capability === "resources") setHasOpenedResources(true);
          if (capability === "connect") setHasOpenedConnection(true);
          onCapabilityChange(capability);
        }}
      />
      <div className="server-capability-panel" hidden={activeCapability !== "tools"}>
        <ToolEditor key={server.id} server={server} />
      </div>
      {hasOpenedPrompts && (
        <div className="server-capability-panel" hidden={activeCapability !== "prompts"}>
          <PromptStudio key={server.id} server={server} />
        </div>
      )}
      {hasOpenedResources && (
        <div className="server-capability-panel" hidden={activeCapability !== "resources"}>
          <ResourceStudio key={server.id} server={server} />
        </div>
      )}
      {hasOpenedConnection && (
        <div className="server-capability-panel" hidden={activeCapability !== "connect"}>
          <div className="panel connection-tab-panel">
            <ServerConnectionGuide server={server} />
          </div>
        </div>
      )}
    </section>
  );
}
