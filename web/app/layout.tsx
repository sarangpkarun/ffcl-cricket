import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Chrome } from "@/components/Chrome";
import { AuthProvider } from "@/lib/auth";
import { NotificationsProvider } from "@/lib/notifications";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100"),
  title: { default: "FFCL digit cricket league", template: "%s · FFCL" },
  description: "Live scores, points table, fixtures and stats for the FFCL digit cricket league.",
  openGraph: { siteName: "FFCL", type: "website" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AuthProvider>
          <NotificationsProvider>
          <Suspense fallback={<div className="h-12 border-b" />}>
            <Chrome>{children}</Chrome>
          </Suspense>
          </NotificationsProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
