"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ALERTA_STYLE, Badge, ErrorBox, Field, SEV_STYLE } from "@/components/ui";
import { api, fdate, usd } from "@/lib/api";

export default function OppPage() {
  const { wid, id } = useParams();
  const base = `/api/w/${wid}/opportunities/${id}`;
  const [o, setO] = useState<any>(null);
  const [cats, setCats] = useState<any>({});
  const [tab, setTab] = useState<"timeline" | "meddpicc" | "datos">("timeline");
  const load = useCallback(() => { api(base).then(setO); }, [base]);
  useEffect(() => { load(); api(`/api/w/${wid}/catalogs`).then(setCats); }, [load, wid]);
  if (!o) return <p className="text-slate-500">Cargando…</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={`/w/${wid}/pipeline`} className="text-sm text-brand underline">← Pipeline</Link>
        <h1 className="text-xl font-semibold">{o.code} · {o.client || "Sin cliente"}</h1>
        <Badge cls={ALERTA_STYLE[o.alerta]}>{o.alerta}</Badge>
        <span className="text-sm text-slate-500">{o.stage} · {usd(o.monto)} · ponderado {usd(o.monto_ponderado)}</span>
      </div>
      <p className="text-slate-600">{o.descripcion}</p>

      {o.alerts.length > 0 && (
        <div className="card border-orange-200 bg-orange-50 !p-3">
          <b className="text-sm">Alertas abiertas</b>
          <ul className="mt-1 space-y-1 text-sm">{o.alerts.map((a: any) => <li key={a.id}><Badge cls={SEV_STYLE[a.severity]}>{a.severity}</Badge> {a.title} <span className="text-slate-500">— {a.detail}</span></li>)}</ul>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-1">
          <NextAction o={o} base={base} onSaved={load} />
          <div className="card text-sm">
            <h3 className="mb-2 font-semibold">Resumen</h3>
            <dl className="grid grid-cols-2 gap-x-2 gap-y-1">
              {[["Partner", o.partner], ["Marca", o.marca], ["Tipo", o.tipo], ["Prioridad", o.prioridad], ["Cierre estimado", fdate(o.fecha_cierre_est)], ["Responsable", o.responsable || "—"],
                ["Última actualización", fdate(o.ultima_actualizacion)], ["En etapa desde", fdate(o.stage_entered_on)], ["MEDDPICC", `${o.meddpicc_score}/16`],
                ["Vence DR", fdate(o.dr_vencimiento)], ["Vence contrato", fdate(o.contrato_vencimiento)], ["Proceso SEACE", o.seace_proceso || "—"], ["Competidor", o.competidor || "—"]].map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd>{v}</dd></div>))}
            </dl>
          </div>
          <div className="card text-sm">
            <h3 className="mb-2 font-semibold">Historial de etapas</h3>
            <ol className="space-y-1">{o.stage_history.map((h: any, i: number) => <li key={i}>{fdate(h.on)} — {h.from ? `${h.from} → ` : ""}<b>{h.to}</b></li>)}</ol>
          </div>
        </div>

        <div className="space-y-3 lg:col-span-2">
          <div className="flex gap-1 border-b">
            {([["timeline", "Actividades"], ["meddpicc", "MEDDPICC"], ["datos", "Editar datos"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={`px-3 py-2 text-sm ${tab === k ? "border-b-2 border-brand font-semibold" : "text-slate-500"}`}>{l}</button>))}
          </div>
          {tab === "timeline" && <Timeline o={o} base={base} cats={cats} onSaved={load} />}
          {tab === "meddpicc" && <Meddpicc o={o} base={base} onSaved={load} />}
          {tab === "datos" && <EditData o={o} base={base} cats={cats} onSaved={load} />}
        </div>
      </div>
    </div>
  );
}

function NextAction({ o, base, onSaved }: { o: any; base: string; onSaved: () => void }) {
  const [a, setA] = useState(o.prox_accion || "");
  const [d, setD] = useState(o.fecha_prox_accion || "");
  const [err, setErr] = useState("");
  const vencida = o.fecha_prox_accion && o.dias_para_accion < 0;
  async function save() {
    try { setErr(""); await api(base, { method: "PATCH", body: { prox_accion: a, fecha_prox_accion: d || null } }); onSaved(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className={`card ${!o.prox_accion || !o.fecha_prox_accion ? "border-red-300 bg-red-50" : vencida ? "border-red-300" : ""}`}>
      <h3 className="mb-2 font-semibold">Próxima acción</h3>
      {(!o.prox_accion || !o.fecha_prox_accion) && !o.sin_proximo_paso_motivo && !o.is_closed && <p className="mb-2 text-sm font-medium text-red-700">⚠ Define una próxima acción con fecha.</p>}
      {o.sin_proximo_paso_motivo && <p className="mb-2 text-sm text-slate-600">Sin próximo paso: {o.sin_proximo_paso_motivo}</p>}
      <ErrorBox msg={err} />
      <div className="space-y-2">
        <input className="input" placeholder="Qué haré…" value={a} onChange={(e) => setA(e.target.value)} />
        <input className="input" type="date" value={d} onChange={(e) => setD(e.target.value)} />
        <button className="btn btn-primary" onClick={save}>Guardar</button>
      </div>
    </div>
  );
}

function Timeline({ o, base, cats, onSaved }: { o: any; base: string; cats: any; onSaved: () => void }) {
  const [v, setV] = useState<any>({ tipo: "Llamada", resumen: "", contacto: "", proximo_paso: "", fecha_proximo_paso: "", sin: false, motivo: "" });
  const [err, setErr] = useState("");
  const [sugs, setSugs] = useState<{ fecha: string; texto: string }[]>([]);
  const set = (k: string, val: any) => setV({ ...v, [k]: val });

  // detección de fechas en texto libre: sólo PROPONE
  useEffect(() => {
    const t = setTimeout(() => {
      const wid = base.split("/")[3];
      if (v.resumen.length > 4) api(`/api/w/${wid}/suggest-dates`, { body: { text: v.resumen } }).then(setSugs).catch(() => {});
      else setSugs([]);
    }, 400);
    return () => clearTimeout(t);
  }, [v.resumen, base]);

  async function save(e: React.FormEvent) {
    e.preventDefault(); setErr("");
    try {
      await api(`${base}/activities`, { body: { tipo: v.tipo, resumen: v.resumen, contacto: v.contacto, proximo_paso: v.sin ? "" : v.proximo_paso, fecha_proximo_paso: v.sin ? null : v.fecha_proximo_paso || null, sin_proximo_paso_motivo: v.sin ? v.motivo : "" } });
      setV({ ...v, resumen: "", contacto: "", proximo_paso: "", fecha_proximo_paso: "", sin: false, motivo: "" }); setSugs([]); onSaved();
    } catch (ex: any) { setErr(ex.message); }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={save} className="card space-y-3">
        <h3 className="font-semibold">Registrar actividad</h3>
        <ErrorBox msg={err} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Tipo"><select className="input" value={v.tipo} onChange={(e) => set("tipo", e.target.value)}>{(cats.tipo_accion || []).map((t: any) => <option key={t.id}>{t.value}</option>)}</select></Field>
          <Field label="Contacto"><input className="input" value={v.contacto} onChange={(e) => set("contacto", e.target.value)} /></Field>
        </div>
        <Field label="Resumen / acuerdos"><textarea className="input" rows={3} required value={v.resumen} onChange={(e) => set("resumen", e.target.value)} /></Field>
        {sugs.length > 0 && !v.sin && (
          <div className="rounded-md border border-blue-200 bg-blue-50 p-2 text-sm">
            📅 Detecté {sugs.length === 1 ? "una fecha" : "fechas"}: {sugs.map((s) => (
              <button type="button" key={s.fecha + s.texto} className="btn mx-1 !py-0.5" onClick={() => { set("fecha_proximo_paso", s.fecha); }}>
                «{s.texto}» → {fdate(s.fecha)} · usar como fecha del próximo paso</button>))}
          </div>
        )}
        <fieldset className="rounded-md border border-slate-200 p-3">
          <legend className="px-1 text-xs font-medium text-slate-600">Próxima acción (obligatoria)</legend>
          {!v.sin ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Qué"><input className="input" value={v.proximo_paso} onChange={(e) => set("proximo_paso", e.target.value)} /></Field>
              <Field label="Fecha"><input className="input" type="date" value={v.fecha_proximo_paso} onChange={(e) => set("fecha_proximo_paso", e.target.value)} /></Field>
            </div>
          ) : <Field label="Motivo de 'sin próximo paso'"><input className="input" value={v.motivo} onChange={(e) => set("motivo", e.target.value)} /></Field>}
          <label className="mt-2 block text-sm"><input type="checkbox" checked={v.sin} onChange={(e) => set("sin", e.target.checked)} /> No hay próximo paso (indicar motivo)</label>
        </fieldset>
        <button className="btn btn-primary">Registrar</button>
      </form>

      <ol className="space-y-2">
        {o.activities.map((a: any) => (
          <li key={a.id} className="card !p-3 text-sm">
            <div className="flex justify-between text-xs text-slate-500"><span>{fdate(a.fecha)} · <b>{a.tipo}</b>{a.contacto ? ` · ${a.contacto}` : ""}</span><span>{a.source}</span></div>
            <p className="mt-1">{a.resumen}</p>
            {a.proximo_paso && <p className="mt-1 text-slate-600">▶ {a.proximo_paso} — {a.fecha_proximo_paso ? fdate(a.fecha_proximo_paso) : <span className="text-red-700">sin fecha</span>}</p>}
          </li>))}
        {o.activities.length === 0 && <p className="text-sm text-slate-500">Aún no hay actividades.</p>}
      </ol>
    </div>
  );
}

function Meddpicc({ o, base, onSaved }: { o: any; base: string; onSaved: () => void }) {
  const [items, setItems] = useState<any[]>(o.meddpicc.items);
  const [err, setErr] = useState("");
  const total = items.reduce((a, i) => a + Number(i.score), 0);
  async function save() { try { setErr(""); await api(`${base}/meddpicc`, { method: "PUT", body: items }); onSaved(); } catch (e: any) { setErr(e.message); } }
  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between"><h3 className="font-semibold">MEDDPICC</h3><b>{total}/16</b></div>
      <ErrorBox msg={err} />
      {items.map((it, i) => (
        <div key={it.criterion} className="grid items-center gap-2 sm:grid-cols-[10rem_8rem_1fr]">
          <span className="text-sm font-medium">{it.criterion}</span>
          <select className="input" value={it.score} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, score: Number(e.target.value) } : x)))}>
            <option value={0}>0 · sin evidencia</option><option value={1}>1 · parcial</option><option value={2}>2 · confirmado</option>
          </select>
          <input className="input" placeholder="Nota" value={it.note} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} />
        </div>))}
      <button className="btn btn-primary" onClick={save}>Guardar MEDDPICC</button>
    </div>
  );
}

function EditData({ o, base, cats, onSaved }: { o: any; base: string; cats: any; onSaved: () => void }) {
  const [v, setV] = useState<any>({ ...o });
  const [err, setErr] = useState("");
  const set = (k: string, val: any) => setV({ ...v, [k]: val === "" ? null : val });
  const keys = ["stage", "prioridad", "tipo", "monto", "fecha_cierre_est", "dr_vencimiento", "contrato_vencimiento", "seace_proceso", "seace_publicacion", "seace_buena_pro", "seace_propuestas", "competidor", "comentarios"];
  const labels: Record<string, string> = { stage: "Etapa", prioridad: "Prioridad", tipo: "Tipo", monto: "Monto (USD)", fecha_cierre_est: "Fecha de cierre estimada", dr_vencimiento: "Vencimiento deal registration", contrato_vencimiento: "Vencimiento contrato/soporte (EW/CSS)", seace_proceso: "N° proceso SEACE", seace_publicacion: "SEACE · publicación", seace_buena_pro: "SEACE · buena pro", seace_propuestas: "SEACE · presentación de propuestas", competidor: "Competidor principal", comentarios: "Comentarios" };
  const dates = new Set(["fecha_cierre_est", "dr_vencimiento", "contrato_vencimiento", "seace_publicacion", "seace_buena_pro", "seace_propuestas"]);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: any = {}; keys.forEach((k) => (body[k] = k === "monto" ? Number(v[k]) || 0 : v[k] ?? (dates.has(k) ? null : "")));
    try { setErr(""); await api(base, { method: "PATCH", body }); onSaved(); } catch (ex: any) { setErr(ex.message); }
  }
  return (
    <form onSubmit={save} className="card grid gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2"><ErrorBox msg={err} /></div>
      {keys.map((k) => (
        <Field key={k} label={labels[k]}>
          {k === "stage" ? <select className="input" value={v.stage} onChange={(e) => set(k, e.target.value)}>{(cats.stage || []).map((s: any) => <option key={s.id}>{s.value}</option>)}</select>
            : k === "prioridad" || k === "tipo" ? <select className="input" value={v[k]} onChange={(e) => set(k, e.target.value)}>{(cats[k] || []).map((s: any) => <option key={s.id}>{s.value}</option>)}</select>
            : k === "comentarios" ? <textarea className="input" rows={3} value={v[k] || ""} onChange={(e) => set(k, e.target.value)} />
            : <input className="input" type={dates.has(k) ? "date" : k === "monto" ? "number" : "text"} value={v[k] ?? ""} onChange={(e) => set(k, e.target.value)} />}
        </Field>))}
      <div className="sm:col-span-2"><button className="btn btn-primary">Guardar cambios</button></div>
    </form>
  );
}
