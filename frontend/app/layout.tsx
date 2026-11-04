import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "CRM comercial proactivo", description: "Pipeline con alertas proactivas" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
