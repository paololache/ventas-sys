"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ErrorBox } from "@/components/ui";
import { api } from "@/lib/api";

type Kind = "clients" | "partners" | "contacts";
const COLS: Record<Kind, [string, string][]> = {
  clients: [["name", "Cliente final"], ["sector", "Sector"]],
  partners: [["name", "Partner"], ["notes", "Notas"]],
  contacts: [["name", "Nombre"], ["kind", "Tipo (client/partner)"], ["cargo", "Cargo"], ["email", "Email"], ["phone", "Teléfono"]],
};

export default function Directory() {
  const { wid } = useParams();
  const [kind, setKind] = useState<Kind>("clients");
  const [rows, setRows] = useState<any[]>([]);
  const [form, setForm] = useState<any>({});
  const [err, setErr] = useState("");
  const load = useCallback(() => { api(`/api/w/${wid}/${kind}`).then(setRows); setForm({}); }, [wid, kind]);
  useEffect(() => { load(); }, [load]);
  async function add(e: React.FormEvent) { e.preventDefault(); try { setErr(""); await api(`/api/w/${wid}/${kind}`, { body: form }); load(); } catch (ex: any) { setErr(ex.message); } }
  async function del(id: number) { if (confirm("¿Eliminar?")) { try { await api(`/api/w/${wid}/${kind}/${id}`, { method: "DELETE" }); load(); } catch (ex: any) { setErr(ex.message); } } }
  return (
    <div className="space-y-3">
      <div className="flex gap-1">{(["clients", "partners", "contacts"] as Kind[]).map((k) => <button key={k} className={`btn ${kind === k ? "btn-primary" : ""}`} onClick={() => setKind(k)}>{{ clients: "Clientes finales", partners: "Partners", contacts: "Contactos" }[k]}</button>)}</div>
      <ErrorBox msg={err} />
      <form onSubmit={add} className="card flex flex-wrap items-end gap-2">
        {COLS[kind].map(([k, l]) => <label key={k} className="block"><span className="label">{l}</span><input className="input" required={k === "name"} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>)}
        <button className="btn btn-primary">Agregar</button>
      </form>
      <div className="card overflow-x-auto !p-0"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-xs text-slate-500"><tr>{COLS[kind].map(([k, l]) => <th key={k} className="px-3 py-2">{l}</th>)}<th /></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id} className="border-t">{COLS[kind].map(([k]) => <td key={k} className="px-3 py-1.5">{r[k]}</td>)}<td className="px-3 text-right"><button className="text-xs text-red-700 underline" onClick={() => del(r.id)}>eliminar</button></td></tr>)}</tbody></table></div>
    </div>
  );
}
