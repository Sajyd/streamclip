"use client";

import { useEffect, useState } from "react";

import { markNotificationsReadAction } from "@/app/actions/account";
import { Form, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { cx, formatDateTime } from "@/lib/format";
import { fetchNotifications } from "@/lib/notifications-poll";
import type { Notification, NotificationList } from "@/types/api";

const SEVERITY_DOT: Record<Notification["severity"], string> = {
  info: "bg-brand-400",
  success: "bg-ok-400",
  warning: "bg-warn-400",
  error: "bg-danger-400",
};

type Props = {
  notifications: NotificationList;
  timeZone: string;
  pollMs?: number;
};

export function LiveNotifications({ notifications, timeZone, pollMs = 5000 }: Props) {
  const [current, setCurrent] = useState(notifications);

  useEffect(() => {
    setCurrent(notifications);
  }, [notifications]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      const next = await fetchNotifications(controller.signal);
      if (cancelled || !next) return;
      setCurrent(next);
    };
    const timer = window.setInterval(() => void tick(), pollMs);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pollMs]);

  return (
    <Card className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Activité</p>
          <CardTitle className="mt-2">Notifications</CardTitle>
          <CardDescription>
            {current.unread_count > 0
              ? `${current.unread_count} non lue${current.unread_count > 1 ? "s" : ""}`
              : "Vous êtes à jour."}
          </CardDescription>
        </div>
        {current.unread_count > 0 ? (
          <Form action={markNotificationsReadAction} className="space-y-0">
            <SubmitButton variant="ghost" size="sm">
              Tout marquer comme lu
            </SubmitButton>
          </Form>
        ) : null}
      </div>
      {current.items.length === 0 ? (
        <p className="mt-6 text-sm text-ink-400">Aucune notification pour le moment.</p>
      ) : (
        <ul className="mt-4 max-h-56 flex-1 divide-y divide-white/5 overflow-y-auto">
          {current.items.slice(0, 6).map((notification) => (
            <li key={notification.id} className="flex gap-3 py-3 first:pt-1">
              <span
                aria-hidden
                className={cx(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  notification.read_at ? "bg-ink-600" : SEVERITY_DOT[notification.severity],
                )}
              />
              <div className="min-w-0">
                <p
                  className={cx(
                    "text-sm",
                    notification.read_at ? "text-ink-200" : "font-medium text-white",
                  )}
                >
                  {notification.title}
                </p>
                <p className="mt-0.5 line-clamp-2 text-sm leading-relaxed text-ink-300">
                  {notification.body}
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  {formatDateTime(notification.created_at, timeZone)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
