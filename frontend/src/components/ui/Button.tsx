import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "text" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant: ButtonVariant;
};

export default function Button({ className, variant, ...buttonProps }: ButtonProps) {
  const classes = [`${variant}-button`, className].filter(Boolean).join(" ");

  return <button {...buttonProps} className={classes} />;
}
