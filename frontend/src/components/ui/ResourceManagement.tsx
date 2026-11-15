import { useEffect, useId, useRef, type ReactNode } from "react";

import Button from "./Button";

type ResourceCardProps = {
  name: string;
  description: string;
  status: string;
  statusTone: "published" | "draft";
  metadata: string;
  editLabel: string;
  onEdit: () => void;
};

type ResourceCardLayoutProps = {
  name: string;
  description: string;
  icon?: ReactNode;
  nameClassName?: string;
  className?: string;
  role?: "listitem";
  headingAside?: ReactNode;
  footerLeading?: ReactNode;
  footerAction: ReactNode;
};

export function ResourceCardLayout({
  name,
  description,
  icon,
  nameClassName,
  className,
  role,
  headingAside,
  footerLeading,
  footerAction,
}: ResourceCardLayoutProps) {
  return (
    <article
      className={`resource-card${className ? ` ${className}` : ""}`}
      role={role}
    >
      <div className="resource-card-heading">
        <div className="resource-card-title-group">
          {icon}
          <h2 className={`resource-card-name${nameClassName ? ` ${nameClassName}` : ""}`}>
            {name}
          </h2>
        </div>
        {headingAside}
      </div>
      <p className="resource-card-description">{description || "No description"}</p>
      <div className="resource-card-footer">
        {footerLeading}
        {footerAction}
      </div>
    </article>
  );
}

export function ResourceCard({
  name,
  description,
  status,
  statusTone,
  metadata,
  editLabel,
  onEdit,
}: ResourceCardProps) {
  return (
    <ResourceCardLayout
      name={name}
      description={description}
      role="listitem"
      headingAside={<span className={`resource-status ${statusTone}`}>{status}</span>}
      footerLeading={<span className="resource-card-metadata">{metadata}</span>}
      footerAction={
        <Button
          variant="secondary"
          className="resource-card-edit icon-tooltip icon-tooltip--above-right"
          onClick={onEdit}
          type="button"
          aria-label={`Edit ${editLabel}`}
          data-tooltip={`Edit ${editLabel}`}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path d="m12.2 4.3 3.5 3.5M4 16l3.5-.8L16 6.7a1.8 1.8 0 0 0-2.6-2.6L4.9 12.5 4 16Z" />
          </svg>
        </Button>
      }
    />
  );
}

type ResourceCardGridProps = {
  label: string;
  busy?: boolean;
  children: ReactNode;
};

export function ResourceCardGrid({ label, busy, children }: ResourceCardGridProps) {
  return (
    <div className="resource-card-grid" role="list" aria-label={label} aria-busy={busy}>
      {children}
    </div>
  );
}

type ResourceModalProps = {
  open: boolean;
  title: string;
  description: string;
  closeLabel?: string;
  onClose: () => void;
  children: ReactNode;
};

export function ResourceModal({
  open,
  title,
  description,
  closeLabel = "Close editor",
  onClose,
  children,
}: ResourceModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = `resource-modal-${useId()}`;
  const descriptionId = `${titleId}-description`;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
      const body = dialog.querySelector<HTMLElement>(".resource-modal-body");
      const initialFocusTarget = body?.querySelector<HTMLElement>(
        'input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled), [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
      );
      if (initialFocusTarget) {
        initialFocusTarget.focus({ preventScroll: true });
      } else {
        dialog.focus({ preventScroll: true });
      }
      if (body) body.scrollTop = 0;
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="resource-editor-modal"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      tabIndex={-1}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="resource-modal-header">
        <div>
          <h2 id={titleId}>{title}</h2>
          <p id={descriptionId}>{description}</p>
        </div>
        <Button
          variant="text"
          className="resource-modal-close icon-tooltip icon-tooltip--below-right"
          onClick={onClose}
          type="button"
          aria-label={closeLabel}
          data-tooltip={closeLabel}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path d="m5 5 10 10M15 5 5 15" />
          </svg>
        </Button>
      </header>
      {open && <div className="resource-modal-body">{children}</div>}
    </dialog>
  );
}
