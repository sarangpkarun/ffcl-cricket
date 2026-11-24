"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, CalendarDays, Home, MessageCircle, Table2, User } from "lucide-react";

const items = [
  { href: "/", label: "Home", Icon: Home },
  { href: "/fixtures", label: "Fixtures", Icon: CalendarDays },
  { href: "/standings", label: "Table", Icon: Table2 },
  { href: "/leaderboards", label: "Stats", Icon: BarChart3 },
  { href: "/chat", label: "Chat", Icon: MessageCircle },
  { href: "/profile", label: "Profile", Icon: User },
];

export function BottomNav() {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-10 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-4px_16px_rgba(5,46,22,0.06)] backdrop-blur">
      <ul className="mx-auto flex max-w-md px-1">
        {items.map(({ href, label, Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-16 flex-col items-center justify-center gap-0.5 text-[11px] transition-colors ${active ? "font-semibold text-primary" : "text-muted-foreground"}`}
              >
                <span className={`flex h-7 w-12 items-center justify-center rounded-full transition-colors ${active ? "bg-accent" : ""}`}>
                  <Icon size={20} strokeWidth={active ? 2.4 : 1.8} aria-hidden />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
