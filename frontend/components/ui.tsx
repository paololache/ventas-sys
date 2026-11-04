"use client";
import { ReactNode } from "react";

export const SEV_STYLE: Record<string, string> = {
  Alta: "bg-red-100 text-red-800", Media: "bg-orange-100 text-orange-800", Baja: "bg-slate-100 text-slate-600",
};
export const ALERTA_STYLE: Record<string, string> = {
  Vencida: "bg-red-100 text-red-800", "Sin acción": "bg-red-100 text-red-800", "Esta semana": "bg-amber-100 text-amber-800",
  "En tiempo": "bg-green-100 text-green-800", Cerrada: "bg-slate-100 text-slate-600",
  "Sin próximo paso (justificado)": "bg-slate-100 text-slate-600",
};

export function Badge({ children, cls }: { children: ReactNode; cls?: string }) {
  return <span className={`badge ${cls || "bg-slate-100 text-slate-700"}`}>{children}</span>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "red" }) {
  return (
    <div className="card">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone === "red" ? "text-red-700" : ""}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="label">{label}</span>{children}</label>;
}

export function Bar({ pct, color = "bg-brand" }: { pct: number; color?: string }) {
  return <div className="h-2 w-full rounded bg-slate-100"><div className={`h-2 rounded ${color}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
}

export function ErrorBox({ msg }: { msg: string }) {
  return msg ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{msg}</div> : null;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="card mt-10 w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2><button className="btn" onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  );
}
