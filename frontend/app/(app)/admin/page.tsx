"use client";
import { useCallback, useEffect, useState } from "react";
import { ErrorBox, Field } from "@/components/ui";
import { api, Me } from "@/lib/api";

export default function Admin() {
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const load = useCallback(() => { api<Me>("/api/auth/me").then((m) => { setMe(m); setSel((s) => s ?? m.tenants[0]?.id ?? null); }); }, []);
  useEffect(() => { load(); }, [load]);
  const [nt, setNt] = useState({ name: "", slug: "", owner_email: "", owner_name: "", owner_password: "", workspace_name: "Principal", timezone: "America/Lima" });
  if (!me) return null;
  async function create(e: React.FormEvent) {
    e.preventDefault();
    try { setErr(""); const r = await api("/api/tenants", { body: { ...nt, slug: nt.slug || undefined } }); await load(); setSel(r.id); setNt({ ...nt, name: "", slug: "", owner_email: "", owner_password: "" }); } catch (ex: any) { setErr(ex.message); }
  }
  const tenant = me.tenants.find((t) => t.id === sel);
  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold">Empresas (tenants)</h1>
      <ErrorBox msg={err} />
      <div className="flex flex-wrap gap-2">{me.tenants.map((t) => <button key={t.id} className={`btn ${sel === t.id ? "btn-primary" : ""}`} onClick={() => setSel(t.id)}>{t.name}</button>)}</div>
      {tenant && <TenantPanel key={tenant.id} t={tenant} superadmin={me.is_superadmin} reload={load} />}
      {me.is_superadmin && (
        <form onSubmit={create} className="card grid gap-3 sm:grid-cols-2">
          <h3 className="font-semibold sm:col-span-2">Crear nueva empresa</h3>
          <Field label="Nombre"><input className="input" required value={nt.name} onChange={(e) => setNt({ ...nt, name: e.target.value })} /></Field>
          <Field label="Identificador (slug)"><input className="input" placeholder="auto" value={nt.slug} onChange={(e) => setNt({ ...nt, slug: e.target.value })} /></Field>
          <Field label="Correo del propietario"><input className="input" type="email" required value={nt.owner_email} onChange={(e) => setNt({ ...nt, owner_email: e.target.value })} /></Field>
          <Field label="Nombre del propietario"><input className="input" value={nt.owner_name} onChange={(e) => setNt({ ...nt, owner_name: e.target.value })} /></Field>
          <Field label="Contraseña inicial"><input className="input" type="password" required minLength={8} value={nt.owner_password} onChange={(e) => setNt({ ...nt, owner_password: e.target.value })} /></Field>
          <Field label="Primer espacio de trabajo"><input className="input" value={nt.workspace_name} onChange={(e) => setNt({ ...nt, workspace_name: e.target.value })} /></Field>
          <div className="sm:col-span-2"><button className="btn btn-primary">Crear empresa</button></div>
        </form>)}
    </div>
  );
}

function TenantPanel({ t, superadmin, reload }: { t: Me["tenants"][0]; superadmin: boolean; reload: () => void }) {
  const [cfg, setCfg] = useState<any>(null);
  const [members, setMembers] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [ws, setWs] = useState("");
  const [m, setM] = useState({ email: "", name: "", password: "", role: "member", workspace_ids: [] as number[] });
  const admin = t.role !== "member";
  const load = useCallback(() => {
    if (!admin) return;
    api(`/api/tenants/${t.id}`).then(setCfg); api(`/api/tenants/${t.id}/members`).then(setMembers);
  }, [t.id, admin]);
  useEffect(() => { load(); }, [load]);
  if (!admin) return <p className="text-sm text-slate-500">No tienes permisos de administración en esta empresa.</p>;
  if (!cfg) return null;
  const set = (k: string, v: any) => setCfg({ ...cfg, [k]: v });
  async function saveCfg() {
    const body: any = { name: cfg.name, timezone: cfg.timezone, smtp_host: cfg.smtp_host, smtp_port: Number(cfg.smtp_port), smtp_user: cfg.smtp_user, smtp_from: cfg.smtp_from };
    if (cfg.new_token) body.telegram_bot_token = cfg.new_token;
    if (cfg.new_smtp_password) body.smtp_password = cfg.new_smtp_password;
    try { setErr(""); await api(`/api/tenants/${t.id}`, { method: "PATCH", body }); setMsg("Guardado ✔"); load(); reload(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="card space-y-3">
        <h3 className="font-semibold">{t.name} · configuración</h3>
        <ErrorBox msg={err} />{msg && <p className="text-sm text-green-700">{msg}</p>}
        <Field label="Nombre"><input className="input" value={cfg.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Zona horaria"><input className="input" value={cfg.timezone} onChange={(e) => set("timezone", e.target.value)} /></Field>
        <h4 className="pt-2 text-sm font-semibold">Bot de Telegram {cfg.telegram_configured ? "✔" : "(sin configurar)"}</h4>
        <Field label="Token de BotFather (se guarda en el servidor; no se vuelve a mostrar)"><input className="input" type="password" placeholder="123456:ABC…" onChange={(e) => set("new_token", e.target.value)} /></Field>
        <button className="btn" onClick={async () => { try { setErr(""); const r = await api(`/api/tenants/${t.id}/telegram/webhook`, { body: {} }); setMsg("Webhook registrado: " + r.webhook); } catch (e: any) { setErr(e.message); } }}>Registrar webhook</button>
        <h4 className="pt-2 text-sm font-semibold">SMTP (Gmail con contraseña de aplicación)</h4>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Host"><input className="input" value={cfg.smtp_host} placeholder="smtp.gmail.com" onChange={(e) => set("smtp_host", e.target.value)} /></Field>
          <Field label="Puerto"><input className="input" type="number" value={cfg.smtp_port} onChange={(e) => set("smtp_port", e.target.value)} /></Field>
          <Field label="Usuario"><input className="input" value={cfg.smtp_user} onChange={(e) => set("smtp_user", e.target.value)} /></Field>
          <Field label={`Contraseña ${cfg.smtp_password_set ? "(guardada)" : ""}`}><input className="input" type="password" onChange={(e) => set("new_smtp_password", e.target.value)} /></Field>
          <Field label="Remitente"><input className="input" value={cfg.smtp_from} onChange={(e) => set("smtp_from", e.target.value)} /></Field>
        </div>
        <button className="btn btn-primary" onClick={saveCfg}>Guardar</button>
      </div>
      <div className="space-y-4">
        <div className="card space-y-2">
          <h3 className="font-semibold">Espacios de trabajo</h3>
          <ul className="text-sm">{t.workspaces.map((w) => <li key={w.id} className="border-t py-1"><a className="text-brand underline" href={`/w/${w.id}`}>{w.name}</a></li>)}</ul>
          <div className="flex gap-2"><input className="input" placeholder="Nuevo espacio (equipo, línea de negocio…)" value={ws} onChange={(e) => setWs(e.target.value)} />
            <button className="btn btn-primary" onClick={async () => { try { setErr(""); await api(`/api/tenants/${t.id}/workspaces`, { body: { name: ws } }); setWs(""); reload(); } catch (e: any) { setErr(e.message); } }}>Crear</button></div>
        </div>
        <div className="card space-y-2">
          <h3 className="font-semibold">Usuarios</h3>
          <ul className="text-sm">{members.map((x) => <li key={x.user_id} className="border-t py-1">{x.email} · <b>{x.role}</b>{x.role === "member" ? ` · espacios: ${x.workspace_ids.join(", ") || "—"}` : " · todos"}</li>)}</ul>
          <div className="grid grid-cols-2 gap-2">
            <input className="input" placeholder="correo" value={m.email} onChange={(e) => setM({ ...m, email: e.target.value })} />
            <input className="input" type="password" placeholder="contraseña (si es nuevo)" value={m.password} onChange={(e) => setM({ ...m, password: e.target.value })} />
            <select className="input" value={m.role} onChange={(e) => setM({ ...m, role: e.target.value })}><option value="member">Vendedor (member)</option><option value="admin">Admin</option><option value="owner">Propietario</option></select>
            <div className="flex flex-wrap gap-2 text-xs">{t.workspaces.map((w) => <label key={w.id}><input type="checkbox" checked={m.workspace_ids.includes(w.id)} onChange={(e) => setM({ ...m, workspace_ids: e.target.checked ? [...m.workspace_ids, w.id] : m.workspace_ids.filter((i) => i !== w.id) })} /> {w.name}</label>)}</div>
          </div>
          <button className="btn btn-primary" onClick={async () => { try { setErr(""); await api(`/api/tenants/${t.id}/members`, { body: m }); setM({ ...m, email: "", password: "" }); load(); } catch (e: any) { setErr(e.message); } }}>Agregar / actualizar usuario</button>
        </div>
      </div>
    </div>
  );
}
