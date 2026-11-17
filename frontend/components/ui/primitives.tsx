import { useId, type ComponentProps, type ReactNode } from "react";

import { cx } from "@/lib/format";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return <section className={cx("surface p-6 sm:p-7", className)} {...props} />;
}

export function CardTitle({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cx("text-base font-semibold tracking-tight text-white", className)} {...props} />;
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return <p className={cx("mt-1 text-sm leading-relaxed text-ink-300", className)} {...props} />;
}

type Tone = "neutral" | "brand" | "ok" | "warn" | "danger";

const BADGE_TONES: Record<Tone, string> = {
  neutral: "border-ink-600 bg-ink-800 text-ink-200",
  brand: "border-brand-500/40 bg-brand-500/15 text-brand-200",
  ok: "border-ok-500/40 bg-ok-500/10 text-ok-400",
  warn: "border-warn-400/40 bg-warn-400/10 text-warn-400",
  danger: "border-danger-500/40 bg-danger-500/10 text-danger-400",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        BADGE_TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

const NOTICE_TONES: Record<Tone, string> = {
  neutral: "border-ink-600 bg-ink-850 text-ink-200",
  brand: "border-brand-500/40 bg-brand-500/10 text-brand-200",
  ok: "border-ok-500/40 bg-ok-500/10 text-ok-400",
  warn: "border-warn-400/40 bg-warn-400/10 text-warn-400",
  danger: "border-danger-500/40 bg-danger-500/10 text-danger-400",
};

type NoticeProps = { tone?: Tone; title?: string; children: ReactNode; className?: string };

export function Notice({ tone = "neutral", title, children, className }: NoticeProps) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cx("rounded-2xl border px-4 py-3.5 text-sm", NOTICE_TONES[tone], className)}
    >
      {title ? <p className="font-semibold tracking-tight">{title}</p> : null}
      <div className={cx(title ? "mt-1" : null, "leading-relaxed text-ink-200")}>{children}</div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse rounded-lg bg-ink-800", className)} />;
}

export function Logo({ className }: { className?: string }) {
  // Unique per instance: the logo appears several times on a page.
  const gradientId = useId();
  return (
    <span className={cx("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      {/*
        viewBox keeps equal left/right padding around the phone mark
        (4 units each side). Play triangle is optically centered in the phone.
      */}
      <svg viewBox="0 0 24 32" aria-hidden className="h-7 w-[1.3125rem]">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0021f3" />
            <stop offset="1" stopColor="#0013de" />
          </linearGradient>
        </defs>
        <rect x="4" y="2" width="16" height="28" rx="5" fill={`url(#${gradientId})`} />
        <path d="M10 11.2v9.6l8.2-4.8z" fill="#010014" />
      </svg>
      <span className="text-white">STREAMCLIP</span>
    </span>
  );
}
