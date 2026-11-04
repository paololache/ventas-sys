"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertT, api, fdate } from "@/lib/api";
import { Badge, SEV_STYLE } from "@/components/ui";

export default function Alerts() {
  const { wid } = useParams();
  const [data, setData] = useState<{ count: number; alerts: AlertT[] } | null>(null);
  const [snoozed, setSnoozed] = useState(false);
  const load = useCallback(() => { api(`/api/w/${wid}/alerts?include_snoozed=${snoozed}`).then(setData); }, [wid, snoozed]);
  useEffect(() => { load(); }, [load]);

  async function snooze(id: number, days: number) { await api(`/api/w/${wid}/alerts/${id}/snooze`, { body: { days } }); load(); }
  async function read(id: number) { await api(`/api/w/${wid}/alerts/${id}/read`, { body: {} }); load(); }

  if (!data) return <p className="text-slate-500">Cargando…</p>;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Bandeja de alertas <span className="text-sm font-normal text-slate-500">({data.count})</span></h1>
        <label className="ml-auto text-sm"><input type="checkbox" checked={snoozed} onChange={(e) => setSnoozed(e.target.checked)} /> incluir pospuestas</label>
        <button className="btn" onClick={async () => { await api(`/api/w/${wid}/alerts/read-all`, { body: {} }); load(); }}>Marcar todo leído</button>
        <button className="btn" onClick={async () => { await api(`/api/w/${wid}/alerts/refresh`, { body: {} }); load(); }}>Re-evaluar</button>
      </div>
      <p className="text-xs text-slate-500">Ordenadas por severidad, prioridad y monto. Se cierran solas cuando registras una actividad o actualizas la oportunidad.</p>
      {data.alerts.length === 0 && <div className="card text-center text-slate-500">🎉 Todo al día.</div>}
      <ul className="space-y-2">
        {data.alerts.map((a) => (
          <li key={a.id} className={`card flex flex-wrap items-center gap-3 !p-3 ${a.read ? "opacity-70" : ""}`}>
            <Badge cls={SEV_STYLE[a.severity]}>{a.severity}{a.escalated ? " ↑" : ""}</Badge>
            <Badge>{a.rule}</Badge>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{a.title}</div>
              <div className="text-xs text-slate-500">{a.detail}{a.snoozed_until ? ` · pospuesta hasta ${fdate(a.snoozed_until)}` : ""}</div>
            </div>
            {a.opportunity_id && <Link className="btn" href={`/w/${wid}/opportunities/${a.opportunity_id}`}>Abrir</Link>}
            <select className="input !w-auto" defaultValue="" onChange={(e) => { if (e.target.value) snooze(a.id, Number(e.target.value)); }} aria-label="Posponer">
              <option value="">⏰ Posponer</option><option value="1">1 día</option><option value="3">3 días</option><option value="7">1 semana</option>
            </select>
            {!a.read && <button className="btn" onClick={() => read(a.id)}>Leída</button>}
          </li>
        ))}
      </ul>
    </div>
  );
}
