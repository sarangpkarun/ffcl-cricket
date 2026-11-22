"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useNotifications } from "@/lib/notifications";

export function NotificationBell() {
  const { me } = useAuth();
  const { unread, connected } = useNotifications();
  if (!me) return null;
  return (
    <Link href="/notifications" data-live={connected ? "true" : "false"} aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} className="relative px-2 text-xl">
      🔔
      {unread > 0 && (
        <span data-testid="unread-badge" className="absolute -right-1 -top-1 min-w-5 rounded-full bg-red-600 px-1 text-center text-[11px] leading-5 text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

/** A short-lived banner for the newest notification. */
export function NotificationToast() {
  const { toast, dismissToast, markRead } = useNotifications();
  const router = useRouter();
  if (!toast) return null;
  return (
    <div role="status" className="fixed inset-x-3 top-14 z-30 mx-auto max-w-md rounded-lg border bg-background p-3 shadow-lg">
      <div className="flex items-start gap-2">
        <button
          type="button"
          className="min-w-0 flex-1 text-left"
          onClick={() => {
            void markRead(toast.id);
            if (toast.data.link) router.push(toast.data.link);
            dismissToast();
          }}
        >
          <p className="text-sm font-medium">{toast.title}</p>
          {toast.body && <p className="truncate text-xs text-muted-foreground">{toast.body}</p>}
        </button>
        <button type="button" aria-label="Dismiss notification" className="text-sm" onClick={dismissToast}>✕</button>
      </div>
    </div>
  );
}
