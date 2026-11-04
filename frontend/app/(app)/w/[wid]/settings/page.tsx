"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ErrorBox, Field } from "@/components/ui";
import { api, download, fdate } from "@/lib/api";

type Tab = "reglas" | "catalogos" | "feriados" | "notificaciones" | "datos";

export default function Settings() {
  const { wid } = useParams();
  const [tab, setTab] = useState<Tab>("reglas");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b">
        {([["reglas", "Reglas de alerta"], ["catalogos", "Catálogos"], ["feriados", "Feriados"], ["notificaciones", "Notificaciones y Telegram"], ["datos", "Importar / Exportar"]] as [Tab, string][]).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-3 py-2 text-sm ${tab === k ? "border-b-2 border-brand font-semibold" : "text-slate-500"}`}>{l}</button>))}
      </div>
      {tab === "reglas" && <Rules wid={wid as string} />}
      {tab === "catalogos" && <Catalogs wid={wid as string} />}
      {tab === "feriados" && <Holidays wid={wid as string} />}
      {tab === "notificaciones" && <Notifications wid={wid as string} />}
      {tab === "datos" && <Data wid={wid as string} />}
    </div>
  );
}

function Rules({ wid }: { wid: string }) {
  const [rules, setRules] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const load = useCallback(() => { api(`/api/w/${wid}/rules`).then(setRules); }, [wid]);
  useEffect(() => { load(); }, [load]);
  async function patch(code: string, body: any) { try { setErr(""); await api(`/api/w/${wid}/rules/${code}`, { method: "PATCH", body }); load(); } catch (e: any) { setErr(e.message); } }
  return (
    <div className="space-y-2">
      <ErrorBox msg={err} />
      <p className="text-sm text-slate-500">Umbrales y severidades se guardan por espacio de trabajo. Los parámetros se editan como JSON.</p>
      {rules.map((r) => <RuleRow key={r.code} r={r} onPatch={patch} />)}
    </div>
  );
}
function RuleRow({ r, onPatch }: { r: any; onPatch: (c: string, b: any) => void }) {
  const [txt, setTxt] = useState(JSON.stringify(r.params, null, 1));
  const [bad, setBad] = useState(false);
  return (
    <div className="card grid gap-3 !p-3 md:grid-cols-[14rem_6rem_7rem_1fr_auto] md:items-start">
      <div><b>{r.code}</b> · {r.name}</div>
      <label className="text-sm"><input type="checkbox" checked={r.enabled} onChange={(e) => onPatch(r.code, { enabled: e.target.checked })} /> Activa</label>
      <select className="input" value={r.severity} onChange={(e) => onPatch(r.code, { severity: e.target.value })}>{["Alta", "Media", "Baja"].map((s) => <option key={s}>{s}</option>)}</select>
      <textarea className={`input font-mono text-xs ${bad ? "border-red-400" : ""}`} rows={Math.min(6, txt.split("\n").length)} value={txt} onChange={(e) => { setTxt(e.target.value); try { JSON.parse(e.target.value); setBad(false); } catch { setBad(true); } }} />
      <button className="btn" disabled={bad} onClick={() => onPatch(r.code, { params: JSON.parse(txt) })}>Guardar</button>
    </div>
  );
}

function Catalogs({ wid }: { wid: string }) {
  const [cats, setCats] = useState<any>({});
  const [nv, setNv] = useState<{ kind: string; value: string; prob: string }>({ kind: "stage", value: "", prob: "" });
  const [err, setErr] = useState("");
  const load = useCallback(() => { api(`/api/w/${wid}/catalogs`).then(setCats); }, [wid]);
  useEffect(() => { load(); }, [load]);
  const labels: Record<string, string> = { stage: "Etapas (con probabilidad)", tipo: "Tipo", prioridad: "Prioridad", sector: "Sector", marca: "Marca", tipo_accion: "Tipo de acción" };
  async function add(e: React.FormEvent) { e.preventDefault(); try { setErr(""); await api(`/api/w/${wid}/catalogs`, { body: { kind: nv.kind, value: nv.value, prob: nv.kind === "stage" ? Number(nv.prob || 0) / 100 : null } }); setNv({ ...nv, value: "", prob: "" }); load(); } catch (ex: any) { setErr(ex.message); } }
  return (
    <div className="space-y-3">
      <ErrorBox msg={err} />
      <form onSubmit={add} className="card flex flex-wrap items-end gap-2">
        <Field label="Lista"><select className="input" value={nv.kind} onChange={(e) => setNv({ ...nv, kind: e.target.value })}>{Object.entries(labels).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Valor"><input className="input" required value={nv.value} onChange={(e) => setNv({ ...nv, value: e.target.value })} /></Field>
        {nv.kind === "stage" && <Field label="Prob. %"><input className="input" type="number" min={0} max={100} value={nv.prob} onChange={(e) => setNv({ ...nv, prob: e.target.value })} /></Field>}
        <button className="btn btn-primary">Agregar</button>
      </form>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(labels).map(([k, l]) => (
          <div key={k} className="card !p-3"><h4 className="mb-1 text-sm font-semibold">{l}</h4>
            <ul className="text-sm">{(cats[k] || []).map((it: any) => (
              <li key={it.id} className="flex items-center gap-2 border-t py-1">
                <span className="flex-1">{it.value}{it.is_closed ? " 🔒" : ""}{it.is_paused ? " ⏸" : ""}</span>
                {k === "stage" && <input className="input !w-16 !py-0.5" type="number" min={0} max={100} defaultValue={Math.round((it.prob || 0) * 100)} onBlur={async (e) => { await api(`/api/w/${wid}/catalogs/${it.id}`, { method: "PATCH", body: { prob: Number(e.target.value) / 100 } }); }} aria-label={`Probabilidad ${it.value}`} />}
                <button className="text-xs text-red-700" onClick={async () => { if (confirm("¿Eliminar?")) { await api(`/api/w/${wid}/catalogs/${it.id}`, { method: "DELETE" }); load(); } }}>✕</button>
              </li>))}</ul></div>))}
      </div>
    </div>
  );
}

function Holidays({ wid }: { wid: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState({ fecha: "", nombre: "" });
  const [err, setErr] = useState("");
  const load = useCallback(() => { api(`/api/w/${wid}/holidays`).then(setRows); }, [wid]);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="space-y-3">
      <ErrorBox msg={err} />
      <p className="text-sm text-slate-500">Feriados de Perú precargados (2026-2027). Verifica el calendario oficial cada año; los días feriados no cuentan como hábiles ni se notifican (salvo urgentes del día).</p>
      <form className="card flex items-end gap-2" onSubmit={async (e) => { e.preventDefault(); try { setErr(""); await api(`/api/w/${wid}/holidays`, { body: f }); setF({ fecha: "", nombre: "" }); load(); } catch (ex: any) { setErr(ex.message); } }}>
        <Field label="Fecha"><input className="input" type="date" required value={f.fecha} onChange={(e) => setF({ ...f, fecha: e.target.value })} /></Field>
        <Field label="Nombre"><input className="input" value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} /></Field>
        <button className="btn btn-primary">Agregar</button>
      </form>
      <div className="card !p-3"><ul className="grid gap-x-6 text-sm sm:grid-cols-2 lg:grid-cols-3">{rows.map((h) => <li key={h.id} className="flex justify-between border-t py-1"><span>{fdate(h.fecha)} · {h.nombre}</span><button className="text-xs text-red-700" onClick={async () => { await api(`/api/w/${wid}/holidays/${h.id}`, { method: "DELETE" }); load(); }}>✕</button></li>)}</ul></div>
    </div>
  );
}

function Notifications({ wid }: { wid: string }) {
  const [st, setSt] = useState<any>(null);
  const [tg, setTg] = useState<any>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api(`/api/w/${wid}/settings`).then(setSt); api(`/api/w/${wid}/telegram/status`).then(setTg); }, [wid]);
  if (!st) return null;
  const set = (k: string, v: any) => setSt({ ...st, [k]: v });
  async function save() { try { setErr(""); await api(`/api/w/${wid}/settings`, { method: "PATCH", body: st }); setMsg("Guardado ✔"); } catch (e: any) { setErr(e.message); } }
  const days = ["L", "M", "X", "J", "V", "S", "D"];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="card space-y-3">
        <h3 className="font-semibold">Horario y frecuencia</h3>
        <ErrorBox msg={err} />{msg && <p className="text-sm text-green-700">{msg}</p>}
        <div className="flex gap-1">{days.map((d, i) => <button key={d} type="button" className={`btn !px-2.5 ${st.work_days.includes(i) ? "btn-primary" : ""}`} onClick={() => set("work_days", st.work_days.includes(i) ? st.work_days.filter((x: number) => x !== i) : [...st.work_days, i].sort())}>{d}</button>)}</div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Inicio (hora)"><input className="input" type="number" min={0} max={23} value={st.work_start} onChange={(e) => set("work_start", Number(e.target.value))} /></Field>
          <Field label="Fin (hora)"><input className="input" type="number" min={1} max={24} value={st.work_end} onChange={(e) => set("work_end", Number(e.target.value))} /></Field>
          <Field label="Resumen diario (Telegram)"><input className="input" value={st.digest_time} onChange={(e) => set("digest_time", e.target.value)} /></Field>
          <Field label="Resumen semanal (email, lunes)"><input className="input" value={st.weekly_time} onChange={(e) => set("weekly_time", e.target.value)} /></Field>
          <Field label="Repetir Alta cada (días)"><input className="input" type="number" min={1} value={st.repeat_alta_days} onChange={(e) => set("repeat_alta_days", Number(e.target.value))} /></Field>
          <Field label="Repetir Media cada (días)"><input className="input" type="number" min={1} value={st.repeat_media_days} onChange={(e) => set("repeat_media_days", Number(e.target.value))} /></Field>
          <Field label="Escalar a Alta tras (avisos)"><input className="input" type="number" min={1} value={st.escalate_after} onChange={(e) => set("escalate_after", Number(e.target.value))} /></Field>
          <Field label="Email del resumen semanal"><input className="input" type="email" value={st.email_to} onChange={(e) => set("email_to", e.target.value)} placeholder="(usa el de tu usuario)" /></Field>
        </div>
        <button className="btn btn-primary" onClick={save}>Guardar</button>
      </div>
      <div className="card space-y-3">
        <h3 className="font-semibold">Telegram</h3>
        {tg && !tg.bot_configured && <p className="rounded bg-amber-50 p-2 text-sm text-amber-800">El bot de la empresa aún no está configurado: un administrador debe pegar el token de BotFather en <b>Empresas → configuración</b>.</p>}
        {tg?.linked ? <p className="text-sm text-green-700">✔ Chat vinculado a este espacio de trabajo.</p> : <p className="text-sm text-slate-600">Sin chat vinculado.</p>}
        <button className="btn" onClick={async () => { const r = await api(`/api/w/${wid}/telegram/link-code`, { body: {} }); setCode(r.code); }}>Generar código de vinculación</button>
        {code && <p className="text-sm">Envía a tu bot: <code className="rounded bg-slate-100 px-1.5 py-0.5">/start {code}</code></p>}
        <p className="text-xs text-slate-500">Comandos: /hoy · /vencidas · /semana · /pipeline · /op OP-002 · /log OP-002 llamé a Miriam, presenta propuesta el 11/11</p>
      </div>
    </div>
  );
}

function Data({ wid }: { wid: string }) {
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState<any>(null);
  useEffect(() => { api(`/api/w/${wid}/quality-report`).then(setQ).catch(() => {}); }, [wid, res]);
  async function up(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { setErr(""); setRes(await api(`/api/w/${wid}/import/excel`, { body: fd })); } catch (ex: any) { setErr(ex.message); }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="card space-y-3">
        <h3 className="font-semibold">Importar desde Excel (idempotente)</h3>
        <p className="text-sm text-slate-500">Hojas Pipeline, Bitácora y Listas. Reimportar actualiza, no duplica.</p>
        <ErrorBox msg={err} />
        <input type="file" accept=".xlsx" onChange={up} />
        {res && <pre className="overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(res.result, null, 1)}</pre>}
        <button className="btn" onClick={() => download(`/api/w/${wid}/export/excel`, "pipeline.xlsx")}>⬇ Exportar a Excel</button>
      </div>
      {q && (
        <div className="card text-sm">
          <h3 className="mb-2 font-semibold">Calidad de datos</h3>
          <ul className="space-y-1">
            <li>Oportunidades activas: <b>{q.oportunidades_activas}</b> de {q.oportunidades_total}</li>
            <li>Sin próxima acción: <b>{q.sin_proxima_accion}</b></li><li>Sin fecha de cierre: <b>{q.sin_fecha_cierre}</b></li>
            <li>Sin contacto: <b>{q.sin_contacto}</b></li><li>Sin MEDDPICC: <b>{q.sin_meddpicc}</b></li>
            <li>Actividades con próximo paso sin fecha: <b>{q.actividades_proximo_paso_sin_fecha}</b></li>
          </ul>
        </div>
      )}
    </div>
  );
}
