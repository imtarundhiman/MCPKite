import { useEffect, useState, type FormEvent } from "react";

import {
  createBinaryResource,
  createResource,
  deleteResource,
  listResourcePage,
  updateBinaryResource,
  updateResource,
} from "../api/resources";
import { ApiError, getApiFieldErrors } from "../api/client";
import type { ResourceMetadata } from "../api/resources";
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
  ResourceDefinition,
  ResourceDefinitionPage,
  Server,
} from "../types/server";

type ResourceForm = Omit<ResourceMetadata, "priority"> & {
  content: string;
  priority: string;
};

const emptyResource: ResourceForm = {
  uri: "",
  name: "",
  description: "",
  mime_type: "text/plain",
  content: "",
  audience: [],
  priority: "",
};
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
type BinaryMimeOption = {
  mimeType: string;
  label: string;
  extensions: readonly string[];
};
const BINARY_MIME_GROUPS: {
  label: string;
  options: readonly BinaryMimeOption[];
}[] = [
  {
    label: "Text and structured data",
    options: [
      { mimeType: "text/plain", label: "Plain text", extensions: [".txt"] },
      { mimeType: "text/markdown", label: "Markdown", extensions: [".md", ".markdown"] },
      { mimeType: "text/csv", label: "CSV", extensions: [".csv"] },
      { mimeType: "application/json", label: "JSON", extensions: [".json"] },
      { mimeType: "application/xml", label: "XML", extensions: [".xml"] },
    ],
  },
  {
    label: "Documents",
    options: [
      { mimeType: "application/pdf", label: "PDF", extensions: [".pdf"] },
      { mimeType: "application/rtf", label: "Rich Text", extensions: [".rtf"] },
      { mimeType: "application/msword", label: "Word (DOC)", extensions: [".doc"] },
      {
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        label: "Word (DOCX)",
        extensions: [".docx"],
      },
      { mimeType: "application/vnd.ms-excel", label: "Excel (XLS)", extensions: [".xls"] },
      {
        mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        label: "Excel (XLSX)",
        extensions: [".xlsx"],
      },
      { mimeType: "application/vnd.ms-powerpoint", label: "PowerPoint (PPT)", extensions: [".ppt"] },
      {
        mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        label: "PowerPoint (PPTX)",
        extensions: [".pptx"],
      },
    ],
  },
  {
    label: "Images",
    options: [
      { mimeType: "image/png", label: "PNG", extensions: [".png"] },
      { mimeType: "image/jpeg", label: "JPEG", extensions: [".jpg", ".jpeg"] },
      { mimeType: "image/gif", label: "GIF", extensions: [".gif"] },
      { mimeType: "image/webp", label: "WebP", extensions: [".webp"] },
      { mimeType: "image/svg+xml", label: "SVG", extensions: [".svg"] },
    ],
  },
];
const BINARY_MIME_TYPES = BINARY_MIME_GROUPS.flatMap((group) => group.options);
const BINARY_MIME_BY_TYPE = new Map<string, BinaryMimeOption>(
  BINARY_MIME_TYPES.map((option) => [option.mimeType, option] as const),
);
const BINARY_MIME_BY_EXTENSION = new Map<string, string>(
  BINARY_MIME_TYPES.flatMap((option) =>
    option.extensions.map((extension) => [extension, option.mimeType] as const),
  ),
);
const BINARY_FILE_ACCEPT = BINARY_MIME_TYPES.flatMap((option) => [
  option.mimeType,
  ...option.extensions,
]).join(",");
const RESOURCE_AUDIENCES = [
  { value: "user", label: "User" },
  { value: "assistant", label: "Assistant" },
] as const;

function getFileExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf(".");
  return dotIndex > 0 ? fileName.slice(dotIndex).toLowerCase() : "";
}

function inferBinaryMimeType(fileName: string): string | undefined {
  return BINARY_MIME_BY_EXTENSION.get(getFileExtension(fileName));
}

function getBinaryFileTypeError(file: File, mimeType: string): string {
  const definition = BINARY_MIME_BY_TYPE.get(mimeType);
  if (!definition) return "Choose a supported MIME type for this file.";

  const extension = getFileExtension(file.name);
  if (!definition.extensions.some((supportedExtension) => supportedExtension === extension)) {
    return `Choose a file with a ${definition.extensions.join(" or ")} extension.`;
  }

  const reportedMimeType = file.type.trim().toLowerCase();
  if (
    reportedMimeType &&
    reportedMimeType !== "application/octet-stream" &&
    reportedMimeType !== mimeType
  ) {
    return `The file reports ${reportedMimeType}; choose a file reported as ${mimeType}.`;
  }

  return "";
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ResourceStudio({ server }: { server: Server }) {
  const [resourcePage, setResourcePage] = useState<ResourceDefinitionPage | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(12);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedResource, setSelectedResource] = useState<ResourceDefinition | null>(null);
  const [form, setForm] = useState<ResourceForm>(emptyResource);
  const [contentKind, setContentKind] = useState<ResourceDefinition["content_kind"]>("text");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileValidationError, setFileValidationError] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [listError, setListError] = useState("");
  const [notice, setNotice] = useState("");
  const resources = resourcePage?.items ?? [];
  const total = resourcePage?.total ?? 0;
  const totalPages = resourcePage?.total_pages ?? 0;
  const showInitialSkeleton = useMinimumInitialLoading(loading);
  const fieldRules: Record<string, ReactFieldRule> = {
    name: {
      required: "Enter a resource name.",
      maxLength: { value: 100, message: "Resource names can be at most 100 characters." },
    },
    uri: {
      required: "Enter a resource URI.",
      maxLength: { value: 2048, message: "Resource URIs can be at most 2,048 characters." },
    },
    description: {
      maxLength: { value: 300, message: "Descriptions can be at most 300 characters." },
    },
    content: {
      maxLength: { value: 50_000, message: "Text content can be at most 50,000 characters." },
    },
    mime_type: {
      required: "Choose a MIME type.",
      validate: (value) =>
        value && !BINARY_MIME_BY_TYPE.has(value)
          ? "Choose a supported MIME type."
          : "",
    },
    priority: {
      number: {
        min: 0,
        max: 1,
        step: 0.1,
        message: "Enter a priority from 0 to 1 in increments of 0.1.",
      },
    },
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setListError("");
    listResourcePage(server.id, page, pageSize)
      .then((result) => {
        if (!active) return;
        setResourcePage(result);
        if (result.page !== page) setPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setListError(reason instanceof Error ? reason.message : "Could not load resources.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [server.id, page, pageSize, refreshKey]);

  function chooseResource(resource: ResourceDefinition) {
    setSelectedResource(resource);
    setForm({
      uri: resource.uri,
      name: resource.name,
      description: resource.description,
      mime_type:
        resource.content_kind === "binary" && !BINARY_MIME_BY_TYPE.has(resource.mime_type)
          ? ""
          : resource.mime_type,
      content: resource.content ?? "",
      audience: resource.audience,
      priority: resource.priority === null ? "" : String(resource.priority),
    });
    setContentKind(resource.content_kind);
    setSelectedFile(null);
    setFileValidationError("");
    setUploadProgress(null);
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function startNewResource() {
    setSelectedResource(null);
    setForm(emptyResource);
    setContentKind("text");
    setSelectedFile(null);
    setFileValidationError("");
    setUploadProgress(null);
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    setNotice("");
    setIsEditorOpen(true);
  }

  function handleFileChange(file: File | undefined, input: HTMLInputElement) {
    setError("");
    setFieldErrors((current) => ({ ...current, file: "", mime_type: "" }));
    setFileValidationError("");
    if (!file) {
      setSelectedFile(null);
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setSelectedFile(null);
      input.value = "";
      setFileValidationError("Choose a file that is 50 MiB or smaller.");
      setFieldErrors((current) => ({
        ...current,
        file: "Choose a file that is 50 MiB or smaller.",
      }));
      return;
    }
    setSelectedFile(file);
    const inferredMimeType = inferBinaryMimeType(file.name);
    const mimeType = selectedResource
      ? inferredMimeType ?? form.mime_type
      : form.mime_type || inferredMimeType || "";
    if (inferredMimeType && (selectedResource || !form.mime_type)) {
      setForm((current) => ({ ...current, mime_type: inferredMimeType }));
    }
    if (!mimeType) {
      setFileValidationError(
        "This file extension is not supported. Choose a supported file format.",
      );
      return;
    }
    setFileValidationError(getBinaryFileTypeError(file, mimeType));
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    const validationErrors: Record<string, string> = {};
    for (const field of ["name", "uri", "description"] as const) {
      const message = validateReactField(form[field], fieldRules[field]);
      if (message) validationErrors[field] = message;
    }
    if (contentKind === "text") {
      const message = validateReactField(form.content, fieldRules.content);
      if (message) validationErrors.content = message;
    }
    const priorityError = validateReactField(form.priority, fieldRules.priority);
    if (priorityError) validationErrors.priority = priorityError;
    if (
      contentKind === "binary" &&
      (!selectedResource || selectedFile) &&
      !form.mime_type
    ) {
      validationErrors.mime_type = "Choose a MIME type.";
    } else if (contentKind === "binary" && (!selectedResource || selectedFile)) {
      const message = validateReactField(form.mime_type, fieldRules.mime_type);
      if (message) validationErrors.mime_type = message;
    }
    if (contentKind === "binary" && fileValidationError) {
      if (selectedFile) validationErrors.mime_type = fileValidationError;
      else validationErrors.file = fileValidationError;
    } else if (contentKind === "binary" && selectedFile && selectedFile.size > MAX_UPLOAD_BYTES) {
      validationErrors.file = "Choose a file that is 50 MiB or smaller.";
    } else if (contentKind === "binary" && !selectedResource && !selectedFile) {
      validationErrors.file = "Choose a file to create this resource.";
    }
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setError("Complete the required fields and correct the highlighted values.");
      return;
    }
    if (contentKind === "binary" && selectedFile) {
      const validationError = getBinaryFileTypeError(selectedFile, form.mime_type);
      if (validationError) {
        setFileValidationError(validationError);
        setFieldErrors({ mime_type: validationError });
        setError("Correct the highlighted file type before saving.");
        document.getElementById("resource-mime-type")?.focus();
        return;
      }
    }
    setSaving(true);
    setFileValidationError("");
    setNotice("");
    setUploadProgress(null);
    try {
      const metadata: ResourceMetadata = {
        uri: form.uri,
        name: form.name,
        description: form.description,
        mime_type: form.mime_type,
        audience: form.audience,
        priority: form.priority.trim() ? Number(form.priority) : null,
      };
      let saved: ResourceDefinition;
      if (contentKind === "binary") {
        if (selectedResource) {
          saved = await updateBinaryResource(
              server.id,
              selectedResource.id,
              metadata,
              selectedFile ?? undefined,
              setUploadProgress,
            );
        } else {
          if (!selectedFile) {
            throw new Error("Choose a file before creating a binary resource.");
          }
          saved = await createBinaryResource(
              server.id,
              metadata,
              selectedFile,
              setUploadProgress,
            );
        }
      } else {
        const definition = { ...metadata, content: form.content };
        saved = selectedResource
          ? await updateResource(server.id, selectedResource.id, definition)
          : await createResource(server.id, definition);
      }
      setSelectedResource(saved);
      setForm({
        uri: saved.uri,
        name: saved.name,
        description: saved.description,
        mime_type: saved.mime_type,
        content: saved.content ?? "",
        audience: saved.audience,
        priority: saved.priority === null ? "" : String(saved.priority),
      });
      setContentKind(saved.content_kind);
      setSelectedFile(null);
      setFileValidationError("");
      if (selectedResource) {
        setResourcePage((current) =>
          current
            ? {
                ...current,
                items: current.items.map((resource) =>
                  resource.id === saved.id ? saved : resource,
                ),
              }
            : current,
        );
      } else {
        setPage(Math.max(1, Math.ceil((total + 1) / pageSize)));
        setRefreshKey((current) => current + 1);
      }
      setNotice("Resource saved and published to MCP clients.");
      setIsEditorOpen(false);
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setError(reason instanceof Error ? reason.message : "Could not save resource definition.");
    } finally {
      setSaving(false);
      setUploadProgress(null);
    }
  }

  async function handleDelete() {
    if (!selectedResource) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await deleteResource(server.id, selectedResource.id);
      const nextTotal = Math.max(total - 1, 0);
      setPage(Math.min(page, Math.max(1, Math.ceil(nextTotal / pageSize))));
      setRefreshKey((current) => current + 1);
      setSelectedResource(null);
      setForm(emptyResource);
      setIsEditorOpen(false);
      setNotice("Resource deleted.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the resource.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="resource-studio prompt-studio panel capability-content-panel">
      <header className="page-heading tool-page-heading">
        <div className="page-title-group">
          <h2 className="sr-only">Resources</h2>
          <p className="subtitle">
            Manage text resources, URI templates, and private binary files.
          </p>
        </div>
        <Button variant="secondary" onClick={startNewResource} type="button">
          New resource
        </Button>
      </header>

      {notice && (
        <div className="message success-message resource-page-notice" role="status">
          {notice}
        </div>
      )}
      {showInitialSkeleton ? (
        <ResourceCardSkeletonGrid label="resources" />
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
      ) : !resourcePage || total === 0 ? (
        <div className="resource-empty-state">
          <h2>No resources yet</h2>
          <p>Publish text and file-based reference data your MCP clients can discover and read.</p>
          <Button variant="secondary" onClick={startNewResource} type="button">
            Create your first resource
          </Button>
        </div>
      ) : (
        <>
          <ResourceCardGrid label="Saved resources" busy={loading}>
            {resources.map((resource) => (
              <ResourceCard
                key={resource.id}
                name={resource.name}
                description={
                  resource.description ||
                  (resource.content_kind === "binary"
                    ? `${resource.file_name ?? "Uploaded file"} · ${resource.uri}`
                    : resource.uri)
                }
                status="Published"
                statusTone="published"
                metadata={
                  resource.content_kind === "binary"
                    ? `${formatFileSize(resource.size_bytes ?? 0)} · ${resource.mime_type}`
                    : `${resource.uri} · ${resource.mime_type}`
                }
                editLabel={resource.name}
                onEdit={() => chooseResource(resource)}
              />
            ))}
          </ResourceCardGrid>
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            itemLabel="resources"
            navigationLabel="Resource pages"
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
        title={selectedResource ? `Edit ${selectedResource.name}` : "Create a resource"}
        description={
          contentKind === "binary"
            ? "Publish a private file at a static URI. Uploaded files are limited to 50 MiB."
            : "Publish text content at a URI or a parameterized URI template."
        }
        onClose={() => {
          if (!saving) setIsEditorOpen(false);
        }}
      >
        <form
          id="resource-editor-form"
          noValidate
          className="resource-form"
          onSubmit={(event) => void handleSave(event)}
          onBlurCapture={(event) =>
            validateReactFieldOnBlur(event, fieldRules, (field, message) =>
              setFieldErrors((current) => ({ ...current, [field]: message })),
            )
          }
        >
          <RequiredFieldsNote />
          {!selectedResource && (
            <fieldset className="resource-kind-picker">
              <legend>
                Resource content <span className="required" aria-hidden="true">*</span>
                <span className="sr-only"> required</span>
              </legend>
              <div className="resource-kind-options">
                <label className={contentKind === "text" ? "selected" : ""}>
                  <input
                    id="resource-kind-text"
                    type="radio"
                    name="resource-content-kind"
                    value="text"
                    checked={contentKind === "text"}
                    onChange={() => {
                      setError("");
                      setContentKind("text");
                      setSelectedFile(null);
                      setFileValidationError("");
                      setForm((current) => ({
                        ...current,
                        mime_type: "text/plain",
                      }));
                    }}
                  />
                  <span>
                    <strong>Text</strong>
                    <small>Static content or a URI template</small>
                  </span>
                </label>
                <label className={contentKind === "binary" ? "selected" : ""}>
                  <input
                    id="resource-kind-file"
                    type="radio"
                    name="resource-content-kind"
                    value="binary"
                    checked={contentKind === "binary"}
                    onChange={() => {
                      setError("");
                      setContentKind("binary");
                      setForm((current) => ({
                        ...current,
                        uri: current.uri.includes("{") ? "" : current.uri,
                        mime_type: "",
                      }));
                    }}
                  />
                  <span>
                    <strong>File</strong>
                    <small>Upload a private binary resource</small>
                  </span>
                </label>
              </div>
            </fieldset>
          )}
          <div className="prompt-form-grid">
            <div>
              <FieldLabel htmlFor="resource-name" required>Resource name</FieldLabel>
              <input
                id="resource-name"
                name="name"
                autoComplete="off"
                value={form.name}
                aria-invalid={Boolean(fieldErrors.name)}
                aria-describedby={fieldErrors.name ? "resource-name-error" : undefined}
                onChange={(event) => {
                  setFieldErrors((current) => ({ ...current, name: "" }));
                  setError("");
                  setForm((current) => ({ ...current, name: event.target.value }));
                }}
                placeholder="e.g. Product documentation"
              />
              <FieldError id="resource-name-error" message={fieldErrors.name} />
            </div>
            {contentKind === "binary" && (
              <div className="resource-mime-field">
                <FieldLabel
                  htmlFor="resource-mime-type"
                  required={!selectedResource || Boolean(selectedFile)}
                >
                  MIME type
                </FieldLabel>
                <select
                  id="resource-mime-type"
                  name="mime_type"
                  value={form.mime_type}
                  disabled={saving || Boolean(selectedResource && !selectedFile)}
                  aria-invalid={Boolean(fileValidationError || fieldErrors.mime_type)}
                  aria-describedby={
                    fileValidationError || fieldErrors.mime_type
                      ? "resource-file-type-error"
                      : "resource-mime-help"
                  }
                  onChange={(event) => {
                    const mimeType = event.target.value;
                    setFieldErrors((current) => ({ ...current, mime_type: "" }));
                    setError("");
                    setForm((current) => ({ ...current, mime_type: mimeType }));
                    setFileValidationError(
                      selectedFile ? getBinaryFileTypeError(selectedFile, mimeType) : "",
                    );
                  }}
                >
                  <option value="" disabled>Choose a supported type</option>
                  {BINARY_MIME_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.options.map((option) => (
                        <option key={option.mimeType} value={option.mimeType}>
                          {option.label} ({option.extensions.join(", ")}) — {option.mimeType}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <p id="resource-mime-help" className="form-note">
                  {selectedResource && !selectedFile
                    ? "Replace the file to change its MIME type."
                    : "The selected type must match the file extension and reported MIME type."}
                </p>
                <FieldError
                  id="resource-file-type-error"
                  message={fieldErrors.mime_type || fileValidationError}
                />
              </div>
            )}
            <div className="resource-form-wide">
              <FieldLabel htmlFor="resource-uri" required>Resource URI</FieldLabel>
              <input
                id="resource-uri"
                name="uri"
                value={form.uri}
                aria-invalid={Boolean(fieldErrors.uri)}
                aria-describedby={fieldErrors.uri ? "resource-uri-error" : undefined}
                onChange={(event) => {
                  setFieldErrors((current) => ({ ...current, uri: "" }));
                  setError("");
                  setForm((current) => ({ ...current, uri: event.target.value }));
                }}
                placeholder={
                  contentKind === "binary"
                    ? "files://assets/reference.pdf"
                    : "docs://handbook or docs://{document_id}"
                }
              />
              <FieldError id="resource-uri-error" message={fieldErrors.uri} />
            </div>
            <div className="resource-form-wide">
              <FieldLabel htmlFor="resource-description">
                Description <span className="optional">Optional</span>
              </FieldLabel>
              <input
                id="resource-description"
                name="description"
                value={form.description}
                aria-invalid={Boolean(fieldErrors.description)}
                aria-describedby={
                  fieldErrors.description ? "resource-description-error" : undefined
                }
                onChange={(event) => {
                  setError("");
                  setFieldErrors((current) => ({ ...current, description: "" }));
                  setForm((current) => ({ ...current, description: event.target.value }));
                }}
                placeholder="What can clients expect to find here?"
              />
              <FieldError
                id="resource-description-error"
                message={fieldErrors.description}
              />
            </div>
          </div>
          {contentKind === "text" ? (
            <div>
              <FieldLabel htmlFor="resource-content">
                Text content <span className="optional">Optional</span>
              </FieldLabel>
              <textarea
                id="resource-content"
                name="content"
                className="resource-content-editor"
                rows={12}
                value={form.content}
                aria-invalid={Boolean(fieldErrors.content)}
                aria-describedby={fieldErrors.content ? "resource-content-error" : undefined}
                onChange={(event) => {
                  setError("");
                  setFieldErrors((current) => ({ ...current, content: "" }));
                  setForm((current) => ({ ...current, content: event.target.value }));
                }}
                placeholder="Write the text returned when an MCP client reads this resource."
              />
              <FieldError id="resource-content-error" message={fieldErrors.content} />
              <p className="form-note resource-content-help">
                For URI templates, use matching content placeholders such as {"{{document_id}}"}.
                Use {"${NAME}"} for a workspace value. Values are inserted as plain text; no code
                is executed. A referenced secret is visible to the client reading this resource.
              </p>
              <WorkspaceValueGuide context="resource" />
            </div>
          ) : (
            <div className="resource-file-field">
              {selectedResource?.content_kind === "binary" && (
                <div className="resource-current-file">
                  <span className="resource-file-label">Current file</span>
                  <strong>{selectedResource.file_name}</strong>
                  <span>
                    {formatFileSize(selectedResource.size_bytes ?? 0)} · {selectedResource.mime_type}
                  </span>
                </div>
              )}
              {selectedResource?.content_kind === "binary" &&
                !BINARY_MIME_BY_TYPE.has(selectedResource.mime_type) && (
                  <p className="form-note resource-legacy-mime-note">
                    This existing file uses {selectedResource.mime_type}. It remains available;
                    replacements must use a supported type.
                  </p>
                )}
              <FieldLabel htmlFor="resource-file" required={!selectedResource}>
                {selectedResource ? "Replace file (optional)" : "Choose a file"}
              </FieldLabel>
              <input
                id="resource-file"
                name="file"
                type="file"
                disabled={saving}
                accept={BINARY_FILE_ACCEPT}
                aria-invalid={Boolean(fileValidationError || fieldErrors.file)}
                aria-describedby={
                  fileValidationError
                    ? selectedFile
                      ? "resource-file-type-error"
                      : "resource-file-error"
                    : fieldErrors.file
                      ? "resource-file-error"
                      : "resource-mime-help"
                }
                onChange={(event) =>
                  handleFileChange(event.currentTarget.files?.[0], event.currentTarget)
                }
              />
              <FieldError id="resource-file-error" message={fieldErrors.file} />
              {fileValidationError && !fieldErrors.mime_type && (
                <FieldError id="resource-file-type-error" message={fileValidationError} />
              )}
              <p className="form-note">
                Maximum file size is 50 MiB. Choose from the supported documents, text/data, and image formats.
              </p>
              {selectedFile && (
                <p className="resource-selected-file" role="status">
                  Selected: <strong>{selectedFile.name}</strong> · {formatFileSize(selectedFile.size)}
                </p>
              )}
              {saving && uploadProgress !== null && (
                <div className="resource-upload-progress" role="status" aria-live="polite">
                  <div>
                    <span>{uploadProgress === 100 ? "Upload complete" : "Uploading file"}</span>
                    <span>{uploadProgress}%</span>
                  </div>
                  <progress
                    max={100}
                    value={uploadProgress}
                    aria-label="Resource file upload progress"
                  />
                </div>
              )}
            </div>
          )}
          <fieldset className="resource-annotations">
            <legend>Suggested audience</legend>
            <div className="resource-audience-options">
              {RESOURCE_AUDIENCES.map(({ value, label }) => (
                <label key={value}>
                  <input
                    id={`resource-audience-${value}`}
                    type="checkbox"
                    name="audience"
                    checked={form.audience.includes(value)}
                    onChange={(event) => {
                      setError("");
                      setForm((current) => ({
                        ...current,
                        audience: event.target.checked
                          ? [...current.audience, value]
                          : current.audience.filter((entry) => entry !== value),
                      }));
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
            <p className="form-note">
              These hints help MCP clients decide when this resource is relevant.
            </p>
          </fieldset>
          <div className="resource-priority-field">
            <FieldLabel htmlFor="resource-priority">
              Priority <span className="optional">Optional</span>
            </FieldLabel>
            <input
              id="resource-priority"
              name="priority"
              type="text"
              inputMode="decimal"
              value={form.priority}
              aria-invalid={Boolean(fieldErrors.priority)}
              aria-describedby={fieldErrors.priority ? "resource-priority-error" : undefined}
              onChange={(event) => {
                setError("");
                setFieldErrors((current) => ({ ...current, priority: "" }));
                setForm((current) => ({
                  ...current,
                  priority: event.target.value,
                }));
              }}
            />
            <FieldError id="resource-priority-error" message={fieldErrors.priority} />
            <p className="form-note">Use a value from 0 to 1; higher values indicate greater relevance.</p>
          </div>
          <FormErrorSummary
            message={error}
            fieldIssues={fieldIssues}
            formId="resource-editor-form"
            fieldIdMap={
              selectedResource ? undefined : { content_kind: "resource-kind-text" }
            }
          />
          <div className="resource-modal-actions">
            {selectedResource && (
              <Button
                variant="text"
                className="danger-text-button"
                disabled={saving}
                onClick={() => void handleDelete()}
                type="button"
              >
                Delete resource
              </Button>
            )}
            <div className="resource-modal-action-group">
              <Button
                variant="secondary"
                disabled={saving}
                onClick={() => setIsEditorOpen(false)}
                type="button"
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={saving}
                type="submit"
              >
                {saving
                  ? contentKind === "binary" && uploadProgress !== null
                    ? `Uploading ${uploadProgress}%…`
                    : "Saving…"
                  : selectedResource
                    ? "Save changes"
                    : "Create resource"}
              </Button>
            </div>
          </div>
        </form>
      </ResourceModal>
    </section>
  );
}
