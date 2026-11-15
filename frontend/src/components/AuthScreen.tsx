import { useState, type FormEvent } from "react";
import { ApiError, getApiFieldErrors } from "../api/client";
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

type AuthScreenProps = {
  workspaceInitialized: boolean;
  inviteToken: string | null;
  inviteWorkspaceName: string | null;
  inviteError: string;
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (
    displayName: string,
    email: string,
    password: string,
    workspaceName?: string,
    inviteToken?: string,
  ) => Promise<void>;
};

export default function AuthScreen({
  workspaceInitialized,
  inviteToken,
  inviteWorkspaceName,
  inviteError,
  onLogin,
  onRegister,
}: AuthScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [firstRunMode, setFirstRunMode] = useState<"create" | "login">("create");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [fieldIssues, setFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [busy, setBusy] = useState(false);
  const isInvitation = inviteToken !== null;
  const isFirstAccount = !workspaceInitialized && !isInvitation;
  const isLogin = !isInvitation && (
    workspaceInitialized || (isFirstAccount && firstRunMode === "login")
  );
  const isCreatingWorkspace = isFirstAccount && !isLogin;
  const fieldRules: Record<string, ReactFieldRule> = {
    email: {
      required: "Enter your email address.",
      maxLength: { value: 320, message: "Email addresses can be at most 320 characters." },
      email: "Enter a valid email address.",
    },
    password: {
      required: "Enter your password.",
      trimRequired: false,
      minLength: {
        value: isLogin ? 1 : 12,
        message: isLogin ? "Enter your password." : "Use at least 12 characters.",
      },
      maxLength: { value: 128, message: "Passwords can be at most 128 characters." },
    },
    display_name: {
      required: "Enter your name.",
      maxLength: { value: 100, message: "Names can be at most 100 characters." },
    },
    workspace_name: {
      required: "Enter a workspace name.",
      maxLength: { value: 100, message: "Workspace names can be at most 100 characters." },
    },
  };
  const activeFieldRules = isLogin
    ? { email: fieldRules.email, password: fieldRules.password }
    : isCreatingWorkspace
      ? fieldRules
      : {
          email: fieldRules.email,
          password: fieldRules.password,
          display_name: fieldRules.display_name,
        };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setFieldErrors({});
    setFieldIssues([]);
    const nextFieldErrors: Record<string, string> = {};
    const values: Record<string, string> = {
      email,
      password,
      display_name: displayName,
      workspace_name: workspaceName,
    };
    for (const [field, rule] of Object.entries(activeFieldRules)) {
      const message = validateReactField(values[field] ?? "", rule);
      if (message) nextFieldErrors[field] = message;
    }
    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors);
      setError("Complete the required fields and correct the highlighted values.");
      return;
    }
    setBusy(true);
    try {
      if (isLogin) {
        await onLogin(email.trim(), password);
      } else {
        await onRegister(
          displayName.trim(),
          email.trim(),
          password,
          isCreatingWorkspace ? workspaceName.trim() : undefined,
          inviteToken ?? undefined,
        );
      }
    } catch (reason) {
      setFieldErrors(getApiFieldErrors(reason));
      setFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setError(reason instanceof Error ? reason.message : "Could not authenticate.");
    } finally {
      setBusy(false);
    }
  }

  if (inviteError) {
    return (
      <section className="auth-panel panel" aria-labelledby="invite-error-title">
        <h1 id="invite-error-title">Invitation unavailable</h1>
        <p>{inviteError}</p>
        <a className="text-link" href="/">Return to sign in</a>
      </section>
    );
  }

  if (isInvitation && !inviteWorkspaceName) {
    return <section className="auth-panel panel"><p>Checking your invitation…</p></section>;
  }

  return (
    <section className="auth-panel panel">
      <div className="panel-heading">
        <div className="icon-tile" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none">
            <path d="M10 2.75 16 5v4.7c0 3.5-2.45 6.25-6 7.55-3.55-1.3-6-4.05-6-7.55V5l6-2.25Z" />
            <path d="m7.4 9.9 1.7 1.7 3.6-3.7" />
          </svg>
        </div>
        <div>
          <p className="auth-eyebrow">MCPKite</p>
          <h1>
            {isInvitation
              ? "Join your workspace"
              : isCreatingWorkspace
                ? "Create your workspace"
                : "Sign in"}
          </h1>
          <p>
            {isInvitation
              ? `Create an account to join ${inviteWorkspaceName}.`
              : isCreatingWorkspace
                ? "Set up the shared MCP server workspace."
                : "Sign in to manage your MCP servers."}
          </p>
        </div>
      </div>
      <form
        noValidate
        onSubmit={handleSubmit}
        onBlurCapture={(event) =>
          validateReactFieldOnBlur(event, activeFieldRules, (field, message) =>
            setFieldErrors((current) => ({ ...current, [field]: message })),
          )
        }
      >
        <RequiredFieldsNote />
        {!isLogin && (
          <>
            <FieldLabel htmlFor="account-display-name" required>Your name</FieldLabel>
            <input
              id="account-display-name"
              name="display_name"
              type="text"
              autoComplete="name"
              aria-invalid={Boolean(fieldErrors.display_name)}
              aria-describedby={fieldErrors.display_name ? "account-display-name-error" : undefined}
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value);
                setFieldErrors((current) => ({ ...current, display_name: "" }));
                setError("");
              }}
            />
            <FieldError id="account-display-name-error" message={fieldErrors.display_name} />
          </>
        )}
        <FieldLabel htmlFor="account-email" required>Email address</FieldLabel>
        <input
          id="account-email"
          name="email"
          type="text"
          inputMode="email"
          autoComplete="email"
          aria-invalid={Boolean(fieldErrors.email)}
          aria-describedby={fieldErrors.email ? "account-email-error" : undefined}
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setFieldErrors((current) => ({ ...current, email: "" }));
            setError("");
          }}
        />
        <FieldError id="account-email-error" message={fieldErrors.email} />

        <FieldLabel htmlFor="account-password" required>Password</FieldLabel>
        <input
          id="account-password"
          name="password"
          type="password"
          autoComplete={isLogin ? "current-password" : "new-password"}
          aria-invalid={Boolean(fieldErrors.password)}
          aria-describedby={fieldErrors.password ? "account-password-error" : undefined}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            setFieldErrors((current) => ({ ...current, password: "" }));
            setError("");
          }}
        />
        <FieldError id="account-password-error" message={fieldErrors.password} />

        {isCreatingWorkspace && (
          <>
            <FieldLabel htmlFor="workspace-name" required>Workspace name</FieldLabel>
            <input
              id="workspace-name"
              name="workspace_name"
              aria-invalid={Boolean(fieldErrors.workspace_name)}
              aria-describedby={fieldErrors.workspace_name ? "workspace-name-error" : undefined}
              value={workspaceName}
              onChange={(event) => {
                setWorkspaceName(event.target.value);
                setFieldErrors((current) => ({ ...current, workspace_name: "" }));
                setError("");
              }}
            />
            <FieldError id="workspace-name-error" message={fieldErrors.workspace_name} />
          </>
        )}

        <FormErrorSummary message={error} fieldIssues={fieldIssues} />
        <Button variant="primary" disabled={busy} type="submit">
          {busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
        </Button>
      </form>
      <p className="form-note">
        {isLogin
          ? "Workspace access is managed through one-time invitation links."
          : "Passwords must contain at least 12 characters."}
      </p>
      {isFirstAccount && (
        <p className="auth-mode-prompt">
          {isLogin ? "New to MCPKite?" : "Already have an account?"}{" "}
          <button
            className="auth-mode-switch"
            disabled={busy}
            onClick={() => {
              setError("");
              setFieldErrors({});
              setFieldIssues([]);
              setFirstRunMode(isLogin ? "create" : "login");
            }}
            type="button"
          >
            {isLogin ? "Create a workspace" : "Sign in"}
          </button>
        </p>
      )}
    </section>
  );
}
