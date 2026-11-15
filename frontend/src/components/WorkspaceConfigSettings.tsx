import { useEffect, useState, type FormEvent } from "react";

import {
  deleteWorkspaceConfigValue,
  listWorkspaceConfigValuePage,
  saveWorkspaceConfigValue,
} from "../api/configValues";
import Button from "./ui/Button";
import { FieldError } from "./ui/FormPrimitives";
import PaginationControls from "./PaginationControls";
import type {
  PageSize,
  WorkspaceConfigValue,
  WorkspaceConfigValuePage,
} from "../types/server";

type ValueKind = WorkspaceConfigValue["kind"];

export default function WorkspaceConfigSettings() {
  const [pageData, setPageData] = useState<WorkspaceConfigValuePage | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(10);
  const [refreshKey, setRefreshKey] = useState(0);
  const [kind, setKind] = useState<ValueKind>("variable");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState<WorkspaceConfigValue | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    listWorkspaceConfigValuePage(page, pageSize)
      .then((result) => {
        if (!active) return;
        setPageData(result);
        if (result.page !== page) setPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setLoadError(
            reason instanceof Error ? reason.message : "Could not load workspace values.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, pageSize, refreshKey]);

  function resetForm() {
    setEditing(null);
    setKind("variable");
    setName("");
    setValue("");
    setFieldErrors({});
  }

  function startEditing(item: WorkspaceConfigValue) {
    setEditing(item);
    setKind(item.kind);
    setName(item.name);
    setValue(item.kind === "variable" ? item.value ?? "" : "");
    setError("");
    setNotice("");
    setFieldErrors({});
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextFieldErrors: Record<string, string> = {};
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name.trim())) {
      nextFieldErrors.name = "Use letters, numbers, and underscores; start with a letter or underscore.";
    }
    if (!value.trim()) nextFieldErrors.value = "Enter a value.";
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) {
      setError("Correct the highlighted values.");
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveWorkspaceConfigValue(
        { name, kind, value },
        editing?.id,
      );
      setRefreshKey((current) => current + 1);
      resetForm();
      setNotice(
        kind === "secret"
          ? "Secret saved. Its value is encrypted and will not be shown again."
          : "Variable saved.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the workspace value.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(item: WorkspaceConfigValue) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await deleteWorkspaceConfigValue(item.id);
      setConfirmDeleteId("");
      if (editing?.id === item.id) resetForm();
      setRefreshKey((current) => current + 1);
      setNotice(`${item.name} deleted.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the workspace value.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel settings-panel workspace-config-panel">
      <div className="settings-heading">
        <div>
          <h2>Variables &amp; secrets</h2>
          <p>Reuse workspace values in Python tools, prompts, and text resources.</p>
        </div>
      </div>

      <form
        className="config-value-form"
        noValidate
        onSubmit={(event) => void handleSave(event)}
      >
        <div>
          <label htmlFor="workspace-config-kind">Type</label>
          <select
            id="workspace-config-kind"
            value={kind}
            onChange={(event) => {
              const nextKind = event.target.value;
              if (nextKind === "variable" || nextKind === "secret") setKind(nextKind);
            }}
            disabled={busy}
          >
            <option value="variable">Variable</option>
            <option value="secret">Secret</option>
          </select>
        </div>
        <div>
          <label htmlFor="workspace-config-name">Name</label>
          <input
            id="workspace-config-name"
            autoComplete="off"
            maxLength={128}
            aria-invalid={Boolean(fieldErrors.name)}
            aria-describedby={fieldErrors.name ? "workspace-config-name-error" : undefined}
            placeholder="e.g. OPENAI_BASE_URL"
            required
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setFieldErrors((current) => ({ ...current, name: "" }));
            }}
            disabled={busy}
          />
          <FieldError id="workspace-config-name-error" message={fieldErrors.name} />
        </div>
        <div className="config-value-input">
          <label htmlFor="workspace-config-value">
            {kind === "secret" ? "Secret value" : "Value"}
          </label>
          <input
            id="workspace-config-value"
            autoComplete={kind === "secret" ? "new-password" : "off"}
            maxLength={10_000}
            aria-invalid={Boolean(fieldErrors.value)}
            aria-describedby={fieldErrors.value ? "workspace-config-value-error" : undefined}
            placeholder={kind === "secret" ? "Enter the secret" : "Enter a value"}
            required
            type={kind === "secret" ? "password" : "text"}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setFieldErrors((current) => ({ ...current, value: "" }));
            }}
            disabled={busy}
          />
          <FieldError id="workspace-config-value-error" message={fieldErrors.value} />
        </div>
        <div className="config-value-actions">
          <Button
            variant="primary"
            disabled={busy || !name.trim() || !value.trim()}
            type="submit"
          >
            {busy ? "Saving…" : editing ? "Save changes" : "Save value"}
          </Button>
          {editing && (
            <Button variant="text" disabled={busy} onClick={resetForm} type="button">
              Cancel
            </Button>
          )}
        </div>
      </form>

      <p className="form-note">
        Variables stay visible for editing. Secret values are encrypted and can only be replaced.
      </p>
      {error && <div className="message error-message" role="alert">{error}</div>}
      {notice && <div className="message success-message" role="status">{notice}</div>}
      {loadError && (
        <div className="message error-message workspace-config-load-error" role="alert">
          <p>{loadError}</p>
          <Button
            variant="secondary"
            disabled={loading}
            onClick={() => setRefreshKey((current) => current + 1)}
            type="button"
          >
            Retry
          </Button>
        </div>
      )}

      {loading && pageData === null ? (
        <p>Loading workspace values…</p>
      ) : pageData === null ? null : pageData.total === 0 ? (
        <div className="settings-empty">
          No values yet. Save a variable or secret to reuse it in your MCP definitions.
        </div>
      ) : (
        <ul className="settings-list workspace-config-list">
          {pageData.items.map((item) => (
            <li key={item.id}>
              <div className="settings-item-copy">
                <div className="workspace-config-item-heading">
                  <strong>{item.name}</strong>
                  <span>{item.kind === "secret" ? "Secret · value hidden" : "Variable"}</span>
                </div>
                {item.kind === "variable" && (
                  <code className="workspace-config-value">{item.value}</code>
                )}
              </div>
              <div className="settings-item-actions">
                {confirmDeleteId === item.id ? (
                  <>
                    <Button
                      variant="danger"
                      disabled={busy}
                      onClick={() => void handleDelete(item)}
                      type="button"
                    >
                      Confirm delete
                    </Button>
                    <Button
                      variant="text"
                      disabled={busy}
                      onClick={() => setConfirmDeleteId("")}
                      type="button"
                    >
                      Cancel
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      variant="text"
                      disabled={busy}
                      onClick={() => startEditing(item)}
                      type="button"
                    >
                      {item.kind === "secret" ? "Replace" : "Edit"}
                    </Button>
                    <Button
                      variant="text"
                      disabled={busy}
                      onClick={() => setConfirmDeleteId(item.id)}
                      type="button"
                    >
                      Delete
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {pageData && pageData.total > 0 && (
        <PaginationControls
          page={pageData.page}
          pageSize={pageData.page_size}
          total={pageData.total}
          totalPages={pageData.total_pages}
          itemLabel="values"
          navigationLabel="Workspace value pagination"
          busy={loading || busy}
          onPageChange={setPage}
          onPageSizeChange={(nextPageSize) => {
            setPageSize(nextPageSize);
            setPage(1);
          }}
        />
      )}
    </section>
  );
}
