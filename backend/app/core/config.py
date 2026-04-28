import os
from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


LOCAL_DATABASE_URL = "postgresql+psycopg://laboratobi:laboratobi@db:5432/laboratobi"
PSYCOPG_SCHEME = "postgresql+psycopg://"
POSTGRESQL_SCHEME = "postgresql://"
POSTGRES_SCHEME = "postgres://"
DatabaseConnectionSource = Literal["pg_components", "database_url", "local_fallback"]


@dataclass(frozen=True)
class ResolvedDatabaseConnection:
    url: URL | str
    source: DatabaseConnectionSource


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_database_url(database_url: str) -> str:
    resolved_url = database_url.strip()
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


def resolve_database_connection(
    database_url: str | None = None,
    app_env: str = "development",
    pghost: str | None = None,
    pgport: str | None = None,
    pguser: str | None = None,
    pgpassword: str | None = None,
    pgdatabase: str | None = None,
) -> ResolvedDatabaseConnection:
    pg_components = {
        "PGHOST": _strip_or_none(pghost if pghost is not None else os.getenv("PGHOST")),
        "PGPORT": _strip_or_none(pgport if pgport is not None else os.getenv("PGPORT")),
        "PGUSER": _strip_or_none(pguser if pguser is not None else os.getenv("PGUSER")),
        "PGPASSWORD": _strip_or_none(
            pgpassword if pgpassword is not None else os.getenv("PGPASSWORD")
        ),
        "PGDATABASE": _strip_or_none(
            pgdatabase if pgdatabase is not None else os.getenv("PGDATABASE")
        ),
    }
    provided_pg_components = [
        name for name, value in pg_components.items() if value is not None
    ]
    if provided_pg_components:
        missing_pg_components = [
            name for name, value in pg_components.items() if value is None
        ]
        if missing_pg_components:
            raise ValueError(
                "Configuracion Postgres incompleta: faltan "
                f"{', '.join(missing_pg_components)}. Define PGHOST, PGPORT, "
                "PGUSER, PGPASSWORD y PGDATABASE, o elimina los PG* y usa DATABASE_URL."
            )

        try:
            port = int(pg_components["PGPORT"])
        except (TypeError, ValueError) as exc:
            raise ValueError("PGPORT debe ser un entero valido.") from exc

        return ResolvedDatabaseConnection(
            url=URL.create(
                drivername="postgresql+psycopg",
                username=pg_components["PGUSER"],
                password=pg_components["PGPASSWORD"],
                host=pg_components["PGHOST"],
                port=port,
                database=pg_components["PGDATABASE"],
            ),
            source="pg_components",
        )

    raw_url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if raw_url is not None:
        return ResolvedDatabaseConnection(
            url=_normalize_database_url(raw_url),
            source="database_url",
        )

    if app_env.strip().lower() == "development":
        return ResolvedDatabaseConnection(
            url=LOCAL_DATABASE_URL,
            source="local_fallback",
        )

    raise ValueError(
        "No hay configuracion de Postgres. Define PGHOST, PGPORT, PGUSER, "
        "PGPASSWORD y PGDATABASE, o configura DATABASE_URL."
    )


def resolve_database_url(
    database_url: str | None = None,
    app_env: str = "development",
) -> URL | str:
    return resolve_database_connection(database_url, app_env).url


class Settings(BaseSettings):
    app_name: str = "LaboraTobi API"
    app_env: str = "development"
    database_url: str | None = None
    pghost: str | None = Field(default=None, validation_alias="PGHOST")
    pgport: str | None = Field(default=None, validation_alias="PGPORT")
    pguser: str | None = Field(default=None, validation_alias="PGUSER")
    pgpassword: str | None = Field(default=None, validation_alias="PGPASSWORD")
    pgdatabase: str | None = Field(default=None, validation_alias="PGDATABASE")
    cors_origins: list[str] = ["http://localhost:3000"]
    pgn_data_dir: str = "data/pgn"
    stockfish_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def resolved_database_connection(self) -> ResolvedDatabaseConnection:
        return resolve_database_connection(
            database_url=self.database_url,
            app_env=self.app_env,
            pghost=self.pghost,
            pgport=self.pgport,
            pguser=self.pguser,
            pgpassword=self.pgpassword,
            pgdatabase=self.pgdatabase,
        )

    @property
    def resolved_database_url(self) -> URL | str:
        return self.resolved_database_connection.url


settings = Settings()
