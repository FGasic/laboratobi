from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LaboraTobi API"
    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://laboratobi:laboratobi@db:5432/laboratobi"
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    pgn_data_dir: str = "data/pgn"
    stockfish_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
