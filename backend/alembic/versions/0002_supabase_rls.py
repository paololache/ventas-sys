"""Activa RLS (sin políticas) en todas las tablas cuando la BD es PostgreSQL/Supabase.

Supabase expone el esquema `public` vía su API REST pública (clave anon). Sin RLS, cualquiera con esa clave podría
leer/escribir. Con RLS activo y sin políticas, la API pública no ve nada; este backend conecta con el rol `postgres`
(que ignora RLS), así que no le afecta.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        DO $$ DECLARE t record; BEGIN
          FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
          END LOOP;
        END $$;
    """)


def downgrade() -> None:
    pass
