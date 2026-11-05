# Conectar Vercel + Supabase: dónde sale cada variable

> Los nombres de menús de Supabase y Vercel cambian de vez en cuando; si algo no coincide, usa el buscador del panel.
> **Nunca** pegues contraseñas ni URLs de conexión en chats, issues ni commits.

## Resumen: qué variable viene de dónde

| Variable (proyecto backend en Vercel) | De dónde sale |
|---|---|
| `POSTGRES_URL` (o `DATABASE_URL`) | **Supabase** → Connect → *Transaction pooler* (A) |
| Contraseña de la base de datos | **Supabase** → Database → Settings → *Reset database password* (B) |
| `SECRET_KEY`, `CRON_SECRET` | Las inventas tú: cadena aleatoria de 40+ caracteres (gestor de contraseñas) |
| `BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | Las eliges tú (superadmin de la plataforma) |
| `SCHEDULER_ENABLED` | `false` |
| `CORS_ORIGINS`, `PUBLIC_URL` | **Vercel** → proyecto frontend → Domains (URL del frontend, sin `/` final) |
| `API_PUBLIC_URL` | **Vercel** → proyecto backend → Domains (URL del backend) |
| `NEXT_PUBLIC_API_URL` (proyecto frontend) | La misma URL del backend |
| Token del bot de Telegram | **Telegram** → @BotFather (se pega luego en la app, no en Vercel) |

El backend **no usa** las claves `anon`/`service_role` ni `SUPABASE_URL`: se conecta directo a Postgres. No necesitas copiarlas.

## A. La cadena de conexión (Connect)

1. Entra a https://supabase.com/dashboard e inicia sesión.
2. Elige tu proyecto (en este caso **`micrm_web`**).
3. En la barra superior, botón **Connect**.
4. Pestaña **Connection string** (o *Direct*/*ORMs*, según la versión del panel).
5. En *Method* / *Type* elige **Transaction pooler** (puerto **6543**). Para tareas de migración existe también **Session pooler** (puerto **5432**).
6. Copia la URI. Tiene esta forma:

```
postgresql://postgres.<REF>:[YOUR-PASSWORD]@aws-0-<región>.pooler.supabase.com:6543/postgres
```

7. Reemplaza `[YOUR-PASSWORD]` por la contraseña (sección B) y agrega `?sslmode=require` al final.

Puntos clave:
* El usuario es `postgres.<REF>` (con el sufijo del proyecto), no solo `postgres`.
* **No uses** la *Direct connection* (`db.<REF>.supabase.co`): es IPv6 y Vercel no llega a ella.
* Si la contraseña tiene caracteres especiales, codifícalos: `@`→`%40`, `#`→`%23`, `/`→`%2F`, `:`→`%3A`, `%`→`%25`.
* Si conectaste la **integración Vercel ↔ Supabase**, Vercel ya creó `POSTGRES_URL` (pooler) y `POSTGRES_URL_NON_POOLING`
  por ti: no hace falta copiar nada. Comprueba en Vercel → Settings → Environment Variables que apunten a tu proyecto.

## B. La contraseña de la base de datos

La contraseña se muestra solo al crear el proyecto. Si no la guardaste:

1. Dashboard → tu proyecto → **Project Settings** (engranaje, abajo a la izquierda) → **Database**.
2. Sección **Database password** → **Reset database password**.
3. Genera una nueva, **guárdala en tu gestor de contraseñas** y actualiza `POSTGRES_URL` / `DATABASE_URL` en Vercel.
   (Si la integración de Vercel administra la variable, al resetear debes volver a sincronizarla o pegar la nueva URL a mano.)

## C. Datos del proyecto (referencia)

* **Project ref / ID**: Project Settings → **General** → *Reference ID* (también aparece en la URL del panel: `.../project/<REF>`).
* **Región**: Project Settings → General (determina el host del pooler, p. ej. `us-east-1`).
* **Table Editor** (menú lateral): aquí verás las 18 tablas del CRM y el candado de RLS activado.

## D. Cómo comprobar que quedó bien

1. En Supabase → **Table Editor**: deben existir `tenants`, `users`, `opportunities`, `alerts`… y `alembic_version` con la versión `0002`.
2. En Supabase → **Database → Advisors** (o *Security Advisor*): no debe avisar de «RLS disabled».
3. En Vercel (backend): `https://<backend>.vercel.app/health` → `{"ok":true}`.
4. Entra al frontend con el superadmin: si el login funciona, la conexión a Supabase está bien.
5. Tras crear la empresa, en Supabase → Table Editor → `tenants`/`users` aparecerán filas.

## E. Errores típicos

| Síntoma | Causa |
|---|---|
| `password authentication failed` | usuario sin `.<REF>` o contraseña sin codificar/desactualizada |
| `Tenant or user not found` | `<REF>` o región incorrectos en el host/usuario del pooler |
| `Network is unreachable` | usaste la *Direct connection* (IPv6) |
| Error 500 en el login | falta la variable de BD o redeploy tras agregarla (Vercel solo aplica variables en un deploy nuevo) |
| Tablas sin crear | ejecuta el esquema (ver README, "Desplegar en Vercel") |
