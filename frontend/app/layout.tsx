import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Health Insurance Plan Assistant",
  description: "Kota-inspired member support workspace for coverage lookup and claim drafting."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
