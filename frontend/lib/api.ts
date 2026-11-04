export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function token(): string {
  try { return localStorage.getItem("crm_token") || ""; } catch { return ""; }
}
export function setToken(t: string) { try { localStorage.setItem("crm_token", t); } catch {} }
export function clearToken() { try { localStorage.removeItem("crm_token"); } catch {} }

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) { super(msg); this.status = status; }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token()}` };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) body = opts.body;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const r = await fetch(`${API}${path}`, { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers, body });
  if (r.status === 401 && typeof window !== "undefined" && !path.includes("/auth/login")) {
    clearToken(); window.location.href = "/login";
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new ApiError(r.status, msg);
  }
  if (opts.raw) return r as any;
  if (r.status === 204) return undefined as any;
  return r.json();
}

export async function download(path: string, filename: string) {
  const r: Response = await api(path, { raw: true });
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
}

export const usd = (n: number | null | undefined) => (n == null ? "—" : "USD " + Math.round(n).toLocaleString("es-PE"));
export const fdate = (d?: string | null) => (d ? d.split("-").reverse().join("/") : "—");

export type Opp = {
  id: number; code: string; tipo: string; client: string; client_id: number | null; descripcion: string; sector: string; partner: string;
  partner_id: number | null; marca: string; monto: number; meddpicc_score: number; stage: string; prob: number; monto_ponderado: number;
  prioridad: string; fecha_cierre_est: string | null; prox_accion: string; fecha_prox_accion: string | null; sin_proximo_paso_motivo: string;
  dias_para_accion: number | null; alerta: string; responsable: string; ultima_actualizacion: string | null; comentarios: string;
  dr_vencimiento: string | null; contrato_vencimiento: string | null; seace_proceso: string; seace_publicacion: string | null;
  seace_buena_pro: string | null; seace_propuestas: string | null; competidor: string; is_closed: boolean; is_paused: boolean;
  [k: string]: any;
};
export type AlertT = { id: number; rule: string; severity: "Alta" | "Media" | "Baja"; title: string; detail: string; opportunity_id: number | null; snoozed_until: string | null; read: boolean; escalated: boolean };
export type Me = { id: number; email: string; name: string; is_superadmin: boolean; tenants: { id: number; name: string; slug: string; role: string; workspaces: { id: number; name: string }[] }[] };
