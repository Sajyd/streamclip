import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const description =
  "STREAMCLIP analyse vos lives et prépare des clips verticaux sous-titrés, " +
  "prêts pour YouTube Shorts, TikTok et Instagram.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.PUBLIC_APP_URL ?? "http://localhost:3000"),
  title: { default: "STREAMCLIP — vos lives en clips verticaux", template: "%s · STREAMCLIP" },
  description,
  applicationName: "STREAMCLIP",
  openGraph: {
    type: "website",
    locale: "fr_FR",
    siteName: "STREAMCLIP",
    title: "STREAMCLIP — vos lives en clips verticaux",
    description,
  },
};

export const viewport: Viewport = {
  themeColor: "#05070c",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="fr"
      // Smooth scrolling is for in-page anchors, not for route changes.
      data-scroll-behavior="smooth"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
