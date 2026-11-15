import {
  useEffect,
  useRef,
  type FocusEvent,
  type ReactNode,
} from "react";

export type FormFieldIssue = {
  field: string;
  message: string;
};

export type ReactFieldRule = {
  required?: string;
  trimRequired?: boolean;
  minLength?: { value: number; message: string };
  maxLength?: { value: number; message: string };
  pattern?: { value: RegExp; message: string };
  email?: string;
  number?: {
    min?: number;
    max?: number;
    step?: number;
    message: string;
  };
  validate?: (value: string) => string;
};

type FieldLabelProps = {
  htmlFor: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
  onClick?: () => void;
};

export function FieldLabel({
  htmlFor,
  required = false,
  children,
  className,
  onClick,
}: FieldLabelProps) {
  return (
    <label className={className} htmlFor={htmlFor} onClick={onClick}>
      {children}
      {required && (
        <>
          {" "}
          <span className="required" aria-hidden="true">*</span>
        </>
      )}
    </label>
  );
}

export function RequiredFieldsNote() {
  return (
    <p className="form-required-note">
      <span className="required" aria-hidden="true">*</span> Required fields
    </p>
  );
}

export function validateReactField(
  value: string,
  rule: ReactFieldRule,
): string {
  if (
    rule.required &&
    (rule.trimRequired === false ? !value : !value.trim())
  ) {
    return rule.required;
  }
  if (rule.minLength && value.length < rule.minLength.value) {
    return rule.minLength.message;
  }
  if (rule.maxLength && value.length > rule.maxLength.value) {
    return rule.maxLength.message;
  }
  if (rule.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())) {
    return rule.email;
  }
  if (rule.pattern && !rule.pattern.value.test(value)) {
    return rule.pattern.message;
  }
  if (rule.number) {
    const number = Number(value);
    if (!Number.isFinite(number)) return rule.number.message;
    if (
      (rule.number.min !== undefined && number < rule.number.min) ||
      (rule.number.max !== undefined && number > rule.number.max)
    ) {
      return rule.number.message;
    }
    if (rule.number.step !== undefined) {
      const base = rule.number.min ?? 0;
      const stepPosition = (number - base) / rule.number.step;
      if (Math.abs(stepPosition - Math.round(stepPosition)) > 1e-8) {
        return rule.number.message;
      }
    }
  }
  return rule.validate?.(value) ?? "";
}

export function validateReactFieldOnBlur(
  event: FocusEvent<HTMLFormElement>,
  rules: Record<string, ReactFieldRule>,
  onValidation: (field: string, message: string) => void,
) {
  const control = event.target;
  if (
    !(control instanceof HTMLInputElement) &&
    !(control instanceof HTMLTextAreaElement) &&
    !(control instanceof HTMLSelectElement)
  ) {
    return;
  }
  if (!control.name || !rules[control.name]) return;
  onValidation(
    control.name,
    validateReactField(control.value, rules[control.name]),
  );
}

export function FieldError({
  id,
  message,
}: {
  id: string;
  message?: string;
}) {
  if (!message) return null;
  return (
    <p className="form-field-error" id={id} aria-live="polite" aria-atomic="true">
      {message}
    </p>
  );
}

function formatFieldName(field: string): string {
  return field
    .split(".")
    .map((part) =>
      /^\d+$/.test(part)
        ? `argument ${Number(part) + 1}`
        : part.replaceAll("_", " "),
    )
    .join(" ");
}

export function FormErrorSummary({
  message,
  fieldIssues = [],
  formId,
  fieldIdMap,
}: {
  message: string;
  fieldIssues?: FormFieldIssue[];
  formId?: string;
  fieldIdMap?: Record<string, string>;
}) {
  const summaryRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (message) summaryRef.current?.focus();
  }, [message]);

  if (!message) return null;

  function getFieldId(field: string): string | undefined {
    const mappedId = fieldIdMap?.[field];
    if (mappedId && document.getElementById(mappedId)) return mappedId;
    if (!formId) return undefined;

    const form = document.getElementById(formId);
    if (!(form instanceof HTMLFormElement)) return undefined;

    const control = form.elements.namedItem(field);
    const target = control instanceof RadioNodeList ? control.item(0) : control;
    return target instanceof HTMLElement && target.id ? target.id : undefined;
  }

  return (
    <div
      className="message error-message form-error-summary"
      role="alert"
      aria-labelledby="form-error-summary-title"
      tabIndex={-1}
      ref={summaryRef}
    >
      <strong id="form-error-summary-title">Review this form</strong>
      {fieldIssues.length > 0 ? (
        <ul>
          {fieldIssues.map((issue, index) => {
            const fieldId = issue.field ? getFieldId(issue.field) : undefined;
            return (
              <li key={`${issue.field}-${index}`}>
                {fieldId ? (
                  <a
                    href={`#${fieldId}`}
                    onClick={(event) => {
                      event.preventDefault();
                      document.getElementById(fieldId)?.focus();
                    }}
                  >
                    {formatFieldName(issue.field)}: {issue.message}
                  </a>
                ) : (
                  <>
                    {issue.field ? `${formatFieldName(issue.field)}: ` : ""}
                    {issue.message}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p>{message}</p>
      )}
    </div>
  );
}
