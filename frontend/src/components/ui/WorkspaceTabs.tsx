import type { MouseEvent } from "react";

type WorkspaceTab<Value extends string> = {
  value: Value;
  label: string;
  href: string;
};

type WorkspaceTabsProps<Value extends string> = {
  ariaLabel: string;
  items: readonly WorkspaceTab<Value>[];
  activeValue: Value;
  onSelect: (value: Value) => void;
};

export default function WorkspaceTabs<Value extends string>({
  ariaLabel,
  items,
  activeValue,
  onSelect,
}: WorkspaceTabsProps<Value>) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>, value: Value) {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    onSelect(value);
  }

  return (
    <nav className="workspace-tabs" aria-label={ariaLabel}>
      <div className="workspace-tab-list">
        {items.map(({ value, label, href }) => (
          <a
            key={value}
            href={href}
            aria-current={activeValue === value ? "page" : undefined}
            className={`workspace-tab${activeValue === value ? " active" : ""}`}
            onClick={(event) => handleClick(event, value)}
          >
            {label}
          </a>
        ))}
      </div>
    </nav>
  );
}
