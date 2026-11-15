import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createSecret,
  deleteSecret,
  listSecretPage,
} from "../api/secrets";
import { updateProfile } from "../api/auth";
import {
  createInvite,
  getInvites,
  getMemberPage,
  getWorkspace,
  removeMember,
  revokeInvite,
} from "../api/workspace";
import { ApiError, getApiFieldErrors } from "../api/client";
import PaginationControls from "./PaginationControls";
import type {
  AuthUser,
  CreatedSecret,
  PageSize,
  Secret,
  SecretRegistryPage,
  Workspace,
  WorkspaceInvite,
  WorkspaceMember,
  WorkspaceMemberPage,
} from "../types/server";
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
import WorkspaceTabs from "./ui/WorkspaceTabs";
import WorkspaceConfigSettings from "./WorkspaceConfigSettings";

export type SettingsSection = "overview" | "values" | "secrets" | "members";

type WorkspaceSettingsProps = {
  user: AuthUser;
  onUserUpdated: (user: AuthUser) => void;
  section: SettingsSection;
  getSectionHref: (section: SettingsSection) => string;
  onSectionChange: (section: SettingsSection) => void;
  createdSecret: CreatedSecret | null;
  onCreatedSecretChange: (secret: CreatedSecret | null) => void;
  onSecretsUpdated: () => Promise<void>;
  onResumeServerSetup?: () => void;
};

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

export default function WorkspaceSettings({
  user,
  onUserUpdated,
  section,
  getSectionHref,
  onSectionChange,
  createdSecret,
  onCreatedSecretChange,
  onSecretsUpdated,
  onResumeServerSetup,
}: WorkspaceSettingsProps) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [invites, setInvites] = useState<WorkspaceInvite[]>([]);
  const [secretPageData, setSecretPageData] = useState<SecretRegistryPage | null>(null);
  const [memberPageData, setMemberPageData] = useState<WorkspaceMemberPage | null>(null);
  const [secretPage, setSecretPage] = useState(1);
  const [memberPage, setMemberPage] = useState(1);
  const [secretPageSize, setSecretPageSize] = useState<PageSize>(10);
  const [memberPageSize, setMemberPageSize] = useState<PageSize>(10);
  const [secretRefreshKey, setSecretRefreshKey] = useState(0);
  const [memberRefreshKey, setMemberRefreshKey] = useState(0);
  const [secretsLoading, setSecretsLoading] = useState(false);
  const [membersLoading, setMembersLoading] = useState(true);
  const [secretListError, setSecretListError] = useState("");
  const [memberListError, setMemberListError] = useState("");
  const [loading, setLoading] = useState(true);
  const [secretName, setSecretName] = useState("");
  const [displayName, setDisplayName] = useState(user.display_name);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileFieldErrors, setProfileFieldErrors] = useState<Record<string, string>>({});
  const [profileFieldIssues, setProfileFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [profileNotice, setProfileNotice] = useState("");
  const [secretError, setSecretError] = useState("");
  const [secretFieldErrors, setSecretFieldErrors] = useState<Record<string, string>>({});
  const [secretFieldIssues, setSecretFieldIssues] = useState<ApiError["fieldIssues"]>([]);
  const [inviteLink, setInviteLink] = useState("");
  const [confirmMemberId, setConfirmMemberId] = useState("");
  const [confirmSecretId, setConfirmSecretId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [copyFeedback, setCopyFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const secretsOnPage = secretPageData?.items ?? [];
  const membersOnPage = memberPageData?.items ?? [];
  const profileFieldRules: Record<string, ReactFieldRule> = {
    display_name: {
      required: "Enter your display name.",
      maxLength: { value: 100, message: "Display names can be at most 100 characters." },
    },
  };
  const secretFieldRules: Record<string, ReactFieldRule> = {
    name: {
      required: "Enter a token name.",
      maxLength: { value: 100, message: "Token names can be at most 100 characters." },
    },
  };

  useEffect(() => {
    setDisplayName(user.display_name);
  }, [user.display_name]);

  const loadWorkspace = useCallback(async () => {
    setError("");
    try {
      const results = await Promise.all([
        getWorkspace(),
        user.role === "owner" ? getInvites() : Promise.resolve([]),
      ]);
      setWorkspace(results[0]);
      setInvites(results[1]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load workspace settings.");
    } finally {
      setLoading(false);
    }
  }, [user.role]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (section !== "secrets") return;
    let active = true;
    setSecretsLoading(true);
    setSecretListError("");
    listSecretPage(secretPage, secretPageSize)
      .then((result) => {
        if (!active) return;
        setSecretPageData(result);
        if (result.page !== secretPage) setSecretPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setSecretListError(reason instanceof Error ? reason.message : "Could not load server tokens.");
        }
      })
      .finally(() => {
        if (active) setSecretsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [section, secretPage, secretPageSize, secretRefreshKey]);

  useEffect(() => {
    if (section !== "members") return;
    let active = true;
    setMembersLoading(true);
    setMemberListError("");
    getMemberPage(memberPage, memberPageSize)
      .then((result) => {
        if (!active) return;
        setMemberPageData(result);
        if (result.page !== memberPage) setMemberPage(result.page);
      })
      .catch((reason: unknown) => {
        if (active) {
          setMemberListError(reason instanceof Error ? reason.message : "Could not load members.");
        }
      })
      .finally(() => {
        if (active) setMembersLoading(false);
      });
    return () => {
      active = false;
    };
  }, [section, memberPage, memberPageSize, memberRefreshKey]);

  async function handleCreateSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSecretError("");
    setSecretFieldErrors({});
    setSecretFieldIssues([]);
    const secretNameError = validateReactField(secretName, secretFieldRules.name);
    if (secretNameError) {
      setSecretFieldErrors({ name: secretNameError });
      setSecretError("Complete the required fields and correct the highlighted values.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      onCreatedSecretChange(await createSecret(secretName));
      setSecretName("");
      setNotice("Server token created. Copy its value now; it cannot be shown again.");
      setSecretPage(1);
      setSecretRefreshKey((current) => current + 1);
      await onSecretsUpdated();
    } catch (reason) {
      setSecretFieldErrors(getApiFieldErrors(reason));
      setSecretFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setSecretError(reason instanceof Error ? reason.message : "Could not create server token.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateInvite() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const invite = await createInvite();
      setInviteLink(`${window.location.origin}/join/${invite.token}`);
      setNotice("Invitation created. Share this one-time link within seven days.");
      await loadWorkspace();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopyFeedback(`${label} copied.`);
    } catch {
      setCopyFeedback("Copy failed. Select the value and copy it manually.");
    }
  }

  async function handleDeleteSecret(secret: Secret) {
    setBusy(true);
    setError("");
    try {
      await deleteSecret(secret.id);
      setConfirmSecretId("");
      setNotice("Server token deleted.");
      setSecretRefreshKey((current) => current + 1);
      await onSecretsUpdated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete server token.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemoveMember(member: WorkspaceMember) {
    setBusy(true);
    setError("");
    try {
      await removeMember(member.user_id);
      setConfirmMemberId("");
      setNotice(`${member.email} was removed from the workspace.`);
      setMemberRefreshKey((current) => current + 1);
      await loadWorkspace();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove member.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRevokeInvite(inviteId: string) {
    setBusy(true);
    setError("");
    try {
      await revokeInvite(inviteId);
      setNotice("Invitation revoked.");
      await loadWorkspace();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not revoke invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileError("");
    setProfileFieldErrors({});
    setProfileFieldIssues([]);
    const normalizedName = displayName.trim();
    const displayNameError = validateReactField(
      displayName,
      profileFieldRules.display_name,
    );
    if (displayNameError) {
      setProfileError("Complete the required fields and correct the highlighted values.");
      setProfileFieldErrors({ display_name: displayNameError });
      setProfileNotice("");
      return;
    }

    setProfileSaving(true);
    setProfileError("");
    setProfileNotice("");
    try {
      const updatedUser = await updateProfile(normalizedName);
      onUserUpdated(updatedUser);
      setDisplayName(updatedUser.display_name);
      setProfileNotice("Your display name was updated.");
    } catch (reason) {
      setProfileFieldErrors(getApiFieldErrors(reason));
      setProfileFieldIssues(reason instanceof ApiError ? reason.fieldIssues : []);
      setProfileError(
        reason instanceof Error ? reason.message : "Could not update your display name.",
      );
    } finally {
      setProfileSaving(false);
    }
  }

  return (
    <div className="settings-stack">
      {error && <div className="message error-message" role="alert">{error}</div>}
      {notice && <div className="message success-message" role="status">{notice}</div>}
      {onResumeServerSetup && (
        <div className="message settings-resume-callout" role="note">
          <div>
            <strong>Finish your protected server setup</strong>
            <p>
              {createdSecret
                ? "Copy the new server token and confirm you’ve saved it before returning; the value cannot be shown again."
                : "Your server details are saved while you create a server token. Return to the form when you’re ready."}
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={createdSecret !== null}
            onClick={onResumeServerSetup}
            type="button"
          >
            Return to server setup
          </Button>
        </div>
      )}
      <WorkspaceTabs
        ariaLabel="Settings pages"
        activeValue={section}
        items={[
          { value: "overview", label: "Overview", href: getSectionHref("overview") },
          { value: "values", label: "Variables & secrets", href: getSectionHref("values") },
          { value: "secrets", label: "Server tokens", href: getSectionHref("secrets") },
          { value: "members", label: "Members", href: getSectionHref("members") },
        ]}
        onSelect={onSectionChange}
      />
      {createdSecret && section !== "secrets" && (
        <div className="message secret-pending-notice" role="status">
          <div>
            <strong>A new server token is ready to copy</strong>
            <p>Save it from Server tokens before refreshing or signing out; its value cannot be retrieved later.</p>
          </div>
          <Button
            variant="secondary"
            onClick={() => onSectionChange("secrets")}
            type="button"
          >
            Return to Server tokens
          </Button>
        </div>
      )}
      {section === "values" && <WorkspaceConfigSettings />}
      {loading ? (
        <section className="panel settings-panel"><p>Loading workspace settings…</p></section>
      ) : (
        <>
          {section === "overview" && (
          <section className="panel settings-panel">
            <div className="settings-heading">
              <div>
                <h2>Workspace</h2>
                <p>Shared MCP servers and credentials for this team.</p>
              </div>
              <span className="role-pill">{user.role === "owner" ? "Owner" : "Member"}</span>
            </div>
            <dl className="workspace-details">
              <div><dt>Name</dt><dd>{workspace?.name}</dd></div>
              <div><dt>Signed in as</dt><dd>{user.email}</dd></div>
            </dl>
          </section>
          )}
          {section === "overview" && (
            <section className="panel settings-panel">
              <div className="settings-heading">
                <div>
                  <h2>Your account</h2>
                  <p>Your name appears in the sidebar and account menu.</p>
                </div>
              </div>
              <form
                noValidate
                className="inline-create-form account-profile-form"
                onSubmit={(event) => void handleUpdateProfile(event)}
                onBlurCapture={(event) =>
                  validateReactFieldOnBlur(event, profileFieldRules, (field, message) =>
                    setProfileFieldErrors((current) => ({ ...current, [field]: message })),
                  )
                }
              >
                <div>
                  <RequiredFieldsNote />
                  <FieldLabel htmlFor="profile-display-name" required>
                    Display name
                  </FieldLabel>
                  <input
                    id="profile-display-name"
                    name="display_name"
                    autoComplete="name"
                    aria-invalid={Boolean(profileFieldErrors.display_name)}
                    aria-describedby={
                      profileFieldErrors.display_name ? "profile-display-name-error" : undefined
                    }
                    value={displayName}
                    onChange={(event) => {
                      setDisplayName(event.target.value);
                      setProfileError("");
                      setProfileFieldErrors((current) => ({ ...current, display_name: "" }));
                      setProfileNotice("");
                    }}
                  />
                  <FieldError
                    id="profile-display-name-error"
                    message={profileFieldErrors.display_name}
                  />
                  <FormErrorSummary
                    message={profileError}
                    fieldIssues={profileFieldIssues}
                  />
                </div>
                <Button
                  variant="secondary"
                  disabled={
                    profileSaving ||
                    !displayName.trim() ||
                    displayName.trim() === user.display_name
                  }
                  type="submit"
                >
                  {profileSaving ? "Saving…" : "Save name"}
                </Button>
              </form>
              {profileNotice && <div className="message success-message" role="status">{profileNotice}</div>}
            </section>
          )}

          {section === "secrets" && (
          <section className="panel settings-panel">
            <div className="settings-heading">
              <div>
                <h2>Server access tokens</h2>
                <p>One-time bearer credentials for protecting MCP endpoints.</p>
              </div>
            </div>
            <form
              noValidate
              className="inline-create-form"
              onSubmit={(event) => void handleCreateSecret(event)}
              onBlurCapture={(event) =>
                validateReactFieldOnBlur(event, secretFieldRules, (field, message) =>
                  setSecretFieldErrors((current) => ({ ...current, [field]: message })),
                )
              }
            >
              <div>
                <RequiredFieldsNote />
                <FieldLabel htmlFor="new-secret-name" required>
                  Token name
                </FieldLabel>
                <input
                  id="new-secret-name"
                  name="name"
                  aria-invalid={Boolean(secretFieldErrors.name)}
                  aria-describedby={secretFieldErrors.name ? "new-secret-name-error" : undefined}
                  value={secretName}
                  onChange={(event) => {
                    setSecretName(event.target.value);
                    setSecretError("");
                    setSecretFieldErrors((current) => ({ ...current, name: "" }));
                  }}
                  placeholder="e.g. Analytics client"
                />
                <FieldError id="new-secret-name-error" message={secretFieldErrors.name} />
                <FormErrorSummary
                  message={secretError}
                  fieldIssues={secretFieldIssues}
                />
              </div>
              <Button variant="secondary" disabled={busy || !secretName.trim()} type="submit">
                Create server token
              </Button>
            </form>

            {createdSecret && (
              <div className="one-time-secret" role="status">
                <div>
                  <strong>{createdSecret.name}</strong>
                  <p>Copy this token now. MCPKite will not be able to show it again.</p>
                  <p>Save it before leaving this page or refreshing.</p>
                </div>
                <code>{createdSecret.value}</code>
                <div className="one-time-actions">
                  <Button
                    variant="secondary"
                    onClick={() => void handleCopy(createdSecret.value, "Server token")}
                    type="button"
                  >
                    Copy server token
                  </Button>
                  <Button variant="text" onClick={() => onCreatedSecretChange(null)} type="button">
                    I’ve saved it
                  </Button>
                </div>
              </div>
            )}

            {secretListError && <div className="message error-message" role="alert">{secretListError}</div>}
            {secretsLoading && secretPageData === null ? (
              <p>Loading secrets…</p>
            ) : secretPageData === null ? null : secretPageData.total === 0 ? (
              <div className="settings-empty">No server tokens yet. Create one to protect an MCP endpoint.</div>
            ) : (
              <ul className="settings-list secret-list">
                {secretsOnPage.map((secret) => (
                  <li key={secret.id}>
                    <div className="settings-item-copy">
                      <strong>{secret.name}</strong>
                      <span>
                        {secret.server_name ? `Assigned to ${secret.server_name}` : "Not assigned"}
                      </span>
                    </div>
                    <div className="settings-item-actions">
                      {confirmSecretId === secret.id ? (
                        <>
                          <Button
                            variant="danger"
                            disabled={busy}
                            onClick={() => void handleDeleteSecret(secret)}
                            type="button"
                          >
                            Confirm delete
                          </Button>
                          <Button variant="text" onClick={() => setConfirmSecretId("")} type="button">
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="text"
                          disabled={busy || secret.server_id !== null}
                          onClick={() => setConfirmSecretId(secret.id)}
                          type="button"
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {secretPageData && secretPageData.total > 0 && (
              <PaginationControls
                page={secretPageData.page}
                pageSize={secretPageData.page_size}
                total={secretPageData.total}
                totalPages={secretPageData.total_pages}
                itemLabel="secrets"
                navigationLabel="Server token pagination"
                busy={secretsLoading || busy}
                onPageChange={setSecretPage}
                onPageSizeChange={(value) => {
                  setSecretPageSize(value);
                  setSecretPage(1);
                }}
              />
            )}
          </section>
          )}

          {section === "members" && (
          <section className="panel settings-panel">
            <div className="settings-heading">
              <div>
                <h2>Members</h2>
                <p>Everyone in this workspace can manage its servers, values, and server tokens.</p>
              </div>
              {user.role === "owner" && (
                <Button variant="secondary" disabled={busy} onClick={() => void handleCreateInvite()} type="button">
                  Create invite link
                </Button>
              )}
            </div>

            {inviteLink && (
              <div className="invite-link-box">
                <label htmlFor="invite-link">One-time invite link</label>
                <div className="copyable-value">
                  <input id="invite-link" readOnly value={inviteLink} />
                  <Button variant="secondary" onClick={() => void handleCopy(inviteLink, "Invite link")} type="button">
                    Copy link
                  </Button>
                </div>
              </div>
            )}

            {memberListError && <div className="message error-message" role="alert">{memberListError}</div>}
            {membersLoading && memberPageData === null ? (
              <p>Loading members…</p>
            ) : memberPageData === null ? null : memberPageData.total === 0 ? (
              <div className="settings-empty">No workspace members found.</div>
            ) : (
            <ul className="settings-list">
              {membersOnPage.map((member) => (
                <li key={member.user_id}>
                  <div className="settings-item-copy">
                    <strong>{member.email}</strong>
                    <span>{member.role === "owner" ? "Workspace owner" : `Joined ${formatDate(member.joined_at)}`}</span>
                  </div>
                  {user.role === "owner" && member.role !== "owner" && (
                    <div className="settings-item-actions">
                      {confirmMemberId === member.user_id ? (
                        <>
                          <Button variant="danger" disabled={busy} onClick={() => void handleRemoveMember(member)} type="button">
                            Confirm remove
                          </Button>
                          <Button variant="text" onClick={() => setConfirmMemberId("")} type="button">
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button variant="text" disabled={busy} onClick={() => setConfirmMemberId(member.user_id)} type="button">
                          Remove
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            )}
            {memberPageData && memberPageData.total > 0 && (
              <PaginationControls
                page={memberPageData.page}
                pageSize={memberPageData.page_size}
                total={memberPageData.total}
                totalPages={memberPageData.total_pages}
                itemLabel="members"
                navigationLabel="Members pagination"
                busy={membersLoading || busy}
                onPageChange={setMemberPage}
                onPageSizeChange={(value) => {
                  setMemberPageSize(value);
                  setMemberPage(1);
                }}
              />
            )}

            {user.role === "owner" && invites.length > 0 && (
              <div className="pending-invites">
                <h3>Pending invitations</h3>
                <ul className="settings-list">
                  {invites.map((invite) => (
                    <li key={invite.id}>
                      <div className="settings-item-copy">
                        <strong>Invitation link</strong>
                        <span>Expires {formatDate(invite.expires_at)}</span>
                      </div>
                      <Button variant="text" disabled={busy} onClick={() => void handleRevokeInvite(invite.id)} type="button">
                        Revoke
                      </Button>
                    </li>
                  ))}
                </ul>
                  {!inviteLink && (
                    <p className="form-note">
                      Invitation URLs are shown only when created. If a link is lost, revoke the pending invitation and create a replacement.
                    </p>
                  )}
              </div>
            )}
          </section>
          )}
        </>
      )}
      {copyFeedback && <p className="copy-feedback" role="status">{copyFeedback}</p>}
    </div>
  );
}
