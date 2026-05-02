from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Annotated

import chess
import chess.pgn
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import CriticalMoment, Game
from app.schemas.game import (
    BroadcastSessionGameResponse,
    BroadcastSessionResponse,
    CriticalMomentCreateRequest,
    CriticalMomentDevSeedRequest,
    CriticalMomentResponse,
    GameImportResponse,
    GamePositionDetailResponse,
    GamePositionResponse,
    RecentBroadcastGameResponse,
    GameResponse,
)
from app.services.pgn_utils import compute_pgn_hash
from app.services.critical_moment_review import (
    build_critical_moment_review_payload_from_position_pair,
)
from app.services.critical_moment_metadata import (
    apply_critical_moment_validation_metadata,
    has_valid_critical_moment_metadata,
    log_persisted_critical_moment_metadata_validation,
)
from app.services.critical_moment_validation import (
    BASELINE_DEPTH,
    OBJECTIVE_GAP_THRESHOLD_CP,
    is_initial_eval_in_critical_range,
    log_critical_moment_review_runtime_failed,
    log_critical_moment_validation,
    validate_critical_moment_review,
    validate_critical_moment_review_with_objective_gap,
)
from app.services.stockfish import evaluate_fens

router = APIRouter(prefix="/games", tags=["games"])
SessionDep = Annotated[Session, Depends(get_db)]
BROADCAST_STUDY_SESSION_LIMIT = 3
BROADCAST_STUDY_REVIEW_DEPTH = 25


@router.post("/import-local-pgns", response_model=GameImportResponse)
def import_local_pgns(db: SessionDep) -> GameImportResponse:
    pgn_dir = Path(settings.pgn_data_dir)
    pgn_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(pgn_dir.glob("*.pgn"))
    imported_count = 0
    skipped_count = 0

    for pgn_file in files:
        with pgn_file.open(encoding="utf-8-sig", errors="replace") as handle:
            while True:
                parsed_game = chess.pgn.read_game(handle)
                if parsed_game is None:
                    break

                pgn_text = export_pgn(parsed_game)
                if not pgn_text:
                    skipped_count += 1
                    continue

                existing_game = db.scalar(
                    select(Game).where(Game.pgn_text == pgn_text).limit(1)
                )
                if existing_game is not None:
                    skipped_count += 1
                    continue

                game = Game(
                    event_name=clean_header(parsed_game.headers.get("Event")),
                    white_player=clean_header(parsed_game.headers.get("White")),
                    black_player=clean_header(parsed_game.headers.get("Black")),
                    result=clean_header(parsed_game.headers.get("Result"), fallback="*"),
                    pgn_text=pgn_text,
                    pgn_hash=compute_pgn_hash(pgn_text),
                )
                db.add(game)
                imported_count += 1

    db.commit()

    return GameImportResponse(
        pgn_dir=str(pgn_dir),
        files_found=len(files),
        imported_count=imported_count,
        skipped_count=skipped_count,
    )


@router.get("", response_model=list[GameResponse])
def list_games(db: SessionDep) -> list[Game]:
    statement = select(Game).order_by(Game.created_at.desc(), Game.id.desc())
    return list(db.scalars(statement).all())


@router.get("/broadcast/recent", response_model=list[RecentBroadcastGameResponse])
def list_recent_broadcast_games(db: SessionDep) -> list[RecentBroadcastGameResponse]:
    active_moments_count = (
        select(func.count(CriticalMoment.id))
        .where(
            CriticalMoment.game_id == Game.id,
            CriticalMoment.is_active.is_(True),
        )
        .correlate(Game)
        .scalar_subquery()
    )
    statement = (
        select(
            Game.id,
            Game.event_name,
            Game.white_player,
            Game.black_player,
            Game.result,
            Game.created_at,
            Game.source_type,
            Game.external_id,
            Game.source_url,
            Game.round_id,
            Game.tournament_id,
            Game.pgn_text,
            active_moments_count.label("critical_moments_count"),
        )
        .where(Game.source_type == "broadcast")
        .order_by(Game.created_at.desc(), Game.id.desc())
        .limit(3)
    )
    rows = db.execute(statement).all()
    return [
        RecentBroadcastGameResponse(
            id=row.id,
            display_event_name=build_display_event_name(
                event_name=row.event_name,
                tournament_id=row.tournament_id,
                round_id=row.round_id,
            ),
            event_name=row.event_name,
            white_player=row.white_player,
            black_player=row.black_player,
            result=row.result,
            critical_moments_count=row.critical_moments_count or 0,
            created_at=row.created_at,
            source_type=row.source_type,
            external_id=row.external_id,
            source_url=row.source_url,
            round_id=row.round_id,
            tournament_id=row.tournament_id,
        )
        for row in rows
    ]


@router.get("/broadcast/session", response_model=BroadcastSessionResponse)
def get_broadcast_study_session(db: SessionDep) -> BroadcastSessionResponse:
    active_moments_count = (
        select(func.count(CriticalMoment.id))
        .where(
            CriticalMoment.game_id == Game.id,
            CriticalMoment.is_active.is_(True),
        )
        .correlate(Game)
        .scalar_subquery()
    )
    current_round_id = get_current_broadcast_round_id(db)
    statement = (
        select(
            Game,
            CriticalMoment,
        )
        .join(CriticalMoment, CriticalMoment.game_id == Game.id)
        .where(Game.source_type == "broadcast")
        .where(CriticalMoment.is_active.is_(True))
        .where(active_moments_count == 1)
        .where(CriticalMoment.validation_status == "valid")
        .where(CriticalMoment.validation_invalid_reason.is_(None))
        .where(CriticalMoment.validation_engine_best_move.is_not(None))
        .where(CriticalMoment.validation_engine_principal_variation_count > 0)
        .where(
            CriticalMoment.validation_objective_gap_cp
            >= OBJECTIVE_GAP_THRESHOLD_CP
        )
        .where(CriticalMoment.validation_equivalent_move_band_reject.is_(False))
        .where(CriticalMoment.ranking_final_candidate_score.is_not(None))
        .where(CriticalMoment.ranking_transferable_idea_score.is_not(None))
        .where(CriticalMoment.ranking_difficulty_adequacy_score.is_not(None))
        .order_by(
            CriticalMoment.ranking_final_candidate_score.desc(),
            CriticalMoment.validation_objective_gap_cp.desc(),
            CriticalMoment.ranking_transferable_idea_score.desc(),
            CriticalMoment.ranking_difficulty_adequacy_score.desc(),
            CriticalMoment.ply_index.asc(),
            Game.id.desc(),
        )
    )

    if current_round_id is not None:
        statement = statement.where(Game.round_id == current_round_id)

    games: list[BroadcastSessionGameResponse] = []
    for game, moment in db.execute(statement).all():
        valid_critical_moments = filter_valid_study_critical_moments(
            game_id=game.id,
            pgn_text=game.pgn_text,
            active_moments=[moment],
        )
        if not valid_critical_moments:
            continue

        if not has_valid_depth25_study_review(game=game, moment=moment):
            continue

        games.append(
            BroadcastSessionGameResponse(
                id=game.id,
                display_event_name=build_display_event_name(
                    event_name=game.event_name,
                    tournament_id=game.tournament_id,
                    round_id=game.round_id,
                ),
                event_name=game.event_name,
                white_player=game.white_player,
                black_player=game.black_player,
                result=game.result,
                critical_moments_count=len(valid_critical_moments),
                created_at=game.created_at,
                source_type=game.source_type,
                external_id=game.external_id,
                source_url=game.source_url,
                round_id=game.round_id,
                tournament_id=game.tournament_id,
                critical_moments=valid_critical_moments,
            )
        )
        if len(games) == BROADCAST_STUDY_SESSION_LIMIT:
            break

    if len(games) != BROADCAST_STUDY_SESSION_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Broadcast study session needs exactly 3 valid ranked games."
                ),
                "round_id": current_round_id,
                "required_games": BROADCAST_STUDY_SESSION_LIMIT,
                "selected_games": len(games),
            },
        )

    return BroadcastSessionResponse(games=games)


def get_current_broadcast_round_id(db: Session) -> str | None:
    return db.scalar(
        select(Game.round_id)
        .where(
            Game.source_type == "broadcast",
            Game.round_id.is_not(None),
        )
        .order_by(Game.created_at.desc(), Game.id.desc())
        .limit(1)
    )


def filter_valid_study_critical_moments(
    *,
    game_id: int,
    pgn_text: str,
    active_moments: list[CriticalMoment],
) -> list[CriticalMoment]:
    valid_moments: list[CriticalMoment] = []
    for moment in active_moments:
        is_valid = has_valid_critical_moment_metadata(moment)
        log_persisted_critical_moment_metadata_validation(
            game_id=game_id,
            moment=moment,
            valid=is_valid,
        )
        if is_valid:
            valid_moments.append(moment)

    return valid_moments


def has_valid_depth25_study_review(
    *,
    game: Game,
    moment: CriticalMoment,
) -> bool:
    try:
        parsed_game = parse_pgn_text(game.pgn_text)
        positions = build_game_positions(parsed_game)
    except HTTPException:
        return False

    position_index = moment.ply_index - 1
    previous_index = position_index - 1
    if previous_index < 0 or position_index >= len(positions):
        return False

    evaluations = evaluate_fens(
        [
            positions[previous_index].fen,
            positions[position_index].fen,
        ],
        BROADCAST_STUDY_REVIEW_DEPTH,
    )
    evaluation_before = evaluations[0]
    evaluation_after = evaluations[1]
    initial_eval_cp = get_optional_int(evaluation_before, "evaluation_white_cp")
    if not is_initial_eval_in_critical_range(initial_eval_cp):
        return False

    review_payload = build_critical_moment_review_payload_from_position_pair(
        ply_index=moment.ply_index,
        position_before=positions[previous_index],
        position_after=positions[position_index],
        evaluation_before=evaluation_before,
        evaluation_after=evaluation_after,
    )
    if review_payload is None:
        return False

    engine_name = evaluation_before.get("engine_name")
    depth_used = get_optional_int(evaluation_before, "depth_used")
    played_move_eval_cp = get_optional_int(evaluation_after, "evaluation_white_cp")
    played_move_mate = get_optional_int(evaluation_after, "mate_white")
    return (
        isinstance(engine_name, str)
        and bool(engine_name.strip())
        and depth_used is not None
        and depth_used >= BROADCAST_STUDY_REVIEW_DEPTH
        and bool(review_payload.get("engine_best_move"))
        and bool(review_payload.get("engine_principal_variation"))
        and (played_move_eval_cp is not None or played_move_mate is not None)
    )


def get_optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


@router.get("/{game_id}", response_model=GameResponse)
def get_game(game_id: int, db: SessionDep) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    return game


@router.get(
    "/{game_id}/critical-moments",
    response_model=list[CriticalMomentResponse],
)
def list_critical_moments(
    game_id: int,
    db: SessionDep,
) -> list[CriticalMoment]:
    get_game_or_404(game_id, db)
    statement = (
        select(CriticalMoment)
        .where(
            CriticalMoment.game_id == game_id,
            CriticalMoment.is_active.is_(True),
        )
        .order_by(CriticalMoment.moment_number.asc(), CriticalMoment.ply_index.asc())
    )
    return list(db.scalars(statement).all())


@router.post(
    "/{game_id}/critical-moments",
    response_model=CriticalMomentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_critical_moment(
    game_id: int,
    payload: CriticalMomentCreateRequest,
    db: SessionDep,
) -> CriticalMoment:
    game = get_game_or_404(game_id, db)
    validate_game_ply_index(game, payload.ply_index)

    duplicate = db.scalar(
        select(CriticalMoment)
        .where(
            CriticalMoment.game_id == game_id,
            CriticalMoment.ply_index == payload.ply_index,
            CriticalMoment.is_active.is_(True),
        )
        .limit(1)
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Critical moment already exists for this ply_index.",
        )

    validation_result = None
    if payload.is_active:
        validation_result = validate_critical_moment_persistence_or_raise(
            game,
            payload.ply_index,
        )

    moment = CriticalMoment(
        game_id=game_id,
        ply_index=payload.ply_index,
        moment_number=payload.moment_number or get_next_moment_number(game_id, db),
        title=payload.title,
        label=payload.label,
        notes=payload.notes,
        is_active=payload.is_active,
    )
    if validation_result is not None:
        validation, review_payload = validation_result
        apply_critical_moment_validation_metadata(
            moment=moment,
            validation=validation,
            review_payload=review_payload,
        )
    db.add(moment)
    db.commit()
    db.refresh(moment)
    return moment


@router.post(
    "/{game_id}/critical-moments/dev-seed",
    response_model=list[CriticalMomentResponse],
)
def seed_critical_moments(
    game_id: int,
    db: SessionDep,
    payload: CriticalMomentDevSeedRequest | None = None,
) -> list[CriticalMoment]:
    game = get_game_or_404(game_id, db)
    seed_payload = payload or CriticalMomentDevSeedRequest()

    if any(ply_index < 1 for ply_index in seed_payload.ply_indexes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All ply_indexes must be positive integers.",
        )

    validation_by_ply_index = {}
    for ply_index in seed_payload.ply_indexes:
        validate_game_ply_index(game, ply_index)
        validation_by_ply_index[ply_index] = validate_critical_moment_persistence_or_raise(
            game,
            ply_index,
        )

    active_moments = db.scalars(
        select(CriticalMoment).where(
            CriticalMoment.game_id == game_id,
            CriticalMoment.is_active.is_(True),
        )
    ).all()
    for moment in active_moments:
        moment.is_active = False

    seeded_moments: list[CriticalMoment] = []
    for index, ply_index in enumerate(seed_payload.ply_indexes, start=1):
        moment = CriticalMoment(
            game_id=game_id,
            ply_index=ply_index,
            moment_number=index,
            title=f"Momento critico {index}",
            label="Curado manual",
            notes="Semilla local para revisar el visor.",
            is_active=True,
        )
        validation, review_payload = validation_by_ply_index[ply_index]
        apply_critical_moment_validation_metadata(
            moment=moment,
            validation=validation,
            review_payload=review_payload,
        )
        db.add(moment)
        seeded_moments.append(moment)

    db.commit()
    for moment in seeded_moments:
        db.refresh(moment)

    return seeded_moments


@router.delete(
    "/{game_id}/critical-moments/{moment_id}",
    response_model=CriticalMomentResponse,
)
def deactivate_critical_moment(
    game_id: int,
    moment_id: int,
    db: SessionDep,
) -> CriticalMoment:
    get_game_or_404(game_id, db)
    moment = db.get(CriticalMoment, moment_id)
    if moment is None or moment.game_id != game_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Critical moment not found.",
        )

    moment.is_active = False
    db.commit()
    db.refresh(moment)
    return moment


@router.get("/{game_id}/positions", response_model=list[GamePositionResponse])
def list_game_positions(game_id: int, db: SessionDep) -> list[GamePositionResponse]:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    parsed_game = parse_pgn_text(game.pgn_text)
    return build_game_positions(parsed_game)


@router.get(
    "/{game_id}/positions/{ply_index}",
    response_model=GamePositionDetailResponse,
)
def get_game_position(
    game_id: int,
    ply_index: int,
    db: SessionDep,
) -> GamePositionDetailResponse:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    parsed_game = parse_pgn_text(game.pgn_text)
    position = get_position_at_ply(parsed_game, ply_index)

    return GamePositionDetailResponse(
        game_id=game.id,
        event_name=game.event_name,
        white_player=game.white_player,
        black_player=game.black_player,
        result=game.result,
        ply_index=position.ply_index,
        fullmove_number=position.fullmove_number,
        san_move=position.san_move,
        from_square=position.from_square,
        to_square=position.to_square,
        fen=position.fen,
        side_to_move=position.side_to_move,
        next_moves=get_next_san_moves(parsed_game, ply_index, limit=3),
    )


def build_game_positions(parsed_game: chess.pgn.Game) -> list[GamePositionResponse]:
    board = parsed_game.board()
    positions: list[GamePositionResponse] = []

    for ply_index, move in enumerate(parsed_game.mainline_moves(), start=1):
        if move not in board.legal_moves:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Illegal move while reconstructing PGN "
                    f"at ply {ply_index}: {move.uci()}."
                ),
            )

        san_move = board.san(move)
        fullmove_number = board.fullmove_number
        board.push(move)

        positions.append(
            GamePositionResponse(
                ply_index=ply_index,
                fullmove_number=fullmove_number,
                san_move=san_move,
                from_square=chess.square_name(move.from_square),
                to_square=chess.square_name(move.to_square),
                fen=board.fen(),
                side_to_move="w" if board.turn == chess.WHITE else "b",
            )
        )

    return positions


def get_position_at_ply(
    parsed_game: chess.pgn.Game,
    ply_index: int,
) -> GamePositionResponse:
    if ply_index < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid ply_index: must be at least 1.",
        )

    positions = build_game_positions(parsed_game)
    if not positions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid ply_index: this game has no moves.",
        )

    if ply_index > len(positions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Invalid ply_index: must be between "
                f"1 and {len(positions)} for this game."
            ),
        )

    return positions[ply_index - 1]


def get_next_san_moves(
    parsed_game: chess.pgn.Game,
    ply_index: int,
    limit: int,
) -> list[str]:
    moves = list(parsed_game.mainline_moves())
    board = parsed_game.board()

    for current_ply, move in enumerate(moves[:ply_index], start=1):
        if move not in board.legal_moves:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Illegal move while reconstructing PGN "
                    f"at ply {current_ply}: {move.uci()}."
                ),
            )
        board.push(move)

    next_moves: list[str] = []
    for offset, move in enumerate(moves[ply_index : ply_index + limit], start=1):
        continuation_ply = ply_index + offset
        if move not in board.legal_moves:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Illegal move while reading continuation "
                    f"at ply {continuation_ply}: {move.uci()}."
                ),
            )

        next_moves.append(board.san(move))
        board.push(move)

    return next_moves


def parse_pgn_text(pgn_text: str) -> chess.pgn.Game:
    try:
        parsed_game = chess.pgn.read_game(StringIO(pgn_text))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse PGN text: {exc}",
        ) from exc

    if parsed_game is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse PGN text: no game found.",
        )

    if parsed_game.errors:
        parser_errors = "; ".join(str(error) for error in parsed_game.errors)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PGN contains illegal or invalid moves: {parser_errors}",
        )

    return parsed_game


def export_pgn(parsed_game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(
        headers=True,
        variations=True,
        comments=True,
    )
    return parsed_game.accept(exporter).strip()


def clean_header(value: str | None, fallback: str = "Unknown") -> str:
    if value is None:
        return fallback

    clean_value = value.strip()
    if not clean_value or clean_value == "?":
        return fallback

    return clean_value


def build_display_event_name(
    *,
    event_name: str | None,
    tournament_id: str | None,
    round_id: str | None,
) -> str:
    normalized_event_name = (event_name or "").strip()
    if normalized_event_name and normalized_event_name.lower() not in {
        "unknown",
        "unknown event",
    }:
        return normalized_event_name

    if tournament_id:
        return f"Broadcast {tournament_id}"

    if round_id:
        return f"Ronda {round_id}"

    return "Evento sin nombre"


def get_game_or_404(game_id: int, db: Session) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    return game


def validate_game_ply_index(game: Game, ply_index: int) -> None:
    parsed_game = parse_pgn_text(game.pgn_text)
    get_position_at_ply(parsed_game, ply_index)


def validate_critical_moment_persistence_or_raise(
    game: Game,
    ply_index: int,
):
    try:
        parsed_game = parse_pgn_text(game.pgn_text)
        positions = build_game_positions(parsed_game)
        position_index = ply_index - 1
        previous_index = position_index - 1
        if previous_index < 0 or position_index >= len(positions):
            raise ValueError("Invalid ply_index for critical moment review.")

        evaluation_before = evaluate_fens(
            [positions[previous_index].fen],
            BASELINE_DEPTH,
        )[0]
    except Exception as exc:
        log_critical_moment_review_runtime_failed(
            game_id=game.id,
            ply_index=ply_index,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not validate critical moment review: {exc}",
        ) from exc

    review_payload = build_critical_moment_review_payload_from_position_pair(
        ply_index=ply_index,
        position_before=positions[previous_index],
        position_after=positions[position_index],
        evaluation_before=evaluation_before,
    )
    if review_payload is None:
        log_critical_moment_review_runtime_failed(
            game_id=game.id,
            ply_index=ply_index,
            error="persistence_review_payload_missing",
        )
        validation = validate_critical_moment_review(
            played_move_san=None,
            engine_best_move=None,
            engine_principal_variation=[],
            review_runtime_ok=False,
        )
    else:
        validation = validate_critical_moment_review_with_objective_gap(
            fen_before=review_payload["fen_before"],
            played_move_san=review_payload["played_move_san"],
            engine_best_move=review_payload["engine_best_move"],
            engine_principal_variation=review_payload["engine_principal_variation"],
        )

    log_critical_moment_validation(
        game_id=game.id,
        ply_index=ply_index,
        validation=validation,
    )
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Invalid critical moment review: "
                f"{validation.invalid_reason}."
            ),
        )

    return validation, review_payload


def get_next_moment_number(game_id: int, db: Session) -> int:
    current_max = db.scalar(
        select(func.max(CriticalMoment.moment_number)).where(
            CriticalMoment.game_id == game_id,
            CriticalMoment.is_active.is_(True),
        )
    )
    return (current_max or 0) + 1
