import { useEffect, useState, type FormEvent } from "react";

import {
  createPrompt,
  deletePrompt,
  listPromptPage,
  updatePrompt,
} from "../api/prompts";
import { ApiError, getApiFieldErrors } from "../api/client";
import useMinimumInitialLoading from "../hooks/useMinimumInitialLoading";
import PaginationControls from "./PaginationControls";
import WorkspaceValueGuide from "./WorkspaceValueGuide";
import Button from "./ui/Button";
import {
  ResourceCard,
  ResourceCardGrid,
  ResourceModal,
} from "./ui/ResourceManagement";
import { ResourceCardSkeletonGrid } from "./ui/LoadingSkeletons";
import {
  FieldError,
  FieldLabel,
  FormErrorSummary,
  RequiredFieldsNote,
  validateReactField,
  validateReactFieldOnBlur,
  type ReactFieldRule,
} from "./ui/FormPrimitives";
import type {
  PageSize,
  PromptArgumentDefinition,
  PromptDefinition,
  PromptDefinitionPage,
  Server,
} from "../types/server";

type PromptArgumentDraft = PromptArgumentDefinition & { key: string };
type PromptForm = {
  name: string;
  description: string;
  template: string;
  arguments: PromptArgumentDraft[];
};

const emptyPrompt: PromptForm = {
  name: "",
  description: "",
  template: "",
  arguments: [],
};
const PYTHON_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break",
  "class", "continue", "def", "del", "elif", "else", "except", "finally",
  "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
  "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

function argumentDraft(argument: PromptArgumentDefinition): PromptArgumentDraft {
  return { ...argument, key: crypto.randomUUID() };
}

export default function PromptStudio({ server }: { server: Server }) {
  const [promptPage, setPromptPage] = useState<PromptDefinitionPage | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(12);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedPrompt, setSelectedPrompt] = useState<PromptDefinition | null>(null);
  const [form, setForm] = useState<PromptForm>(emptyPrompt);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [listError, setListError] = useState("");
  const [notice, setNotice] = useState("");
  const prompts = promptPage?.items ?? [];
  const total = promptPage?.total ?? 0;
  const totalPages = promptPage?.total_pages ?? 0;
  const showInitialSkeleton = useMinimumInitialLoading(loading);
  const fieldRules: Record<string, ReactFieldRule> = {
    name: {
      required: "Enter a prompt name.",
      maxLength: { value: 64, message: "Prompt names can be at most 64 characters." },
      pattern: {
        value: /^[A-Za-z][A-Za-z0-9_-]*$/,
        message: "Start with a letter; use only letters, numbers, underscores, and hyphens.",
      },
    },
    description: {
      maxLength: { value: 300, message: "Descriptions can be at most 300 characters." },
    },
    template: {
      required: "Enter a prompt template.",
      maxLength: { value: 50_000, message: "Templates can be at most 50,000 characters." },
    },
    ...Object.fromEntries(
      form.arguments.flatMap((_, index) => [
        [
          `arguments.${index}.name`,
          {
            required: "Enter an argument name.",
            maxLength: {
              value: 64,
              message: "Argument names can be at most 64 characters.",
            },
            pattern: {
              value: /^[A-Za-z_][A-Za-z0-9_]*$/,
              message: "Use a valid identifier: letters, numbers, and underscores.",
            },
            validate: (value: string) =>
              PYTHON_KEYWORDS.has(value) ? "Argument names cannot be Python keywords." : "",
          },
        ],
        [
          `arguments.${index}.description`,
          {
            maxLength: {
              value: 300,
              message: "Descriptions can be at most 300 characters.",
            },
          },
        ],
        [
          `arguments.${index}.default_value`,
          {
            maxLength: {
              value: 2_000,
              message: "Default values can be at most 2,000 characters.",
            },
          },
        ],
      ]),
    ),
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setListError("");
    listPromptPage(server.id, page, pageSize)
      .then((result) => {
        if (!active) return;
        setPromptPage(result);
        if (result.page !== page) setPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setListError(reason instanceof Error ? reason.message : "Could not load prompts.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [server.id, page, pageSize, refreshKey]);

  function choosePrompt(prompt: PromptDefinition) {
    setSelectedPrompt(prompt);
    setForm({
      name: prompt.name,
      description: prompt.description,
      template: prompt.template,
      arguments: prompt.arguments.map(argumentDraft),
    });
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function startNewPrompt() {
    setSelectedPrompt(null);
    setForm(emptyPrompt);
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function updateArgument(key: string, update: Partial<PromptArgumentDraft>) {
    setFieldErrors({});
    setError("");
    setForm((current) => ({
      ...current,
      arguments: current.arguments.map((argument) =>
        argument.key === key ? { ...argument, ...update } : argument,
      ),
    }));
  }

  function addArgument() {
    if (form.arguments.length >= 32) return;
    setForm((current) => ({
      ...current,
      arguments: [
        ...current.arguments,
        {
          key: crypto.randomUUID(),
          name: "",
          description: "",
          required: true,
          default_value: null,
        },
      ],
    }));
  }

  function removeArgument(key: string) {
    setForm((current) => ({
      ...current,
      arguments: current.arguments.filter((argument) => argument.key !== key),
    }));
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFieldErrors({});
    setFieldIssues([]);
    setError("");
    const validationErrors: Record<string, string> = {};
    for (const field of ["name", "description", "template"] as const) {
      const message = validateReactField(form[field], fieldRules[field]);
      if (message) validationErrors[field] = message;
    }
    const argumentNames = new Map<string, number>();
    form.arguments.forEach((argument, index) => {
      const nameField = `arguments.${index}.name`;
      const nameMessage = validateReactField(argument.name, fieldRules[nameField]);
      if (nameMessage) validationErrors[nameField] = nameMessage;
      const descriptionMessage = validateReactField(
        argument.description,
        fieldRules[`arguments.${index}.description`],
      );
      if (descriptionMessage) {
        validationErrors[`arguments.${index}.description`] = descriptionMessage;
      }
      const defaultMessage = validateReactField(
        argument.default_value ?? "",
        fieldRules[`arguments.${index}.default_value`],
      );
      if (defaultMessage) {
        validationErrors[`arguments.${index}.default_value`] = defaultMessage;
      }
      if (argument.name.trim() && argumentNames.has(argument.name.trim())) {
        validationErrors[`arguments.${index}.name`] = "Argument names must be unique.";
      } else if (argument.name.trim()) {
        argumentNames.set(argument.name.trim(), index);
      }
    });
    const placeholderPattern = /\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}/g;
    const placeholders = [...form.template.matchAll(placeholderPattern)].map(
      (match) => match[1],
    );
    const unmatchedTemplate = form.template.replace(placeholderPattern, "");
    if (unmatchedTemplate.includes("{{") || unmatchedTemplate.includes("}}")) {
      validationErrors.template = "Use placeholders in the form {{argument_name}}.";
    } else {
      const placeholderNames = new Set(placeholders);
      const unknownNames = [...placeholderNames].filter((name) => !argumentNames.has(name));
      if (unknownNames.length > 0) {
        validationErrors.template =
          `Define arguments for these placeholders: ${unknownNames.sort().join(", ")}.`;
      }
      form.arguments.forEach((argument, index) => {
        if (argument.name.trim() && !placeholderNames.has(argument.name.trim())) {
          validationErrors[`arguments.${index}.name`] =
            "Use this argument in the template.";
        }
      });
    }
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setError("Complete the required fields and correct the highlighted values.");
      return;
    }
    setSaving(true);
    setNotice("");
    try {
      const { arguments: promptArguments, ...fields } = form;
      const definition = {
        ...fields,
        arguments: promptArguments.map(
          (argument): PromptArgumentDefinition => ({
            name: argument.name,
            description: argument.description,
            required: argument.required,
            default_value: argument.default_value,
          }),
        ),
      };
      const saved = selectedPrompt
        ? await updatePrompt(server.id, selectedPrompt.id, definition)
        : await createPrompt(server.id, definition);
      setSelectedPrompt(saved);
      setForm({
        name: saved.name,
        description: saved.description,
        template: saved.template,
        arguments: saved.arguments.map(argumentDraft),
      });
      if (selectedPrompt) {
        setPromptPage((current) =>
          current
            ? {
                ...current,
                items: current.items.map((prompt) =>
                  prompt.id === saved.id ? saved : prompt,
                ),
              }
            : current,
        );
      } else {
        setPage(Math.max(1, Math.ceil((total + 1) / pageSize)));
        setRefreshKey((current) => current + 1);
      }
      setNotice("Prompt saved and published to MCP clients.");
      setIsEditorOpen(false);
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setError(reason instanceof Error ? reason.message : "Could not save prompt definition.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selectedPrompt) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await deletePrompt(server.id, selectedPrompt.id);
      const nextTotal = Math.max(total - 1, 0);
      setPage(Math.min(page, Math.max(1, Math.ceil(nextTotal / pageSize))));
      setRefreshKey((current) => current + 1);
      setSelectedPrompt(null);
      setForm(emptyPrompt);
      setIsEditorOpen(false);
      setNotice("Prompt deleted.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the prompt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="prompt-studio panel capability-content-panel">
      <header className="page-heading tool-page-heading">
        <div className="page-title-group">
          <h2 className="sr-only">Prompts</h2>
          <p className="subtitle">Create reusable prompt templates for MCP clients.</p>
        </div>
        <Button variant="secondary" onClick={startNewPrompt} type="button">
          New prompt
        </Button>
      </header>

      {notice && <div className="message success-message resource-page-notice" role="status">{notice}</div>}
      {showInitialSkeleton ? (
        <ResourceCardSkeletonGrid label="prompts" />
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
      ) : !promptPage || total === 0 ? (
        <div className="resource-empty-state">
          <h2>No prompts yet</h2>
          <p>Create a reusable template for your MCP clients.</p>
          <Button variant="secondary" onClick={startNewPrompt} type="button">
            Create your first prompt
          </Button>
        </div>
      ) : (
        <>
          <ResourceCardGrid label="Saved prompts" busy={loading}>
            {prompts.map((prompt) => (
              <ResourceCard
                key={prompt.id}
                name={prompt.name}
                description={prompt.description}
                status="Published"
                statusTone="published"
                metadata={`${prompt.arguments.length} ${prompt.arguments.length === 1 ? "argument" : "arguments"}`}
                editLabel={prompt.name}
                onEdit={() => choosePrompt(prompt)}
              />
            ))}
          </ResourceCardGrid>
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            itemLabel="prompts"
            navigationLabel="Prompt pages"
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
        title={selectedPrompt ? `Edit ${selectedPrompt.name}` : "Create a prompt"}
        description={`Use named placeholders such as {{topic}} in the template.`}
        onClose={() => setIsEditorOpen(false)}
      >
        <form
          id="prompt-editor-form"
          noValidate
          onSubmit={(event) => void handleSave(event)}
          onBlurCapture={(event) =>
            validateReactFieldOnBlur(event, fieldRules, (field, message) =>
              setFieldErrors((current) => ({ ...current, [field]: message })),
            )
          }
        >
            <RequiredFieldsNote />
            <div className="prompt-form-grid">
              <div>
                <FieldLabel htmlFor="prompt-name" required>Prompt name</FieldLabel>
                <input
                  id="prompt-name"
                  name="name"
                  autoComplete="off"
                  aria-invalid={Boolean(fieldErrors.name)}
                  aria-describedby={fieldErrors.name ? "prompt-name-error" : undefined}
                  value={form.name}
                  onChange={(event) => {
                    setFieldErrors((current) => ({ ...current, name: "" }));
                    setError("");
                    setForm((current) => ({ ...current, name: event.target.value }));
                  }}
                  placeholder="e.g. summarize_report"
                />
                <FieldError id="prompt-name-error" message={fieldErrors.name} />
              </div>
              <div>
                <FieldLabel htmlFor="prompt-description">
                  Description <span className="optional">Optional</span>
                </FieldLabel>
                <input
                  id="prompt-description"
                  name="description"
                  aria-invalid={Boolean(fieldErrors.description)}
                  aria-describedby={
                    fieldErrors.description ? "prompt-description-error" : undefined
                  }
                  value={form.description}
                  onChange={(event) => {
                    setError("");
                    setFieldErrors((current) => ({ ...current, description: "" }));
                    setForm((current) => ({ ...current, description: event.target.value }))
                  }}
                  placeholder="What this prompt helps the client do"
                />
                <FieldError
                  id="prompt-description-error"
                  message={fieldErrors.description}
                />
              </div>
            </div>

            <FieldLabel htmlFor="prompt-template" required>Template</FieldLabel>
            <textarea
              className="code-editor prompt-template-editor"
              id="prompt-template"
              name="template"
              value={form.template}
              aria-invalid={Boolean(fieldErrors.template)}
              aria-describedby={fieldErrors.template ? "prompt-template-error" : undefined}
              onChange={(event) => {
                setFieldErrors((current) => ({ ...current, template: "" }));
                setError("");
                setForm((current) => ({ ...current, template: event.target.value }));
              }}
              placeholder={"Summarize {{report}} for {{audience}}."}
            />
            <FieldError id="prompt-template-error" message={fieldErrors.template} />
            <p className="form-note tool-source-help">
              Required arguments must be supplied by the MCP client. Optional arguments use their
              default value, or an empty string when no default is set. Use {"${NAME}"} for a
              workspace value; secret values are included in the prompt returned to the client.
            </p>
            <WorkspaceValueGuide context="prompt" />

            <div className="prompt-arguments-heading">
              <div>
                <h3>Arguments</h3>
                <p>Declare each placeholder used in the template.</p>
              </div>
              <Button
                variant="secondary"
                disabled={form.arguments.length >= 32}
                onClick={addArgument}
                type="button"
              >
                Add argument
              </Button>
            </div>

            {form.arguments.length > 0 && (
              <div className="prompt-arguments">
                {form.arguments.map((argument, index) => (
                  <fieldset className="prompt-argument" key={argument.key}>
                    <legend>Argument {index + 1}</legend>
                    <div className="prompt-argument-fields">
                      <div>
                        <FieldLabel
                          htmlFor={`prompt-argument-name-${argument.key}`}
                          required
                        >
                          Name
                        </FieldLabel>
                        <input
                          id={`prompt-argument-name-${argument.key}`}
                          name={`arguments.${index}.name`}
                          autoComplete="off"
                          aria-invalid={Boolean(fieldErrors[`arguments.${index}.name`])}
                          aria-describedby={
                            fieldErrors[`arguments.${index}.name`]
                              ? `prompt-argument-name-error-${argument.key}`
                              : undefined
                          }
                          value={argument.name}
                          onChange={(event) =>
                            updateArgument(argument.key, { name: event.target.value })
                          }
                          placeholder="e.g. report"
                        />
                        <FieldError
                          id={`prompt-argument-name-error-${argument.key}`}
                          message={fieldErrors[`arguments.${index}.name`]}
                        />
                      </div>
                      <div>
                        <FieldLabel htmlFor={`prompt-argument-description-${argument.key}`}>
                          Description <span className="optional">Optional</span>
                        </FieldLabel>
                        <input
                          id={`prompt-argument-description-${argument.key}`}
                          name={`arguments.${index}.description`}
                          aria-invalid={
                            Boolean(fieldErrors[`arguments.${index}.description`])
                          }
                          aria-describedby={
                            fieldErrors[`arguments.${index}.description`]
                              ? `prompt-argument-description-error-${argument.key}`
                              : undefined
                          }
                          value={argument.description}
                          onChange={(event) =>
                            updateArgument(argument.key, {
                              description: event.target.value,
                            })
                          }
                          placeholder="What value to provide"
                        />
                        <FieldError
                          id={`prompt-argument-description-error-${argument.key}`}
                          message={fieldErrors[`arguments.${index}.description`]}
                        />
                      </div>
                      {!argument.required && (
                        <div>
                          <FieldLabel htmlFor={`prompt-argument-default-${argument.key}`}>
                            Default value <span className="optional">Optional</span>
                          </FieldLabel>
                          <input
                            id={`prompt-argument-default-${argument.key}`}
                            name={`arguments.${index}.default_value`}
                            aria-invalid={
                              Boolean(fieldErrors[`arguments.${index}.default_value`])
                            }
                            aria-describedby={
                              fieldErrors[`arguments.${index}.default_value`]
                                ? `prompt-argument-default-error-${argument.key}`
                                : undefined
                            }
                            value={argument.default_value ?? ""}
                            onChange={(event) =>
                              updateArgument(argument.key, {
                                default_value: event.target.value,
                              })
                            }
                            placeholder="Leave blank to use an empty string"
                          />
                          <FieldError
                            id={`prompt-argument-default-error-${argument.key}`}
                            message={fieldErrors[`arguments.${index}.default_value`]}
                          />
                        </div>
                      )}
                    </div>
                    <div className="prompt-argument-actions">
                      <label className="prompt-required-toggle">
                        <input
                          id={`prompt-argument-required-${argument.key}`}
                          name={`arguments.${index}.required`}
                          checked={argument.required}
                          onChange={(event) =>
                            updateArgument(argument.key, {
                              required: event.target.checked,
                              default_value: event.target.checked
                                ? null
                                : argument.default_value,
                            })
                          }
                          type="checkbox"
                        />
                        Required
                      </label>
                      <Button
                        variant="text"
                        className="danger-text-button"
                        onClick={() => removeArgument(argument.key)}
                        type="button"
                      >
                        Remove argument
                      </Button>
                    </div>
                  </fieldset>
                ))}
              </div>
            )}

            <FormErrorSummary
              message={error}
              fieldIssues={fieldIssues}
              formId="prompt-editor-form"
            />
            <div className="resource-modal-actions">
              {selectedPrompt && (
                <Button
                  variant="text"
                  className="danger-text-button"
                  disabled={saving}
                  onClick={() => void handleDelete()}
                  type="button"
                >
                  Delete prompt
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
                  {saving ? "Saving…" : selectedPrompt ? "Save changes" : "Create prompt"}
                </Button>
              </div>
            </div>
          </form>
      </ResourceModal>
    </section>
  );
}
