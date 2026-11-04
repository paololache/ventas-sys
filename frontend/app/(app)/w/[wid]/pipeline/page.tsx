"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { ALERTA_STYLE, Badge, ErrorBox, Field, Modal } from "@/components/ui";
import { api, fdate, Opp, usd } from "@/lib/api";

const PRIO_DOT: Record<string, string> = { Alta: "bg-red-500", Media: "bg-amber-400", Baja: "bg-slate-300" };

export default function Pipeline() {
  const { wid } = useParams();
  const [opps, setOpps] = useState<Opp[]>([]);
  const [cats, setCats] = useState<any>({});
  const [view, setView] = useState<"kanban" | "tabla">("kanban");
  const [f, setF] = useState({ partner: "", marca: "", sector: "", prioridad: "", alerta: "", q: "" });
  const [err, setErr] = useState("");
  const [creating, setCreating] = useState(false);
  const [drag, setDrag] = useState<number | null>(null);

  const load = useCallback(() => { api<Opp[]>(`/api/w/${wid}/opportunities`).then(setOpps); }, [wid]);
  useEffect(() => { load(); api(`/api/w/${wid}/catalogs`).then(setCats); }, [wid, load]);

  const rows = useMemo(() => opps.filter((o) =>
    (!f.partner || o.partner === f.partner) && (!f.marca || o.marca === f.marca) && (!f.sector || o.sector === f.sector) &&
    (!f.prioridad || o.prioridad === f.prioridad) && (!f.alerta || o.alerta === f.alerta) &&
    (!f.q || `${o.code} ${o.client} ${o.descripcion} ${o.partner}`.toLowerCase().includes(f.q.toLowerCase()))), [opps, f]);
  const partners = useMemo(() => Array.from(new Set(opps.map((o) => o.partner).filter(Boolean))), [opps]);
  const stages: string[] = (cats.stage || []).map((s: any) => s.value);

  async function move(id: number, stage: string) {
    setErr("");
    const prev = opps;
    setOpps(opps.map((o) => (o.id === id ? { ...o, stage } : o)));
    try { await api(`/api/w/${wid}/opportunities/${id}`, { method: "PATCH", body: { stage } }); load(); }
    catch (e: any) { setErr(e.message); setOpps(prev); }
  }

  const sel = (k: keyof typeof f, label: string, options: string[]) => (
    <select className="input !w-auto" aria-label={label} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
      <option value="">{label}</option>{options.map((o) => <option key={o}>{o}</option>)}
    </select>
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input !w-56" placeholder="Buscar…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        {sel("partner", "Partner", partners)}
        {sel("marca", "Marca", (cats.marca || []).map((x: any) => x.value))}
        {sel("sector", "Sector", (cats.sector || []).map((x: any) => x.value))}
        {sel("prioridad", "Prioridad", ["Alta", "Media", "Baja"])}
        {sel("alerta", "Alerta", ["Vencida", "Sin acción", "Esta semana", "En tiempo", "Cerrada"])}
        <div className="ml-auto flex gap-2">
          <div className="inline-flex overflow-hidden rounded-md border border-slate-300">
            {(["kanban", "tabla"] as const).map((v) => <button key={v} className={`px-3 py-1.5 text-sm ${view === v ? "bg-brand text-white" : "bg-white"}`} onClick={() => setView(v)}>{v === "kanban" ? "Kanban" : "Tabla"}</button>)}
          </div>
          <button className="btn btn-primary" onClick={() => setCreating(true)}>+ Oportunidad</button>
        </div>
      </div>
      <ErrorBox msg={err} />

      {view === "kanban" ? (
        <div className="flex gap-3 overflow-x-auto pb-3">
          {stages.map((st) => {
            const col = rows.filter((o) => o.stage === st);
            return (
              <div key={st} className="w-72 shrink-0 rounded-lg bg-slate-100 p-2"
                onDragOver={(e) => e.preventDefault()} onDrop={() => { if (drag != null) { move(drag, st); setDrag(null); } }}>
                <div className="mb-2 flex items-center justify-between px-1 text-sm font-semibold"><span>{st}</span><span className="text-xs font-normal text-slate-500">{col.length} · {usd(col.reduce((a, o) => a + o.monto, 0))}</span></div>
                <div className="space-y-2">
                  {col.map((o) => (
                    <Link key={o.id} href={`/w/${wid}/opportunities/${o.id}`} draggable onDragStart={() => setDrag(o.id)}
                      className="card block cursor-grab !p-3 hover:border-brand">
                      <div className="flex items-center justify-between text-xs text-slate-500"><span><span className={`mr-1 inline-block h-2 w-2 rounded-full ${PRIO_DOT[o.prioridad]}`} />{o.code} · {o.tipo}</span><Badge cls={ALERTA_STYLE[o.alerta]}>{o.alerta}</Badge></div>
                      <div className="mt-1 text-sm font-medium">{o.client || "Sin cliente"}</div>
                      <div className="truncate text-xs text-slate-500">{o.descripcion}</div>
                      <div className="mt-1 flex justify-between text-xs"><span>{usd(o.monto)}</span><span className="text-slate-500">{o.partner}</span></div>
                      <div className="mt-1 truncate text-xs text-slate-600">▶ {o.prox_accion ? `${o.prox_accion} (${fdate(o.fecha_prox_accion)})` : <span className="text-red-700">sin próxima acción</span>}</div>
                    </Link>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="card overflow-x-auto !p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500"><tr>
              {["ID", "Cliente", "Oportunidad", "Partner", "Marca", "Etapa", "Monto", "Pond.", "Prio", "Cierre", "Próxima acción", "Fecha", "Alerta", "Actualiz."].map((h) => <th key={h} className="px-2 py-2">{h}</th>)}
            </tr></thead>
            <tbody>{rows.map((o) => (
              <tr key={o.id} className="border-t hover:bg-slate-50">
                <td className="px-2 py-1.5"><Link className="font-medium text-brand underline" href={`/w/${wid}/opportunities/${o.id}`}>{o.code}</Link></td>
                <td className="px-2">{o.client}</td><td className="max-w-[16rem] truncate px-2">{o.descripcion}</td><td className="px-2">{o.partner}</td><td className="px-2">{o.marca}</td>
                <td className="px-2">{o.stage}</td><td className="px-2 text-right">{usd(o.monto)}</td><td className="px-2 text-right">{usd(o.monto_ponderado)}</td>
                <td className="px-2">{o.prioridad}</td><td className="px-2">{fdate(o.fecha_cierre_est)}</td><td className="max-w-[14rem] truncate px-2">{o.prox_accion}</td>
                <td className="px-2">{fdate(o.fecha_prox_accion)}</td><td className="px-2"><Badge cls={ALERTA_STYLE[o.alerta]}>{o.alerta}</Badge></td><td className="px-2">{fdate(o.ultima_actualizacion)}</td>
              </tr>))}</tbody>
          </table>
          {rows.length === 0 && <p className="p-4 text-sm text-slate-500">Sin resultados.</p>}
        </div>
      )}
      {creating && <NewOpp wid={wid as string} cats={cats} onClose={() => setCreating(false)} onDone={() => { setCreating(false); load(); }} />}
    </div>
  );
}

function NewOpp({ wid, cats, onClose, onDone }: { wid: string; cats: any; onClose: () => void; onDone: () => void }) {
  const [clients, setClients] = useState<any[]>([]);
  const [partners, setPartners] = useState<any[]>([]);
  const [v, setV] = useState<any>({ tipo: "DR", stage: "Prospección", prioridad: "Media", monto: 0, descripcion: "", client_id: "", partner_id: "", marca: "" });
  const [err, setErr] = useState("");
  useEffect(() => { api(`/api/w/${wid}/clients`).then(setClients); api(`/api/w/${wid}/partners`).then(setPartners); }, [wid]);
  const set = (k: string, val: any) => setV({ ...v, [k]: val });
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = { ...v, monto: Number(v.monto) || 0, client_id: v.client_id ? Number(v.client_id) : null, partner_id: v.partner_id ? Number(v.partner_id) : null, fecha_cierre_est: v.fecha_cierre_est || null, fecha_prox_accion: v.fecha_prox_accion || null };
    try { await api(`/api/w/${wid}/opportunities`, { body }); onDone(); } catch (ex: any) { setErr(ex.message); }
  }
  const opts = (k: string) => (cats[k] || []).map((x: any) => <option key={x.id}>{x.value}</option>);
  return (
    <Modal title="Nueva oportunidad" onClose={onClose}>
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><ErrorBox msg={err} /></div>
        <Field label="Descripción"><input className="input" required value={v.descripcion} onChange={(e) => set("descripcion", e.target.value)} /></Field>
        <Field label="Monto (USD)"><input className="input" type="number" min={0} value={v.monto} onChange={(e) => set("monto", e.target.value)} /></Field>
        <Field label="Cliente final"><select className="input" value={v.client_id} onChange={(e) => set("client_id", e.target.value)}><option value="">—</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Partner"><select className="input" value={v.partner_id} onChange={(e) => set("partner_id", e.target.value)}><option value="">—</option>{partners.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
        <Field label="Tipo"><select className="input" value={v.tipo} onChange={(e) => set("tipo", e.target.value)}>{opts("tipo")}</select></Field>
        <Field label="Etapa"><select className="input" value={v.stage} onChange={(e) => set("stage", e.target.value)}>{opts("stage")}</select></Field>
        <Field label="Prioridad"><select className="input" value={v.prioridad} onChange={(e) => set("prioridad", e.target.value)}>{opts("prioridad")}</select></Field>
        <Field label="Marca"><select className="input" value={v.marca} onChange={(e) => set("marca", e.target.value)}><option value="">—</option>{opts("marca")}</select></Field>
        <Field label="Fecha de cierre estimada"><input className="input" type="date" onChange={(e) => set("fecha_cierre_est", e.target.value)} /></Field>
        <div />
        <Field label="Próxima acción"><input className="input" onChange={(e) => set("prox_accion", e.target.value)} /></Field>
        <Field label="Fecha próxima acción"><input className="input" type="date" onChange={(e) => set("fecha_prox_accion", e.target.value)} /></Field>
        <p className="text-xs text-slate-500 sm:col-span-2">Si no defines próxima acción con fecha, el sistema te lo recordará (regla R3).</p>
        <div className="sm:col-span-2"><button className="btn btn-primary">Crear</button></div>
      </form>
    </Modal>
  );
}
