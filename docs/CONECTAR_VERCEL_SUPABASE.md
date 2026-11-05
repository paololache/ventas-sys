# Conectar Vercel + Supabase

Ver la guía paso a paso entregada en la conversación; resumen:

1. Supabase → **Connect** → copia el *Session pooler* (puerto 5432) y el *Transaction pooler* (puerto 6543). Usuario: `postgres.<ref>`.
2. Migrar desde tu máquina con el Session pooler: `cd backend && DATABASE_URL='postgresql://postgres.<ref>:<CLAVE-URL-ENCODED>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require' alembic upgrade head`
3. Vercel (proyecto backend): `DATABASE_URL` = Transaction pooler (6543), `SECRET_KEY`, `BOOTSTRAP_ADMIN_*`, `SCHEDULER_ENABLED=false`, `CRON_SECRET`, `CORS_ORIGINS`, `PUBLIC_URL`, `API_PUBLIC_URL`. Redeploy.
4. Vercel (proyecto frontend): `NEXT_PUBLIC_API_URL` = URL del backend. Redeploy.
5. Verificar `GET <backend>/health` y entrar al frontend con el superadmin.
