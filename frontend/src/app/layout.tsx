import type { Metadata, Viewport } from "next";
import { connection } from "next/server";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Data Analyst",
  description: "Upload a CSV file and ask questions about it in plain English.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Render every page for each request, never ahead of time, so that it gets
  // the fresh nonce that src/proxy.ts puts in the Content-Security-Policy.
  // That includes the "page not found" page. (Next's page for a crash of this
  // layout itself is still built ahead of time; it shows no data.)
  await connection();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
