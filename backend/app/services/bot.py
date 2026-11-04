"""Lógica del bot de Telegram (bidireccional). Funciona por webhook, así soporta un bot distinto por empresa.

`handle_update` es independiente de HTTP: recibe el update (dict), el cliente de Telegram y el reloj.
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts.engine import evaluate_workspace, open_alerts_sorted
from ..channels.base import Button, Message
from ..channels.telegram import to_markup
from ..clock import Clock
from ..dates_es import extract_dates, first_future_date
from ..deps import Ctx, tenant_role
from ..models import Alert, Client, Contact, Opportunity, Partner, TelegramLink, Tenant, User, Workspace
from .notify import app_url
from .opportunities import BusinessError, register_activity, update_opportunity
from .seed import stage_info

e = html.escape
HELP = (
    "<b>Comandos</b>\n/hoy · acciones de hoy y vencidas\n/vencidas · acciones vencidas\n/semana · próximos 7 días\n"
    "/pipeline · resumen por etapa\n/op OP-002 · ficha\n"
    "/log OP-002 llamé a Miriam, presenta propuesta el 11/11 · registra actividad y propone la próxima acción"
)
TIPO_KEYWORDS = [
    (r"llam", "Llamada"), (r"reuni", "Reunión"), (r"correo|email|mail", "Email"), (r"demo|poc", "Demo/POC"),
    (r"envi\w+ (la )?propuesta|propuesta enviada", "Envío de propuesta"), (r"visit", "Visita cliente"), (r"partner", "Seguimiento partner"),
]


def guess_tipo(text: str) -> str:
    t = text.lower()
    for pat, tipo in TIPO_KEYWORDS:
        if re.search(pat, t):
            return tipo
    return "Llamada"


def action_segment(text: str, sug) -> str:
    """Fragmento (separado por , ; .) que contiene la fecha detectada: es la próxima acción propuesta."""
    pos = 0
    for seg in re.split(r"[,;]|\.\s", text):
        if pos <= sug.start < pos + len(seg) + 1:
            return seg.strip(" .")
        pos += len(seg) + 1
    return text.strip()


class Bot:
    def __init__(self, db: Session, tenant: Tenant, client, clock: Clock):
        self.db, self.tenant, self.client, self.clock = db, tenant, client, clock

    # ------------------------------------------------------------ salida
    def say(self, chat_id, msg: Message | str):
        if isinstance(msg, str):
            msg = Message(msg)
        self.client.send_message(chat_id, msg.html, to_markup(msg))

    # ------------------------------------------------------------ entrada
    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            cq = update["callback_query"]
            chat_id = str(cq["message"]["chat"]["id"])
            self.client.answer_callback(cq["id"])
            link = self._link(chat_id)
            if link:
                self._callback(link, chat_id, cq.get("data", ""))
            return
        msg = update.get("message")
        if not msg or "text" not in msg:
            return
        chat_id, text = str(msg["chat"]["id"]), msg["text"].strip()
        if text.startswith("/start"):
            return self._start(chat_id, text)
        link = self._link(chat_id)
        if not link:
            return self.say(chat_id, "Este chat no está vinculado. En la app, ve a Configuración → Telegram, genera un código y envíame <code>/start CODIGO</code>.")
        if text.startswith("/"):
            link.state = {}
            return self._command(link, chat_id, text)
        if link.state:
            return self._conversation(link, chat_id, text)
        self.say(chat_id, "No entendí. " + HELP)

    # ------------------------------------------------------------ contexto
    def _link(self, chat_id: str) -> TelegramLink | None:
        return self.db.scalar(select(TelegramLink).where(TelegramLink.tenant_id == self.tenant.id, TelegramLink.chat_id == chat_id))

    def _ctx(self, link: TelegramLink) -> Ctx:
        user, ws = self.db.get(User, link.user_id), self.db.get(Workspace, link.workspace_id)
        return Ctx(user, self.tenant, ws, tenant_role(self.db, user, self.tenant.id) or "member")

    def _today(self) -> date:
        return self.clock.today(self.tenant.timezone)

    def _opp(self, ctx: Ctx, code: str) -> Opportunity | None:
        return self.db.scalar(select(Opportunity).where(Opportunity.workspace_id == ctx.ws.id, Opportunity.code == code.upper()))

    def _refresh(self, ctx: Ctx):
        evaluate_workspace(self.db, ctx.ws, self._today(), self.clock.now_utc())

    def _label(self, o: Opportunity) -> str:
        c = self.db.get(Client, o.client_id) if o.client_id else None
        return f"{o.code} · {c.name if c else 'Sin cliente'}"

    # ------------------------------------------------------------ /start
    def _start(self, chat_id: str, text: str):
        parts = text.split()
        if len(parts) < 2:
            return self.say(chat_id, "Hola 👋 Envía <code>/start CODIGO</code> con el código generado en la app (Configuración → Telegram).")
        link = self.db.scalar(select(TelegramLink).where(TelegramLink.tenant_id == self.tenant.id, TelegramLink.link_code == parts[1].strip()))
        if not link:
            return self.say(chat_id, "Código inválido o ya usado.")
        # un chat se vincula a un solo workspace a la vez
        for old in self.db.scalars(select(TelegramLink).where(TelegramLink.tenant_id == self.tenant.id, TelegramLink.chat_id == chat_id, TelegramLink.id != link.id)):
            self.db.delete(old)
        self.db.flush()
        link.chat_id, link.link_code, link.state = chat_id, None, {}
        ws = self.db.get(Workspace, link.workspace_id)
        self.say(chat_id, f"✅ Vinculado a <b>{e(self.tenant.name)} / {e(ws.name)}</b>.\n\n{HELP}")

    # ------------------------------------------------------------ comandos
    def _command(self, link: TelegramLink, chat_id: str, text: str):
        ctx = self._ctx(link)
        cmd, _, rest = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        today = self._today()
        if cmd in ("/ayuda", "/help"):
            return self.say(chat_id, HELP)
        if cmd == "/hoy":
            return self._list_actions(ctx, chat_id, "Para hoy y vencidas", lambda o: o.fecha_prox_accion and o.fecha_prox_accion <= today)
        if cmd == "/vencidas":
            return self._list_actions(ctx, chat_id, "Acciones vencidas", lambda o: o.fecha_prox_accion and o.fecha_prox_accion < today)
        if cmd == "/semana":
            return self._list_actions(ctx, chat_id, "Próximos 7 días", lambda o: o.fecha_prox_accion and o.fecha_prox_accion <= today + timedelta(days=7))
        if cmd == "/pipeline":
            return self._pipeline(ctx, chat_id)
        if cmd == "/op":
            return self._op(ctx, chat_id, rest.strip())
        if cmd == "/log":
            return self._log(link, ctx, chat_id, rest.strip())
        self.say(chat_id, HELP)

    def _open_opps(self, ctx: Ctx):
        info = stage_info(self.db, ctx.ws.id)
        return [o for o in self.db.scalars(select(Opportunity).where(Opportunity.workspace_id == ctx.ws.id))
                if not (info.get(o.stage) and (info[o.stage].is_closed or info[o.stage].is_paused))]

    def _list_actions(self, ctx: Ctx, chat_id, title, pred):
        today = self._today()
        rows = sorted((o for o in self._open_opps(ctx) if pred(o)), key=lambda o: (o.fecha_prox_accion, -o.monto))
        if not rows:
            return self.say(chat_id, f"<b>{title}</b>\n\nNada pendiente ✅")
        lines = []
        for o in rows[:20]:
            d = o.fecha_prox_accion
            tag = f"⚠️ vencida {(today - d).days} d" if d < today else ("hoy" if d == today else d.strftime("%d/%m"))
            lines.append(f"• <b>{e(self._label(o))}</b> — {e(o.prox_accion or 'acción')} ({tag})")
        sin = [o for o in self._open_opps(ctx) if not o.prox_accion.strip() or not o.fecha_prox_accion]
        extra = f"\n\n🔴 {len(sin)} oportunidades sin próxima acción (usa /op ID)." if sin else ""
        self.say(chat_id, f"<b>{title}</b> ({len(rows)})\n\n" + "\n".join(lines) + extra)

    def _pipeline(self, ctx: Ctx, chat_id):
        from .reports import dashboard

        d = dashboard(self.db, ctx.ws, self._today())
        lines = [f"• {b['stage']}: {b['count']} · USD {b['monto']:,.0f}" for b in d["por_etapa"] if b["count"]]
        self.say(chat_id, f"<b>Pipeline</b>\nAbierto: USD {d['pipeline_abierto']:,.0f} ({d['abiertas']})\nForecast ponderado: USD {d['forecast_ponderado']:,.0f}\n"
                          f"Ganado: USD {d['ganado']:,.0f} · Win rate: {d['win_rate'] if d['win_rate'] is not None else '—'}%\n\n" + "\n".join(lines))

    def _op(self, ctx: Ctx, chat_id, code: str):
        o = self._opp(ctx, code) if code else None
        if not o:
            return self.say(chat_id, "No encontré esa oportunidad. Ejemplo: <code>/op OP-002</code>")
        alerts = self.db.scalars(select(Alert).where(Alert.opportunity_id == o.id, Alert.status == "open")).all()
        txt = (f"<b>{e(self._label(o))}</b>\n{e(o.descripcion)}\nEtapa: {e(o.stage)} · Prioridad: {o.prioridad} · USD {o.monto:,.0f}\n"
               f"Cierre est.: {o.fecha_cierre_est:%d/%m/%Y}\n" if o.fecha_cierre_est else
               f"<b>{e(self._label(o))}</b>\n{e(o.descripcion)}\nEtapa: {e(o.stage)} · Prioridad: {o.prioridad} · USD {o.monto:,.0f}\nCierre est.: —\n")
        txt += f"Próxima acción: {e(o.prox_accion) or '—'} ({o.fecha_prox_accion:%d/%m/%Y})\n" if o.fecha_prox_accion else f"Próxima acción: {e(o.prox_accion) or '—'} (sin fecha)\n"
        txt += f"Última actualización: {o.ultima_actualizacion:%d/%m/%Y}\n" if o.ultima_actualizacion else ""
        txt += f"MEDDPICC: {o.meddpicc_score}/16"
        if alerts:
            txt += "\n\n" + "\n".join(f"⚠️ {e(a.title)}" for a in alerts[:5])
        self.say(chat_id, Message(txt, [[Button("📝 Registrar actividad", f"lg:{o.id}"), Button("🔗 Abrir en la app", url=app_url(ctx.ws, f"/opportunities/{o.id}"))]]))

    # ------------------------------------------------------------ /log
    def _log(self, link: TelegramLink, ctx: Ctx, chat_id, rest: str):
        m = re.match(r"(OP-\d+)\s+(.+)", rest, re.I | re.S)
        if not m:
            return self.say(chat_id, "Formato: <code>/log OP-002 llamé a Miriam, presenta propuesta el 11/11</code>")
        opp = self._opp(ctx, m.group(1))
        if not opp:
            return self.say(chat_id, f"No existe {e(m.group(1).upper())}.")
        text, today = m.group(2).strip(), self._today()
        sug = first_future_date(text, today)
        register_activity(self.db, ctx, opp, fecha=today, tipo=guess_tipo(text), resumen=text, source="telegram", require_next=False, today=today)
        self._refresh(ctx)
        if sug:
            accion = action_segment(text, sug)
            link.state = {"step": "proposal", "opp_id": opp.id, "accion": accion, "fecha": sug.fecha.isoformat()}
            self.say(chat_id, Message(
                f"📝 Actividad registrada en <b>{e(self._label(opp))}</b>.\n\nDetecté una fecha: «{e(sug.texto)}» → <b>{sug.fecha:%d/%m/%Y}</b>.\n¿Programo la próxima acción «{e(accion)}» para esa fecha?",
                [[Button(f"✅ Sí, {sug.fecha:%d/%m}", "pna"), Button("✏️ Otra", "pne")]]))
        else:
            link.state = {"step": "next", "opp_id": opp.id, "summary": None}
            self.say(chat_id, f"📝 Actividad registrada en <b>{e(self._label(opp))}</b>.\n\n¿Cuál es la <b>próxima acción y su fecha</b>? (ej: «enviar propuesta el 15/11» o «sin: cliente pausó el proyecto»)")

    # ------------------------------------------------------------ callbacks
    def _callback(self, link: TelegramLink, chat_id: str, data: str):
        ctx = self._ctx(link)
        kind, _, arg = data.partition(":")
        today = self._today()
        if kind == "pna":
            st = link.state or {}
            if st.get("step") != "proposal":
                return self.say(chat_id, "Esa propuesta ya no está vigente.")
            opp = self.db.get(Opportunity, st["opp_id"])
            update_opportunity(self.db, ctx, opp, {"prox_accion": st["accion"], "fecha_prox_accion": date.fromisoformat(st["fecha"])}, today)
            link.state = {}
            self._refresh(ctx)
            return self.say(chat_id, f"📅 Próxima acción de <b>{e(opp.code)}</b>: {e(st['accion'])} — {date.fromisoformat(st['fecha']):%d/%m/%Y}.")
        if kind == "pne":
            st = link.state or {}
            link.state = {"step": "next", "opp_id": st.get("opp_id"), "summary": None}
            return self.say(chat_id, "Escribe la próxima acción con su fecha (ej: «llamar a Miriam el lunes»).")
        if kind == "lg":
            link.state = {"step": "summary", "opp_id": int(arg), "alert_id": None}
            return self.say(chat_id, "¿Qué se hizo? Escribe un resumen corto.")
        alert = self.db.scalar(select(Alert).where(Alert.id == int(arg.split(":")[0]), Alert.workspace_id == ctx.ws.id)) if arg and arg.split(":")[0].isdigit() else None
        if kind == "done":
            if not alert:
                return self.say(chat_id, "Esa alerta ya no existe.")
            if alert.opportunity_id:
                link.state = {"step": "summary", "opp_id": alert.opportunity_id, "alert_id": alert.id}
                return self.say(chat_id, f"✅ ¿Qué se hizo en <b>{e(alert.title.split(':')[0])}</b>? Escribe un resumen corto.")
            alert.status, alert.resolved_at, alert.resolved_reason = "resolved", self.clock.now_utc(), "marcada como hecha"
            return self.say(chat_id, "Alerta cerrada ✅")
        if kind == "snzm":
            return self.say(chat_id, Message("¿Hasta cuándo la pospongo?", [[
                Button("1 día", f"snz:{alert.id}:1"), Button("3 días", f"snz:{alert.id}:3"), Button("1 semana", f"snz:{alert.id}:7")],
                [Button("📅 Hasta una fecha", f"snz:{alert.id}:d")]]))
        if kind == "snz" and alert:
            how = data.split(":")[2]
            if how == "d":
                link.state = {"step": "snooze_date", "alert_id": alert.id}
                return self.say(chat_id, "Escribe la fecha (ej: 20/11 o «el lunes»).")
            alert.snoozed_until = today + timedelta(days=int(how))
            return self.say(chat_id, f"⏰ Pospuesta hasta el {alert.snoozed_until:%d/%m/%Y}.")
        if kind == "ct" and alert:
            return self.say(chat_id, self._contact_text(alert))

    def _contact_text(self, alert: Alert) -> str:
        cs: list[Contact] = []
        if alert.opportunity_id:
            o = self.db.get(Opportunity, alert.opportunity_id)
            if o.responsable_id:
                cs.append(self.db.get(Contact, o.responsable_id))
            if o.client_id:
                cs += [c for c in self.db.scalars(select(Contact).where(Contact.client_id == o.client_id)) if c not in cs]
            if o.partner_id:
                cs += self.db.scalars(select(Contact).where(Contact.partner_id == o.partner_id)).all()
        elif alert.partner_id:
            cs = self.db.scalars(select(Contact).where(Contact.partner_id == alert.partner_id)).all()
        if not cs:
            return "Sin contactos registrados para esta oportunidad."
        return "\n".join(f"📞 <b>{e(c.name)}</b> ({e(c.cargo) or c.kind})\n    {e(c.phone) or '—'} · {e(c.email) or '—'}" for c in cs[:5])

    # ------------------------------------------------------------ conversación
    def _parse_next(self, text: str):
        """→ (accion, fecha, motivo_sin_proximo_paso) | None"""
        today = self._today()
        if text.lower().startswith("sin"):
            motivo = text.split(":", 1)[1].strip() if ":" in text else ""
            return ("", None, motivo) if motivo else None
        sug = first_future_date(text, today)
        return (text.strip(), sug.fecha, "") if sug else None

    def _conversation(self, link: TelegramLink, chat_id: str, text: str):
        ctx, st, today = self._ctx(link), dict(link.state), self._today()
        step = st.get("step")
        if step == "summary":
            link.state = {**st, "step": "next", "summary": text}
            return self.say(chat_id, "Anotado. ¿Cuál es la <b>próxima acción y su fecha</b>? (ej: «enviar propuesta el 15/11» · o «sin: motivo»)")
        if step == "next":
            parsed = self._parse_next(text)
            if not parsed:
                return self.say(chat_id, "No detecté una fecha. Escribe por ejemplo «llamar el 15/11», «el lunes» o «sin: motivo».")
            accion, fecha, motivo = parsed
            opp = self.db.get(Opportunity, st["opp_id"])
            try:
                if st.get("summary"):
                    register_activity(self.db, ctx, opp, fecha=today, tipo=guess_tipo(st["summary"]), resumen=st["summary"], proximo_paso=accion,
                                      fecha_proximo_paso=fecha, sin_proximo_paso_motivo=motivo, source="telegram", today=today)
                else:
                    update_opportunity(self.db, ctx, opp, {"prox_accion": accion, "fecha_prox_accion": fecha, "sin_proximo_paso_motivo": motivo}, today)
            except BusinessError as ex:
                return self.say(chat_id, str(ex))
            link.state = {}
            self._refresh(ctx)
            fin = f"Próxima acción: {e(accion)} — {fecha:%d/%m/%Y}" if fecha else f"Sin próximo paso: {e(motivo)}"
            return self.say(chat_id, f"✅ Listo, <b>{e(self._label(opp))}</b> actualizada.\n{fin}")
        if step == "snooze_date":
            sug = first_future_date(text, today)
            if not sug:
                return self.say(chat_id, "No entendí la fecha. Prueba con 20/11.")
            alert = self.db.get(Alert, st["alert_id"])
            alert.snoozed_until = sug.fecha
            link.state = {}
            return self.say(chat_id, f"⏰ Pospuesta hasta el {sug.fecha:%d/%m/%Y}.")
        link.state = {}
        self.say(chat_id, HELP)
