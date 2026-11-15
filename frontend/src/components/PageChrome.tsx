import { useEffect, useId, useRef, useState } from "react";
import type { AuthUser } from "../types/server";
import Button from "./ui/Button";

type HeaderProps = {
  user?: AuthUser | null;
  onLogout?: () => void;
};

type AccountControlsProps = {
  user: AuthUser;
  onLogout?: () => void;
  className?: string;
};

export function AccountControls({ user, onLogout, className }: AccountControlsProps) {
  const classes = ["account-controls", className].filter(Boolean).join(" ");
  const [isOpen, setIsOpen] = useState(false);
  const menuId = useId();
  const initial = Array.from(user.display_name.trim())[0]?.toUpperCase() ?? "";
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    function handleOutsidePointerDown(event: PointerEvent) {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setIsOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", handleOutsidePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handleOutsidePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div
      ref={containerRef}
      className={classes}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget;
        if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
          setIsOpen(false);
        }
      }}
    >
      <button
        ref={triggerRef}
        className="account-menu-trigger"
        aria-expanded={isOpen}
        aria-controls={menuId}
        onClick={() => setIsOpen((open) => !open)}
        type="button"
      >
        <span className="account-avatar" aria-hidden="true">{initial}</span>
        <span className="account-name" title={user.display_name}>{user.display_name}</span>
        <svg className="account-menu-chevron" viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      <div
        id={menuId}
        className="account-menu"
        role="group"
        aria-label="Account actions"
        hidden={!isOpen}
      >
        <Button
          variant="text"
          className="account-menu-action"
          onClick={() => {
            setIsOpen(false);
            onLogout?.();
          }}
          type="button"
        >
          Sign out
        </Button>
      </div>
    </div>
  );
}

export function Header({ user, onLogout }: HeaderProps) {
  return (
    <header className="topbar">
      <a className="brand" href="/" aria-label="MCPKite home">
        <span className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span>MCP<span className="brand-muted">Kite</span></span>
      </a>
      {user ? (
        <AccountControls
          className="header-account-controls"
          user={user}
          onLogout={onLogout}
        />
      ) : (
        <div className="environment">
          <span className="environment-dot" />
          <span>Workspace console</span>
        </div>
      )}
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <span>© {new Date().getFullYear()} MCPkite</span>
    </footer>
  );
}
