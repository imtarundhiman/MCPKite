import { useState, type FormEvent } from "react";
import { ApiError, getApiFieldErrors } from "../api/client";
import type { Secret, Server } from "../types/server";
import Button from "./ui/Button";
import {
  FieldError,
  FieldLabel,
  FormErrorSummary,
  RequiredFieldsNote,
  validateReactField,
  validateReactFieldOnBlur,
  type ReactFieldRule,
} from "./ui/FormPrimitives";

export type ServerDraft = {
  name: string;
  description: string;
  authMode: "normal" | "protected";
  secretId: string;
};

export function createEmptyServerDraft(): ServerDraft {
  return { name: "", description: "", authMode: "normal", secretId: "" };
}

type CreateServerFormProps = {
  secrets: Secret[];
  draft: ServerDraft;
  onDraftChange: (draft: ServerDraft) => void;
  onCreate: (draft: ServerDraft) => Promise<Server | null>;
  onOpenSettings: () => void;
  onOpenTools: (serverId: string) => void;
  error: string;
  notice: string;
  persistenceWarning: string;
};

export default function CreateServerForm({
  secrets,
  draft,
  onDraftChange,
  onCreate,
  onOpenSettings,
  onOpenTools,
  error,
  notice,
  persistenceWarning,
}: CreateServerFormProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createdServerId, setCreatedServerId] = useState<string | null>(null);
  const [formError, setFormError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const availableSecrets = secrets.filter((secret) => secret.server_id === null);
  const secretId = availableSecrets.some((secret) => secret.id === draft.secretId)
    ? draft.secretId
    : availableSecrets[0]?.id ?? "";
  const hasSecretForProtection = secretId !== "";
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setFieldErrors({});
    setFieldIssues([]);
    const validationErrors: Record<string, string> = {};
    for (const field of ["name", "description"] as const) {
      const message = validateReactField(draft[field], fieldRules[field]);
      if (message) validationErrors[field] = message;
    }
    if (draft.authMode === "protected") {
      const message = validateReactField(secretId, fieldRules.secret_id);
      if (message) validationErrors.secret_id = message;
    }
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setFormError("Complete the required fields and correct the highlighted values.");
      return;
    }
    setSaving(true);
    try {
      const created = await onCreate({ ...draft, secretId });
      if (created) {
        onDraftChange(createEmptyServerDraft());
        setCreatedServerId(created.id);
      }
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setFormError(reason instanceof Error ? reason.message : "Could not create the server.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className={`panel create-panel${isExpanded ? " is-expanded" : " is-collapsed"}`}
      aria-labelledby="create-server-title"
    >
      <div className="panel-heading create-panel-heading">
        <div className="create-panel-title">
          <div className="icon-tile" aria-hidden="true">
            <svg viewBox="0 0 20 20" fill="none">
              <path d="M10 4.25v11.5M4.25 10h11.5" />
            </svg>
          </div>
          <div>
            <h2 id="create-server-title">Create a server</h2>
            <p>Add a managed endpoint to your workspace.</p>
          </div>
        </div>
        <Button
          variant="secondary"
          className="create-panel-toggle icon-tooltip icon-tooltip--below-right"
          type="button"
          aria-expanded={isExpanded}
          aria-controls="server-create-fields"
          aria-label={`${isExpanded ? "Hide" : "Show"} server creation form`}
          data-tooltip={`${isExpanded ? "Hide" : "Show"} server creation form`}
          onClick={() => setIsExpanded((expanded) => !expanded)}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path d="m5 7.5 5 5 5-5" />
          </svg>
        </Button>
      </div>
      <form
        noValidate
        id="server-create-fields"
        className="create-panel-fields"
        onSubmit={handleSubmit}
        onBlurCapture={(event) =>
          validateReactFieldOnBlur(event, fieldRules, (field, message) =>
            setFieldErrors((current) => ({ ...current, [field]: message })),
          )
        }
        hidden={!isExpanded}
      >
        <RequiredFieldsNote />
        <p className="form-section-label">Server details</p>

        <FieldLabel htmlFor="server-name" required>Server name</FieldLabel>
        <input
          id="server-name"
          name="name"
          autoComplete="off"
          placeholder="e.g. Customer Support"
          aria-invalid={Boolean(fieldErrors.name)}
          aria-describedby={fieldErrors.name ? "server-name-error" : undefined}
          value={draft.name}
          onChange={(event) => {
            setCreatedServerId(null);
            setFieldErrors((current) => ({ ...current, name: "" }));
            setFormError("");
            onDraftChange({ ...draft, name: event.target.value });
          }}
        />
        <FieldError id="server-name-error" message={fieldErrors.name} />

        <FieldLabel htmlFor="server-description">
          Description <span className="optional">Optional</span>
        </FieldLabel>
        <textarea
          id="server-description"
          name="description"
          aria-invalid={Boolean(fieldErrors.description)}
          aria-describedby={
            fieldErrors.description ? "server-description-error" : undefined
          }
          placeholder="What will this server help with?"
          rows={3}
          value={draft.description}
          onChange={(event) => {
            setCreatedServerId(null);
            setFieldErrors((current) => ({ ...current, description: "" }));
            setFormError("");
            onDraftChange({ ...draft, description: event.target.value });
          }}
        />
        <FieldError
          id="server-description-error"
          message={fieldErrors.description}
        />

        <FieldLabel htmlFor="server-auth-mode" required>Connection security</FieldLabel>
        <select
          id="server-auth-mode"
          name="auth_mode"
          value={draft.authMode}
          onChange={(event) => {
            const nextMode = event.target.value === "protected" ? "protected" : "normal";
            setCreatedServerId(null);
            setFormError("");
            setFieldErrors((current) => ({ ...current, secret_id: "" }));
            onDraftChange({ ...draft, authMode: nextMode });
          }}
        >
          <option value="normal">Normal — no token required</option>
          <option value="protected">Protected — bearer token required</option>
        </select>

        {draft.authMode === "protected" && (
          <div className="secret-select-field">
            <FieldLabel htmlFor="server-secret" required>Server access token</FieldLabel>
            {availableSecrets.length > 0 ? (
              <select
                id="server-secret"
                name="secret_id"
                aria-invalid={Boolean(fieldErrors.secret_id)}
                aria-describedby={fieldErrors.secret_id ? "server-secret-error" : undefined}
                value={secretId}
                onChange={(event) => {
                  setCreatedServerId(null);
                  setFieldErrors((current) => ({ ...current, secret_id: "" }));
                  setFormError("");
                  onDraftChange({ ...draft, secretId: event.target.value });
                }}
              >
                {availableSecrets.map((secret) => (
                  <option key={secret.id} value={secret.id}>{secret.name}</option>
                ))}
              </select>
            ) : (
              <div className="helper-callout">
                <span>No unassigned server tokens are available.</span>
                <Button variant="text" onClick={onOpenSettings} type="button">
                  Create a server token
                </Button>
              </div>
            )}
            <FieldError id="server-secret-error" message={fieldErrors.secret_id} />
          </div>
        )}

        <FormErrorSummary
          message={formError || error}
          fieldIssues={fieldIssues}
        />
        {notice && <div className="message success-message" role="status">{notice}</div>}
        {persistenceWarning && (
          <div className="message draft-persistence-warning" role="status">
            {persistenceWarning}
          </div>
        )}

        <Button
          variant="primary"
          disabled={saving || !draft.name.trim() || (draft.authMode === "protected" && !hasSecretForProtection)}
          type="submit"
        >
          {saving ? <><span className="spinner" /> Creating…</> : "Create server"}
        </Button>
        {createdServerId && (
          <Button
            variant="secondary"
            className="create-server-next-action"
            onClick={() => onOpenTools(createdServerId)}
            type="button"
          >
            Add tools or prompts
          </Button>
        )}
        <p className="form-note">Server definitions are saved to the workspace database.</p>
      </form>
    </section>
  );
}
