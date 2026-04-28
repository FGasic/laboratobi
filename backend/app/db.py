import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings
from app.services.pgn_utils import compute_pgn_hash

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def sanitize_database_url(database_url: URL | str) -> str:
    try:
        url = database_url if isinstance(database_url, URL) else make_url(database_url)
        return url.render_as_string(hide_password=True)
    except Exception:
        return "<DATABASE_URL invalida o no sanitizable>"


try:
    database_connection = settings.resolved_database_connection
except ValueError:
    logger.exception("No se pudo resolver la conexion Postgres para SQLAlchemy.")
    raise

database_url = database_connection.url
logger.info("Ruta de conexion Postgres usada: %s", database_connection.source)
logger.info("Usando DATABASE_URL: %s", sanitize_database_url(database_url))

try:
    engine = create_engine(database_url, pool_pre_ping=True)
except Exception:
    logger.exception(
        "No se pudo crear el engine de SQLAlchemy usando la ruta %s. Revisa "
        "PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE o DATABASE_URL, segun "
        "corresponda.",
        database_connection.source,
    )
    raise

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

GAME_COMPATIBILITY_COLUMNS: dict[str, str] = {
    "source_type": "ALTER TABLE games ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)",
    "external_id": "ALTER TABLE games ADD COLUMN IF NOT EXISTS external_id VARCHAR(50)",
    "source_url": "ALTER TABLE games ADD COLUMN IF NOT EXISTS source_url TEXT",
    "round_id": "ALTER TABLE games ADD COLUMN IF NOT EXISTS round_id VARCHAR(50)",
    "tournament_id": "ALTER TABLE games ADD COLUMN IF NOT EXISTS tournament_id VARCHAR(50)",
    "pgn_hash": "ALTER TABLE games ADD COLUMN IF NOT EXISTS pgn_hash VARCHAR(64)",
}

CRITICAL_MOMENT_COMPATIBILITY_COLUMNS: dict[str, str] = {
    "validation_status": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_status VARCHAR(20)"
    ),
    "validation_invalid_reason": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_invalid_reason VARCHAR(80)"
    ),
    "validation_played_move_san": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_played_move_san VARCHAR(32)"
    ),
    "validation_engine_best_move": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_engine_best_move VARCHAR(32)"
    ),
    "validation_engine_principal_variation_count": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_engine_principal_variation_count INTEGER"
    ),
    "validation_best_eval_cp": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_best_eval_cp INTEGER"
    ),
    "validation_played_eval_cp": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_played_eval_cp INTEGER"
    ),
    "validation_objective_gap_cp": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_objective_gap_cp INTEGER"
    ),
    "validation_objective_gap_depth": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_objective_gap_depth INTEGER"
    ),
    "validation_equivalent_move_band_reject": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_equivalent_move_band_reject BOOLEAN"
    ),
    "validation_borderline_recheck": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_borderline_recheck BOOLEAN"
    ),
    "validation_depth24_gap_cp": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validation_depth24_gap_cp INTEGER"
    ),
    "ranking_phase": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_phase VARCHAR(40)"
    ),
    "ranking_phase_preference_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_phase_preference_score DOUBLE PRECISION"
    ),
    "ranking_final_candidate_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_final_candidate_score DOUBLE PRECISION"
    ),
    "ranking_objective_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_objective_score DOUBLE PRECISION"
    ),
    "ranking_transferable_idea_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_transferable_idea_score DOUBLE PRECISION"
    ),
    "ranking_objective_gap_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_objective_gap_score DOUBLE PRECISION"
    ),
    "ranking_difficulty_adequacy_score": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "ranking_difficulty_adequacy_score DOUBLE PRECISION"
    ),
    "validated_at": (
        "ALTER TABLE critical_moments ADD COLUMN IF NOT EXISTS "
        "validated_at TIMESTAMP WITH TIME ZONE"
    ),
}


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_games_table_compatibility()
    ensure_critical_moments_table_compatibility()
    backfill_game_pgn_hashes()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_games_table_compatibility() -> None:
    inspector = inspect(engine)
    if "games" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("games")}
    statements = [
        statement
        for column_name, statement in GAME_COMPATIBILITY_COLUMNS.items()
        if column_name not in existing_columns
    ]
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_critical_moments_table_compatibility() -> None:
    inspector = inspect(engine)
    if "critical_moments" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("critical_moments")
    }
    statements = [
        statement
        for column_name, statement in CRITICAL_MOMENT_COMPATIBILITY_COLUMNS.items()
        if column_name not in existing_columns
    ]
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def backfill_game_pgn_hashes() -> None:
    from app.models import Game

    with SessionLocal() as db:
        games_without_hash = list(
            db.scalars(select(Game).where(Game.pgn_hash.is_(None))).all()
        )
        if not games_without_hash:
            return

        for game in games_without_hash:
            if not game.pgn_text:
                continue
            game.pgn_hash = compute_pgn_hash(game.pgn_text)

        db.commit()
