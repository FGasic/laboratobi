import os

from pydantic_settings import BaseSettings, SettingsConfigDict


LOCAL_DATABASE_URL = "postgresql+psycopg://laboratobi:laboratobi@db:5432/laboratobi"
PSYCOPG_SCHEME = "postgresql+psycopg://"
POSTGRESQL_SCHEME = "postgresql://"
POSTGRES_SCHEME = "postgres://"


def resolve_database_url(
    database_url: str | None = None,
    app_env: str = "development",
) -> str:
    raw_url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if raw_url is None:
        if app_env.strip().lower() == "development":
            raw_url = LOCAL_DATABASE_URL
        else:
            raise ValueError(
                "DATABASE_URL no esta configurada; el fallback local solo se usa "
                "en desarrollo."
            )

    resolved_url = raw_url.strip()
    if not resolved_url:
        raise ValueError("DATABASE_URL esta vacia despues de aplicar strip().")
    if "${{" in resolved_url or "}}" in resolved_url:
        raise ValueError(
            "DATABASE_URL contiene una referencia de Railway sin resolver. "
            "Configura DATABASE_URL como reference variable del servicio Postgres, "
            "por ejemplo ${{Postgres.DATABASE_URL}}."
        )
    if resolved_url.startswith(PSYCOPG_SCHEME):
        return resolved_url
    if resolved_url.startswith(POSTGRESQL_SCHEME):
        return f"{PSYCOPG_SCHEME}{resolved_url[len(POSTGRESQL_SCHEME):]}"
    if resolved_url.startswith(POSTGRES_SCHEME):
        return f"{PSYCOPG_SCHEME}{resolved_url[len(POSTGRES_SCHEME):]}"
    return resolved_url


class Settings(BaseSettings):
    app_name: str = "LaboraTobi API"
    app_env: str = "development"
    database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]
    pgn_data_dir: str = "data/pgn"
    stockfish_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def resolved_database_url(self) -> str:
        return resolve_database_url(self.database_url, self.app_env)


settings = Settings()
