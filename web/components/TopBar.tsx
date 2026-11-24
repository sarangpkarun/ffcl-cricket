import { Logo } from "@/components/Logo";
import { NotificationBell, NotificationToast } from "@/components/NotificationBell";

export function TopBar() {
  return (
    <header className="hero-gradient sticky top-0 z-10 pt-[env(safe-area-inset-top)] shadow-md">
      <div className="mx-auto flex h-14 max-w-md items-center justify-between px-4">
        <span className="flex items-center gap-2 text-lg font-bold tracking-wide"><Logo size={32} />FFCL</span>
        <NotificationBell />
      </div>
      <NotificationToast />
    </header>
  );
}
