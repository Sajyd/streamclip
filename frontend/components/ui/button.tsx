import type { ComponentProps } from "react";

import { cx } from "@/lib/format";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-b from-brand-400 to-brand-500 text-white shadow-[0_10px_28px_-10px_rgba(0,19,222,0.75)] hover:from-[#3358ff] hover:to-brand-400 active:from-brand-500 active:to-brand-600",
  secondary:
    "border border-white/12 bg-white/[0.04] text-white shadow-[0_8px_24px_-16px_rgba(0,0,0,0.8)] hover:border-white/20 hover:bg-white/[0.08]",
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

type ButtonLinkProps = ComponentProps<"a"> & { variant?: ButtonVariant; size?: ButtonSize };

export function ButtonLink({ variant, size, className, ...props }: ButtonLinkProps) {
  return <a className={buttonClasses({ variant, size, className })} {...props} />;
}
