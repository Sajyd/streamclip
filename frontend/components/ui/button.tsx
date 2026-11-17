import Link from "next/link";
import type { ComponentProps } from "react";

import { cx } from "@/lib/format";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-500 text-white shadow-lg shadow-brand-500/25 hover:bg-brand-400 active:bg-brand-600",
  secondary:
    "border border-white/10 bg-white/5 text-ink-100 hover:border-white/15 hover:bg-white/10",
  ghost: "text-ink-200 hover:bg-white/5 hover:text-white",
  danger: "border border-danger-500/50 bg-danger-500/10 text-danger-400 hover:bg-danger-500/20",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

export function buttonClasses({
  variant = "primary",
  size = "md",
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
} = {}): string {
  return cx(
    "inline-flex items-center justify-center gap-2 rounded-xl font-medium whitespace-nowrap",
    "transition-colors disabled:cursor-not-allowed disabled:opacity-60",
    VARIANTS[variant],
    SIZES[size],
    className,
  );
}

type ButtonLinkProps = ComponentProps<typeof Link> & { variant?: ButtonVariant; size?: ButtonSize };

export function ButtonLink({ variant, size, className, ...props }: ButtonLinkProps) {
  return <Link className={buttonClasses({ variant, size, className })} {...props} />;
}
