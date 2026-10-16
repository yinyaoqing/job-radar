import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Job Radar：全遠端職缺雷達",
  description: "每天到公司 ATS 確認仍開放的全遠端職缺，依領域篩選，並判斷你所在的地區能否申請。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
