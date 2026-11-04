# CRM comercial proactivo (multi-empresa)

CRM de pipeline para Channel Account Managers / presales, cuyo valor central es el **motor de alertas**: el sistema te avisa
(Telegram, email y bandeja in-app) cuándo llamar, qué seguimiento está vencido y qué oportunidad lleva demasiado tiempo sin tocarse.
Reemplaza al Excel `CRM_Oportunidades_Adistec.xlsx` y soporta **varias empresas, cada una aislada, con múltiples espacios de trabajo**.

## Arquitectura y por qué este stack

| Capa | Elección | Por qué |
|---|---|---|
| API | **FastAPI + SQLAlchemy 2 + Alembic** (Python) | Las reglas de alerta son lógica de negocio pura y fechas: Python las expresa y testea mejor; FastAPI da validación y OpenAPI (`/docs`) gratis. |
| BD | **PostgreSQL** (SQLite en desarrollo/tests) | Transaccional, JSON nativo para configuración por empresa. |
| Jobs | **APScheduler** (en el mismo proceso) | Un solo contenedor; el *tick* (cada 15 min) decide por empresa y hora local qué toca enviar. |
| Telegram | **Webhook propio sobre `httpx`** | Un bot **por empresa** sin procesos de *polling* por tenant; el tenant sale de la URL del webhook. |
| UI | **Next.js 14 + TypeScript + Tailwind** | Kanban, tabla, ficha y configuración. Componentes propios estilo shadcn (sin dependencia extra). |

### Multi-empresa (tenants) y espacios de trabajo

```
Plataforma (superadmin)
 └─ Empresa (Tenant)        → bot de Telegram, SMTP, zona horaria y usuarios propios
     └─ Espacio de trabajo  → pipeline, catálogos, reglas de alerta, feriados y horario laboral propios
         └─ datos: oportunidades, clientes, partners, contactos, actividades, alertas…
```

* **Aislamiento por fila**: toda entidad lleva `tenant_id` + `workspace_id` + `owner_id`. Todo acceso pasa por `deps.scoped()` / `get_owned()`
  (filtra siempre por el workspace autenticado) y las referencias cruzadas (p. ej. asignar el partner de otra empresa) se rechazan.
  Se prefirió *shared schema* a *schema-por-tenant* porque permite crear empresas sin migraciones ni DDL en caliente; las pruebas de `tests/test_tenancy.py`
  verifican que una empresa no puede ver, modificar ni referenciar datos de otra (responde 404 para no revelar existencia).
* **Roles**: `superadmin` (plataforma; crea/desactiva empresas) · `owner`/`admin` (administran la empresa y todos sus espacios) · `member`
  (vendedor: sólo los espacios que se le asignan).
* **Crear más empresas**: `POST /api/tenants` o pantalla *Empresas* (sólo superadmin). Cada empresa nace con su espacio sembrado
  (etapas+probabilidades, catálogos, 13 reglas, feriados de Perú 2026-2027).

## Motor de alertas

Reglas R1–R13 como **funciones puras** (`backend/app/alerts/rules.py`): reciben vistas inmutables + `today` inyectado y devuelven candidatas.
Umbrales y severidad viven en BD (`alert_rules`, editables en *Configuración → Reglas*). `alerts/engine.py` las orquesta:

* **Deduplicación**: clave estable por regla+objeto; una alerta existente se actualiza, no se recrea.
* **Resolución automática**: tras registrar una actividad o cambiar la oportunidad se re-evalúa y las que ya no aplican se cierran solas.
* **Cadencia y escalamiento**: Alta cada 1 día, Media cada 3 (configurable). Una Media que acumula 3 avisos sin atenderse pasa a Alta.
* **Snooze**: 1 día, 3 días, 1 semana o hasta fecha (web y Telegram).
* **Horario laboral**: L-V 8–19 (configurable) sin feriados; fuera de horario sólo salen las **Alta con fecha de hoy** (DR que vence hoy, hito SEACE hoy…).
* **Agrupación**: las alertas se envían agrupadas por regla y ordenadas por prioridad → monto (25 "sin próxima acción" = **1 mensaje**).
* **Fechas en texto libre** (`dates_es.py`): "el 15/11", "15 de noviembre", "mañana", "la semana que viene", "el viernes", "en 3 días"… se *proponen*, nunca se crean sin confirmar.
* "Última actualización" ya no es manual: se actualiza al registrar actividades y al cambiar etapa, monto, cierre o próxima acción.
* Registrar una actividad **obliga** a definir próxima acción con fecha o marcar "sin próximo paso" con motivo.

## Canales

* **Telegram** (por empresa): resumen diario 8:00 hora de la empresa; alertas Alta agrupadas con botones ✅ Hecho · ⏰ Posponer · 📞 Ver contacto · 🔗 Abrir en la app;
  comandos `/hoy /vencidas /semana /pipeline /op OP-002 /log OP-002 llamé a Miriam, presenta propuesta el 11/11`.
* **Email**: resumen semanal el primer día hábil de la semana a las 7:30 (pipeline, forecast del mes, sin actualizar, datos incompletos, a quién llamar).
* **In-app**: campana con contador y bandeja.
* Interfaz común `channels/base.py`; `channels/stubs.py` deja listos los adaptadores de **Google Calendar** y **WhatsApp** (fase posterior, no implementados).

## Puesta en marcha

```bash
cp .env.example .env        # edita SECRET_KEY, BOOTSTRAP_ADMIN_*, POSTGRES_PASSWORD
docker compose up --build
```

* App: http://localhost:3000 · API/Swagger: http://localhost:8000/docs
* Entra con `BOOTSTRAP_ADMIN_EMAIL` → *Empresas* → **Crear nueva empresa** (define su propietario). Cierra sesión y entra como el propietario.

Desarrollo sin Docker:

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
SCHEDULER_ENABLED=true alembic upgrade head && uvicorn app.main:app --reload     # SQLite por defecto
pytest -q                                                                          # 63 tests
cd ../frontend && npm install && npm run dev
```

### Migrar el Excel

Desde la app: *Configuración → Importar / Exportar*. O por CLI (idempotente; conserva `OP-xxx`, unifica partners/clientes/contactos, vincula la bitácora por ID):

```bash
cd backend && python -m app.cli import-excel /ruta/CRM_Oportunidades_Adistec.xlsx --workspace-id 1
```

Imprime el **reporte de calidad** (sin próxima acción, sin fecha de cierre, sin contacto, sin MEDDPICC, actividades con próximo paso sin fecha). Las cifras
se calculan con las mismas reglas del motor, por lo que coinciden con las alertas de la primera corrida (hay un test que lo verifica).
*Exportar a Excel* devuelve `Pipeline / Bitácora / Listas` con las mismas columnas.

## Crear el bot de Telegram (una vez por empresa)

1. En Telegram habla con **@BotFather** → `/newbot` → elige nombre y usuario → copia el **token**.
2. En la app: *Empresas → (tu empresa) → Bot de Telegram*, pega el token, **Guardar** y luego **Registrar webhook**.
   Requiere que `API_PUBLIC_URL` sea una URL **HTTPS pública** (Telegram no acepta `localhost`; en local usa un túnel tipo ngrok/cloudflared).
3. Vincula tu chat: *Configuración → Notificaciones y Telegram → Generar código* y envía `/start CODIGO` a tu bot.
   (El *chat ID* queda guardado automáticamente; no necesitas buscarlo.)

## Configurar Gmail (email semanal)

1. Activa la verificación en dos pasos en tu cuenta de Google → *Contraseñas de aplicaciones* → genera una de 16 caracteres.
2. En *Empresas → SMTP*: host `smtp.gmail.com`, puerto `587`, usuario = tu correo, contraseña = la de aplicación, remitente = tu correo.

## Desplegar 24/7

Si corre sólo en tu laptop apagada **no avisa**. Opciones baratas:

* **VPS** (Hetzner/DigitalOcean/Contabo, ~US$5/mes): instala Docker, clona el repo, `cp .env.example .env`, `docker compose up -d --build`, y pon **Caddy** o
  **nginx + certbot** delante para HTTPS (`api.tudominio.com` → 8000, `crm.tudominio.com` → 3000). Ajusta `PUBLIC_URL`, `API_PUBLIC_URL`, `CORS_ORIGINS` y `NEXT_PUBLIC_API_URL`.
* **Railway / Render**: 3 servicios (Postgres gestionado, `backend/` con su Dockerfile, `frontend/` con su Dockerfile con el *build arg* `NEXT_PUBLIC_API_URL`).
  Mantén **una sola instancia** del backend (el scheduler corre en proceso) y usa un plan que no se "duerma".
* Haz copia de seguridad de Postgres (`pg_dump` diario).

## Decisiones, límites y pendientes (a conciencia)

* **El Excel real no estaba disponible** en el entorno de desarrollo. El importador sigue la estructura descrita (encabezados en fila 4, hojas `Pipeline`/`Bitácora`/`Listas`,
  detección de encabezados tolerante a tildes/espacios) y se probó con un **fixture sintético** (`backend/tests/make_fixture.py`) que reproduce los problemas descritos.
  Ejecuta el importador con tu archivo real y revisa el reporte; si alguna hoja difiere, ajusta `PIPELINE_MAP`/`BITACORA_MAP` en `services/excel.py`.
* **Feriados de Perú**: precargados para 2026-2027 como punto de partida; **verifica el calendario oficial** (se editan en *Configuración → Feriados*).
* **Secretos**: tokens de bot y contraseña SMTP se guardan en la columna JSON `tenants.settings` **sin cifrar**. Para producción cifra la base/volumen o añade cifrado a nivel de campo.
  Las contraseñas de usuario van con bcrypt.
* **Login simple** (JWT, 7 días). No incluye recuperación de contraseña ni 2FA.
* Telegram usa webhook propio en vez de `python-telegram-bot` (decisión de arquitectura multi-bot); la detección de fechas es por reglas/regex (sin LLM).
* Pendiente: Google Calendar y WhatsApp (adaptadores preparados), drag & drop táctil en móvil, RLS de PostgreSQL como segunda barrera de aislamiento.
* `docker compose` y el despliegue **no se ejecutaron** en el entorno de desarrollo (sin Docker); sí se probaron en vivo API (SQLite + `alembic upgrade`) y UI (build de producción + navegador).

## Estructura

```
backend/app/
  alerts/rules.py     reglas R1–R13 (puras)        alerts/engine.py   dedupe, escalamiento, auto-resolución
  services/           notify · bot · excel · reports · scheduler · opportunities · seed
  channels/           telegram · email · stubs (Calendar, WhatsApp)
  routers/            auth_admin (empresas, espacios, usuarios) · workspace · telegram
backend/tests/        reglas, fechas, tenancy, API, importación, notificaciones, E2E Telegram
frontend/app/         login · admin · w/[wid]/{dashboard, pipeline (Kanban/tabla), opportunities/[id], alerts, directory, settings}
```
