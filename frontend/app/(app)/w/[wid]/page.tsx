"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, usd } from "@/lib/api";
import { Bar, Stat } from "@/components/ui";

type Row = { name?: string; stage?: string; count: number; monto: number; ponderado: number };

function Table({ title, rows, k }: { title: string; rows: Row[]; k: "name" | "stage" }) {
  const max = Math.max(1, ...rows.map((r) => r.monto));
  return (
    <div className="card">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th>Nombre</th><th className="text-right">#</th><th className="text-right">Monto</th><th className="w-1/4"></th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r[k]} className="border-t"><td className="py-1">{r[k]}</td><td className="text-right">{r.count}</td><td className="text-right">{usd(r.monto)}</td><td className="pl-2"><Bar pct={(100 * r.monto) / max} /></td></tr>
        ))}</tbody></table>
    </div>
  );
}

export default function Dashboard() {
  const { wid } = useParams();
  const [d, setD] = useState<any>(null);
  const [alerts, setAlerts] = useState<any>(null);
  useEffect(() => {
    api(`/api/w/${wid}/dashboard`).then(setD);
    api(`/api/w/${wid}/alerts`).then(setAlerts);
  }, [wid]);
  if (!d) return <p className="text-slate-500">Cargando…</p>;
  const s = d.salud;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Pipeline abierto" value={usd(d.pipeline_abierto)} />
        <Stat label="Forecast ponderado" value={usd(d.forecast_ponderado)} />
        <Stat label="Ganado" value={usd(d.ganado)} />
        <Stat label="Abiertas" value={d.abiertas} />
        <Stat label="Acciones vencidas" value={d.acciones_vencidas} tone={d.acciones_vencidas ? "red" : undefined} />
        <Stat label="Win rate" value={d.win_rate == null ? "—" : `${d.win_rate}%`} />
      </div>

      {alerts && alerts.count > 0 && (
        <div className="card border-red-200 bg-red-50">
          <b className="text-red-800">{alerts.count} alertas abiertas</b>{" "}
          <a className="underline" href={`/w/${wid}/alerts`}>ver bandeja</a>
          <ul className="mt-2 space-y-1 text-sm">{alerts.alerts.slice(0, 5).map((a: any) => <li key={a.id}>{a.severity === "Alta" ? "🔴" : "🟠"} {a.title}</li>)}</ul>
        </div>
      )}

      <div className="card">
        <h3 className="mb-3 font-semibold">Salud del pipeline <span className="text-xs font-normal text-slate-500">({s.total_activas} oportunidades activas)</span></h3>
        <div className="grid gap-4 md:grid-cols-3">
          {[["Con próxima acción vigente", s.pct_proxima_accion_vigente], ["Con fecha de cierre", s.pct_fecha_cierre], ["Con MEDDPICC", s.pct_meddpicc]].map(([l, v]) => (
            <div key={l as string}><div className="mb-1 flex justify-between text-sm"><span>{l}</span><b>{v}%</b></div><Bar pct={v as number} color={(v as number) < 50 ? "bg-red-500" : (v as number) < 80 ? "bg-amber-500" : "bg-green-600"} /></div>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Table title="Por etapa" rows={d.por_etapa.filter((r: any) => r.count)} k="stage" />
        <Table title="Por tipo" rows={d.por_tipo} k="name" />
        <Table title="Por partner" rows={d.por_partner} k="name" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h3 className="mb-2 font-semibold">Forecast por mes de cierre</h3>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th>Mes</th><th className="text-right">#</th><th className="text-right">Bruto</th><th className="text-right">Ponderado</th></tr></thead>
            <tbody>{d.forecast_por_mes.map((m: any) => <tr key={m.mes} className="border-t"><td className="py-1">{m.mes}</td><td className="text-right">{m.count}</td><td className="text-right">{usd(m.monto)}</td><td className="text-right">{usd(m.ponderado)}</td></tr>)}</tbody></table>
        </div>
        <div className="card">
          <h3 className="mb-2 font-semibold">Aging por etapa (días en la etapa)</h3>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th>Etapa</th><th className="text-right">#</th><th className="text-right">Prom.</th><th className="text-right">Máx.</th></tr></thead>
            <tbody>{d.aging.map((a: any) => <tr key={a.stage} className="border-t"><td className="py-1">{a.stage}</td><td className="text-right">{a.count}</td><td className="text-right">{a.avg_days}</td><td className="text-right">{a.max_days}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  );
}
