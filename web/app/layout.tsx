import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import { Geist } from "next/font/google";
import "./globals.css";
import { Chrome } from "@/components/Chrome";
import { InstallPrompt } from "@/components/InstallPrompt";
import { ServiceWorker } from "@/components/ServiceWorker";
import { AuthProvider } from "@/lib/auth";
import { NotificationsProvider } from "@/lib/notifications";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const viewport: Viewport = { themeColor: "#111111", width: "device-width", initialScale: 1 };

export const metadata: Metadata = {
  applicationName: "FFCL",
  appleWebApp: { capable: true, title: "FFCL", statusBarStyle: "default" },
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100"),
  title: { default: "FFCL digit cricket league", template: "%s · FFCL" },
  description: "Live scores, points table, fixtures and stats for the FFCL digit cricket league.",
  openGraph: { siteName: "FFCL", type: "website" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-foreground focus:px-3 focus:py-2 focus:text-background">Skip to main content</a>
        <AuthProvider>
          <NotificationsProvider>
          <Suspense fallback={<div className="h-12 border-b" />}>
            <Chrome>{children}</Chrome>
          </Suspense>
          <ServiceWorker />
          <InstallPrompt />
          </NotificationsProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
