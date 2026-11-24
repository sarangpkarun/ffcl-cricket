import { Logo } from "@/components/Logo";
import { NotificationBell, NotificationToast } from "@/components/NotificationBell";

export function TopBar() {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-md items-center justify-between px-4 font-semibold">
        <span className="flex items-center gap-2"><Logo size={28} />FFCL</span>
        <NotificationBell />
      </div>
      <NotificationToast />
    </header>
  );
}
