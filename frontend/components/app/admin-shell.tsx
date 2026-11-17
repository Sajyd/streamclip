import type { ReactNode } from "react";

import { AdminNav } from "@/components/app/admin-nav";

export function AdminShell({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">
              Administration
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              {title}
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm text-ink-300">{description}</p>
          </div>
          {actions}
        </div>
        <AdminNav />
      </div>
      {children}
    </div>
  );
}
