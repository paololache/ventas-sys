from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # La integración Vercel↔Supabase inyecta POSTGRES_URL (pooler); DATABASE_URL tiene prioridad si existe
    database_url: str = Field("sqlite:///./crm.db", validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"))
    secret_key: str = "cambia-esto-en-produccion"
    token_expire_minutes: int = 60 * 24 * 7
    default_timezone: str = "America/Lima"
    public_url: str = "http://localhost:3000"  # base para el botón "Abrir en la app"
    api_public_url: str = "http://localhost:8000"  # base para webhooks de Telegram
    cors_origins: str = "http://localhost:3000"

    # En Vercel (serverless) no hay proceso permanente: desactiva el scheduler y llama a /api/cron/tick
    scheduler_enabled: bool = True
    cron_secret: str = ""  # protege /api/cron/tick (Vercel Cron lo envía como Bearer)
    scheduler_interval_minutes: int = 15

    # Fallback SMTP global (cada empresa puede definir el suyo en su configuración)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    telegram_api_base: str = "https://api.telegram.org"

    # Usuario superadmin de la plataforma, creado al arrancar si no existe
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
