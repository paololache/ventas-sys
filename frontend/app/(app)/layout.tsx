"use client";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, clearToken, Me, token } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const params = useParams();
  const wid = params?.wid as string | undefined;
  const [me, setMe] = useState<Me | null>(null);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    api<Me>("/api/auth/me").then(setMe).catch(() => router.replace("/login"));
  }, [router]);

  const poll = useCallback(() => {
    if (wid) api<{ unread: number }>(`/api/w/${wid}/alerts`).then((r) => setUnread(r.unread)).catch(() => {});
  }, [wid]);
  useEffect(() => { poll(); const t = setInterval(poll, 60000); return () => clearInterval(t); }, [poll]);

  if (!me) return <p className="p-8 text-slate-500">Cargando…</p>;
  const tenant = me.tenants.find((t) => t.workspaces.some((w) => String(w.id) === wid));
  const nav = wid ? [
    ["", "Dashboard"], ["/pipeline", "Pipeline"], ["/alerts", "Alertas"], ["/directory", "Directorio"], ["/settings", "Configuración"],
  ] : [];

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-brand text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-2">
          <Link href="/" className="font-semibold">CRM</Link>
          <select
            className="rounded bg-white/10 px-2 py-1 text-sm text-white"
            value={wid || ""}
            onChange={(e) => e.target.value && router.push(`/w/${e.target.value}`)}
            aria-label="Empresa y espacio de trabajo"
          >
            {!wid && <option value="">Elegir espacio…</option>}
            {me.tenants.map((t) => (
              <optgroup key={t.id} label={t.name} className="text-slate-900">
                {t.workspaces.map((w) => <option key={w.id} value={w.id} className="text-slate-900">{t.name} · {w.name}</option>)}
              </optgroup>
            ))}
          </select>
          <nav className="flex flex-1 flex-wrap gap-1 text-sm">
            {nav.map(([p, l]) => {
              const href = `/w/${wid}${p}`;
              const active = p === "" ? path === href : path.startsWith(href);
              return <Link key={p} href={href} className={`rounded px-2.5 py-1 ${active ? "bg-white/20" : "hover:bg-white/10"}`}>{l}</Link>;
            })}
            {(me.is_superadmin || me.tenants.some((t) => t.role !== "member")) && (
              <Link href="/admin" className={`rounded px-2.5 py-1 ${path.startsWith("/admin") ? "bg-white/20" : "hover:bg-white/10"}`}>Empresas</Link>
            )}
          </nav>
          {wid && (
            <Link href={`/w/${wid}/alerts`} className="relative rounded px-2 py-1 hover:bg-white/10" aria-label="Alertas">
              🔔{unread > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-red-500 px-1.5 text-[10px] font-bold">{unread}</span>}
            </Link>
          )}
          <span className="hidden text-xs text-white/70 sm:inline">{me.email}{tenant ? ` · ${tenant.role}` : ""}</span>
          <button className="text-xs underline" onClick={() => { clearToken(); router.replace("/login"); }}>Salir</button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>
    </div>
  );
}
