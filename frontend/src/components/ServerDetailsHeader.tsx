import { useState, type FormEvent } from "react";

import { ApiError, getApiFieldErrors } from "../api/client";
import { getServerDeletionSummary } from "../api/servers";
import type {
  Secret,
  Server,
  ServerDeletionSummary,
  ServerUpdateInput,
} from "../types/server";
import Button from "./ui/Button";
import { ResourceModal } from "./ui/ResourceManagement";
import {
  FieldError,
  FieldLabel,
  FormErrorSummary,
  RequiredFieldsNote,
  validateReactField,
  validateReactFieldOnBlur,
  type ReactFieldRule,
} from "./ui/FormPrimitives";

export type ServerDetailsHeaderProps = {
  server: Server;
  secrets: Secret[];
  onUpdateServer: (
    serverId: string,
    input: ServerUpdateInput,
  ) => Promise<Server>;
  onDeleteServer: (serverId: string) => Promise<void>;
};

export default function ServerDetailsHeader({
  server,
  secrets,
  onUpdateServer,
  onDeleteServer,
}: ServerDetailsHeaderProps) {
  const [name, setName] = useState(server.name);
  const [description, setDescription] = useState(server.description);
  const [authMode, setAuthMode] = useState<ServerUpdateInput["auth_mode"]>(
    server.auth_mode,
  );
  const [secretId, setSecretId] = useState(server.secret_id ?? "");
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [notice, setNotice] = useState("");
  const [isDeleteConfirmationOpen, setIsDeleteConfirmationOpen] = useState(false);
  const [isDeleteSummaryLoading, setIsDeleteSummaryLoading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteSummary, setDeleteSummary] = useState<ServerDeletionSummary | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const availableSecrets = secrets.filter(
    (secret) => secret.server_id === null || secret.id === server.secret_id,
  );
  const fieldRules: Record<string, ReactFieldRule> = {
    name: {
      required: "Enter a server name.",
      maxLength: { value: 80, message: "Server names can be at most 80 characters." },
    },
    description: {
      maxLength: { value: 300, message: "Descriptions can be at most 300 characters." },
    },
    secret_id: { required: "Choose an available server token." },
  };
  const hasChanges =
    name.trim() !== server.name ||
    description.trim() !== server.description ||
    authMode !== server.auth_mode ||
    (authMode === "protected" && secretId !== (server.secret_id ?? ""));
  const canSave =
    hasChanges &&
    name.trim().length > 0 &&
    !busy &&
    (authMode !== "protected" ||
      availableSecrets.some((secret) => secret.id === secretId));

  function openEditor() {
    setName(server.name);
    setDescription(server.description);
    setAuthMode(server.auth_mode);
    setSecretId(server.secret_id ?? "");
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function closeEditor() {
    if (!busy) setIsEditorOpen(false);
  }

  async function loadDeleteSummary() {
    setDeleteSummary(null);
    setDeleteError("");
    setIsDeleteSummaryLoading(true);
    try {
      setDeleteSummary(await getServerDeletionSummary(server.id));
    } catch (reason) {
      setDeleteError(
        reason instanceof Error
          ? reason.message
          : "Could not check the server's attached content.",
      );
    } finally {
      setIsDeleteSummaryLoading(false);
    }
  }

  function openDeleteConfirmation() {
    setIsDeleteConfirmationOpen(true);
    void loadDeleteSummary();
  }

  function closeDeleteConfirmation() {
    if (!isDeleting) setIsDeleteConfirmationOpen(false);
  }

  async function confirmDelete() {
    if (!deleteSummary || isDeleteSummaryLoading || isDeleting) return;
    setIsDeleting(true);
    setDeleteError("");
    try {
      await onDeleteServer(server.id);
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason.message : "Could not delete the server.",
      );
      setIsDeleting(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    const validationErrors: Record<string, string> = {};
    for (const [field, value] of Object.entries({ name, description })) {
      const message = validateReactField(value, fieldRules[field]);
      if (message) validationErrors[field] = message;
    }
    if (authMode === "protected") {
      const message = validateReactField(secretId, fieldRules.secret_id);
      if (
        message ||
        !availableSecrets.some((secret) => secret.id === secretId)
      ) {
        validationErrors.secret_id = message || "Choose an available server token.";
      }
    }
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setError("Complete the required fields and correct the highlighted values.");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      await onUpdateServer(server.id, {
        name: name.trim(),
        description: description.trim(),
        auth_mode: authMode,
        secret_id: authMode === "protected" ? secretId : null,
      });
      setIsEditorOpen(false);
      setNotice("Server details updated.");
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setError(
        reason instanceof Error ? reason.message : "Could not update the server.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="panel server-details-header"
      aria-labelledby={`server-details-title-${server.id}`}
    >
      <div className="server-details-heading">
        <div className="server-details-identity">
          <p className="page-kicker">MCP server overview</p>
          <div className="server-details-title-row">
            <h1 id={`server-details-title-${server.id}`}>{server.name}</h1>
            <span
              className={`server-access-pill${server.auth_mode === "protected" ? " protected" : ""}`}
            >
              {server.auth_mode === "protected" ? "Protected access" : "Standard access"}
            </span>
          </div>
          {server.description.trim() && (
            <p className="server-details-description">{server.description}</p>
          )}
        </div>
        <div className="server-details-access">
          <Button
            variant="danger"
            className="server-edit-trigger icon-tooltip icon-tooltip--above-left"
            type="button"
            onClick={openDeleteConfirmation}
            aria-label={`Delete ${server.name}`}
            data-tooltip={`Delete ${server.name}`}
            disabled={isDeleting}
          >
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
              <path d="M3.5 5.5h13M8 5.5V3.7h4v1.8m-6.5 0 .7 10.1c.1.8.7 1.4 1.5 1.4h4.6c.8 0 1.4-.6 1.5-1.4l.7-10.1" />
              <path d="M8.2 8.5v5M11.8 8.5v5" />
            </svg>
          </Button>
          <Button
            variant="secondary"
            className="server-edit-trigger icon-tooltip icon-tooltip--above-right"
            type="button"
            onClick={openEditor}
            aria-label={`Edit ${server.name}`}
            data-tooltip={`Edit ${server.name}`}
          >
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
              <path d="m12.2 4.3 3.5 3.5M4 16l3.5-.8L16 6.7a1.8 1.8 0 0 0-2.6-2.6L4.9 12.5 4 16Z" />
            </svg>
          </Button>
        </div>
      </div>

      <div className="server-details-summary server-details-meta">
        <span className="protocol-tag">Streamable HTTP</span>
        <span>
          Created{" "}
          <time dateTime={server.created_at}>
            {new Date(server.created_at).toLocaleDateString()}
          </time>
        </span>
      </div>
      {notice && (
        <p className="server-details-feedback" role="status">
          {notice}
        </p>
      )}

      <ResourceModal
        open={isDeleteConfirmationOpen}
        title={`Delete ${server.name}?`}
        description="Review the attached content before permanently deleting this MCP server."
        closeLabel="Close confirmation"
        onClose={closeDeleteConfirmation}
      >
        <div
          className="server-delete-confirmation"
          aria-busy={isDeleteSummaryLoading || isDeleting}
        >
          {isDeleteSummaryLoading ? (
            <p className="server-delete-status" role="status">
              Checking tools, prompts, and resources…
            </p>
          ) : deleteError && !deleteSummary ? (
            <div className="message error-message server-delete-error" role="alert">
              <p>{deleteError}</p>
              <Button variant="secondary" onClick={() => void loadDeleteSummary()} type="button">
                Retry
              </Button>
            </div>
          ) : deleteSummary ? (
            <>
              {deleteSummary.tool_count +
                deleteSummary.prompt_count +
                deleteSummary.resource_count >
              0 ? (
                <>
                  <div className="message error-message server-delete-warning" role="note">
                    This permanently deletes the server and its saved tools, prompts,
                    resources, and uploaded resource files.
                  </div>
                  <ul className="server-delete-counts" aria-label="Attached content">
                    <li>
                      <span>Tools</span>
                      <strong>{deleteSummary.tool_count}</strong>
                    </li>
                    <li>
                      <span>Prompts</span>
                      <strong>{deleteSummary.prompt_count}</strong>
                    </li>
                    <li>
                      <span>Resources</span>
                      <strong>{deleteSummary.resource_count}</strong>
                    </li>
                    {deleteSummary.file_resource_count > 0 && (
                      <li>
                        <span>Uploaded files to remove</span>
                        <strong>{deleteSummary.file_resource_count}</strong>
                      </li>
                    )}
                  </ul>
                </>
              ) : (
                <p className="server-delete-status">
                  This server has no saved tools, prompts, or resources. Its endpoint will
                  still be permanently removed.
                </p>
              )}
              <p className="server-delete-token-note">
                Its assigned server token will remain in Settings as an unassigned token.
                Workspace variables and secrets will not be changed.
              </p>
            </>
          ) : null}
          {deleteError && deleteSummary && (
            <p className="message error-message server-delete-error" role="alert">
              {deleteError}
            </p>
          )}
          {isDeleting && (
            <p className="server-delete-status" role="status">
              Deleting server…
            </p>
          )}
          <div className="resource-modal-actions">
            <Button
              variant="text"
              onClick={closeDeleteConfirmation}
              type="button"
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <div className="resource-modal-action-group">
              <Button
                variant="danger"
                onClick={() => void confirmDelete()}
                type="button"
                disabled={!deleteSummary || isDeleteSummaryLoading || isDeleting}
              >
                {isDeleting ? "Deleting…" : "Delete server permanently"}
              </Button>
            </div>
          </div>
        </div>
      </ResourceModal>

      <ResourceModal
        open={isEditorOpen}
        title="Edit MCP server"
        description="Update server details and how clients connect."
        onClose={closeEditor}
      >
        <form
          noValidate
          className="server-edit-form"
          onSubmit={(event) => void handleSubmit(event)}
          onBlurCapture={(event) =>
            validateReactFieldOnBlur(event, fieldRules, (field, message) =>
              setFieldErrors((current) => ({ ...current, [field]: message })),
            )
          }
        >
          <RequiredFieldsNote />
          <div className={`server-edit-grid${authMode === "protected" ? " is-protected" : ""}`}>
            <div className="server-edit-field full-width">
              <FieldLabel htmlFor={`server-name-${server.id}`} required>
                Server name
              </FieldLabel>
              <input
                id={`server-name-${server.id}`}
                name="name"
                autoComplete="off"
                disabled={busy}
                aria-invalid={Boolean(fieldErrors.name)}
                aria-describedby={fieldErrors.name ? `server-name-error-${server.id}` : undefined}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setFieldErrors((current) => ({ ...current, name: "" }));
                  setError("");
                }}
              />
              <FieldError
                id={`server-name-error-${server.id}`}
                message={fieldErrors.name}
              />
            </div>
            <div className="server-edit-field full-width">
              <FieldLabel htmlFor={`server-description-${server.id}`}>
                Description <span className="optional">Optional</span>
              </FieldLabel>
              <textarea
                id={`server-description-${server.id}`}
                name="description"
                disabled={busy}
                rows={3}
                value={description}
                aria-invalid={Boolean(fieldErrors.description)}
                aria-describedby={
                  fieldErrors.description
                    ? `server-description-error-${server.id}`
                    : undefined
                }
                onChange={(event) => {
                  setDescription(event.target.value);
                  setError("");
                }}
              />
              <FieldError
                id={`server-description-error-${server.id}`}
                message={fieldErrors.description}
              />
            </div>
            <div className="server-edit-field server-edit-access-field">
              <FieldLabel htmlFor={`server-auth-mode-${server.id}`} required>
                Access mode
              </FieldLabel>
              <select
                id={`server-auth-mode-${server.id}`}
                name="auth_mode"
                disabled={busy}
                value={authMode}
                onChange={(event) => {
                  const nextMode =
                    event.target.value === "protected" ? "protected" : "normal";
                  setAuthMode(nextMode);
                  setError("");
                  setFieldErrors((current) => ({ ...current, secret_id: "" }));
                  if (
                    nextMode === "protected" &&
                    !availableSecrets.some((secret) => secret.id === secretId)
                  ) {
                    setSecretId(availableSecrets[0]?.id ?? "");
                  }
                }}
              >
                <option value="normal">Standard</option>
                <option value="protected">Protected</option>
              </select>
            </div>
            {authMode === "protected" && (
              <div className="server-edit-field">
                <FieldLabel htmlFor={`server-secret-${server.id}`} required>
                  Server access token
                </FieldLabel>
                {availableSecrets.length > 0 ? (
                  <select
                    id={`server-secret-${server.id}`}
                    name="secret_id"
                    disabled={busy}
                    aria-invalid={Boolean(fieldErrors.secret_id)}
                    aria-describedby={
                      fieldErrors.secret_id
                        ? `server-secret-error-${server.id}`
                        : undefined
                    }
                    value={secretId}
                    onChange={(event) => {
                      setSecretId(event.target.value);
                      setFieldErrors((current) => ({ ...current, secret_id: "" }));
                      setError("");
                    }}
                  >
                    {availableSecrets.map((secret) => (
                      <option key={secret.id} value={secret.id}>
                        {secret.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <p className="server-edit-helper">
                    Create an unassigned server token in Settings first.
                  </p>
                )}
                <FieldError
                  id={`server-secret-error-${server.id}`}
                  message={fieldErrors.secret_id}
                />
              </div>
            )}
          </div>

          <FormErrorSummary message={error} fieldIssues={fieldIssues} />
          <div className="resource-modal-actions server-edit-actions">
            <div className="resource-modal-action-group">
              <Button
                variant="text"
                type="button"
                disabled={busy}
                onClick={closeEditor}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                type="submit"
                disabled={!canSave}
              >
                {busy ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </div>
        </form>
      </ResourceModal>
    </section>
  );
}
