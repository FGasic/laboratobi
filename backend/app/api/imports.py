from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.analysis import generate_critical_moments_for_game
from app.db import get_db
from app.models import Game
from app.schemas.imports import (
    BroadcastImportRequest,
    BroadcastImportResponse,
    BroadcastPreviewRequest,
    BroadcastPreviewResponse,
)
from app.services.broadcast_quality import evaluate_broadcast_quality
from app.services.lichess_broadcast import (
    BroadcastPreviewError,
    fetch_broadcast_round_data,
    serialize_broadcast_game,
)

router = APIRouter(prefix="/imports", tags=["imports"])
SessionDep = Annotated[Session, Depends(get_db)]


@router.post("/broadcast/preview", response_model=BroadcastPreviewResponse)
def preview_broadcast_import(
    payload: BroadcastPreviewRequest,
) -> BroadcastPreviewResponse:
    try:
        round_data = fetch_broadcast_round_data(
            round_id=payload.round_id.strip() if payload.round_id else None,
            round_url=payload.round_url,
        )
    except BroadcastPreviewError as exc:
        raise_http_from_broadcast_error(exc)

    preview_games = [
        serialize_broadcast_game(
            game,
            include_pgn_text=payload.include_pgn_text,
        )
        for game in round_data["games"][: payload.limit]
    ]

    return BroadcastPreviewResponse(
        source_type=round_data["source_type"],
        source_url=round_data["source_url"],
        source_host=round_data["source_host"],
        round_id=round_data["round_id"],
        round_url=round_data["round_url"],
        tournament_id=round_data["tournament_id"],
        tournament_name=round_data["tournament_name"],
        round_name=round_data["round_name"],
        games_found=round_data["games_found"],
        games_previewed=len(preview_games),
        quality=evaluate_broadcast_quality(round_data),
        games=preview_games,
    )


@router.post("/broadcast/import", response_model=BroadcastImportResponse)
def import_broadcast_games(
    payload: BroadcastImportRequest,
    db: SessionDep,
) -> BroadcastImportResponse:
    try:
        round_data = fetch_broadcast_round_data(
            round_id=payload.round_id,
            round_url=payload.round_url,
        )
    except BroadcastPreviewError as exc:
        raise_http_from_broadcast_error(exc)

    quality = evaluate_broadcast_quality(round_data)
    if not payload.allow_low_quality and not quality["is_serious_gm_broadcast"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "Broadcast round did not pass the serious master broadcast "
                    "quality filter."
                ),
                "quality": quality,
            },
        )

    games_by_external_id = {
        game["external_id"]: game
        for game in round_data["games"]
        if game.get("external_id")
    }
    requested_external_ids = resolve_requested_external_ids(
        round_data=round_data,
        explicit_external_ids=payload.external_ids,
        limit=payload.limit,
    )
    imported_games: list[dict[str, object]] = []
    skipped_games: list[dict[str, object]] = []

    for external_id in requested_external_ids:
        game_data = games_by_external_id.get(external_id)
        if game_data is None:
            skipped_games.append(
                {
                    "external_id": external_id,
                    "reason": "not_found_in_round",
                    "existing_game_id": None,
                }
            )
            continue

        duplicate_by_source = db.scalar(
            select(Game)
            .where(
                Game.source_type == "broadcast",
                Game.external_id == external_id,
            )
            .limit(1)
        )
        if duplicate_by_source is not None:
            skipped_games.append(
                {
                    "external_id": external_id,
                    "reason": "already_exists_by_source",
                    "existing_game_id": duplicate_by_source.id,
                }
            )
            continue

        duplicate_by_hash = db.scalar(
            select(Game)
            .where(Game.pgn_hash == game_data["pgn_hash"])
            .limit(1)
        )
        if duplicate_by_hash is not None:
            skipped_games.append(
                {
                    "external_id": external_id,
                    "reason": "already_exists_by_pgn_hash",
                    "existing_game_id": duplicate_by_hash.id,
                }
            )
            continue

        game = Game(
            event_name=game_data["event_name"],
            white_player=game_data["white_player"],
            black_player=game_data["black_player"],
            result=game_data["result"],
            pgn_text=game_data["pgn_text"],
            source_type="broadcast",
            external_id=external_id,
            source_url=game_data["game_url"] or round_data["round_url"],
            round_id=round_data["round_id"],
            tournament_id=round_data["tournament_id"],
            pgn_hash=game_data["pgn_hash"],
        )
        db.add(game)
        db.flush()

        imported_games.append(
            {
                "id": game.id,
                "event_name": game.event_name,
                "white_player": game.white_player,
                "black_player": game.black_player,
                "result": game.result,
                "external_id": game.external_id,
                "source_url": game.source_url,
                "analysis_requested": False,
                "critical_moments_generated": False,
                "generated_moments_count": 0,
                "generated_moment_ply_indexes": [],
                "analysis_error": None,
            }
        )

    db.commit()

    analyzed_count = 0
    total_generated_moments = 0
    if payload.generate_critical_moments:
        for imported_game in imported_games:
            imported_game["analysis_requested"] = True

            game_id = int(imported_game["id"])
            game = db.get(Game, game_id)
            if game is None:
                imported_game["analysis_error"] = (
                    "Imported game not found after commit."
                )
                continue

            try:
                analysis_result = generate_critical_moments_for_game(
                    db=db,
                    game=game,
                    depth=payload.depth,
                    swing_threshold_cp=payload.swing_threshold_cp,
                    max_moments=payload.max_moments,
                    min_spacing_plies=payload.min_spacing_plies,
                    min_remaining_plies=payload.min_remaining_plies,
                    commit=True,
                )
            except HTTPException as exc:
                db.rollback()
                imported_game["analysis_error"] = format_http_exception_detail(
                    exc.detail
                )
                continue
            except Exception as exc:
                db.rollback()
                imported_game["analysis_error"] = str(exc)
                continue

            analyzed_count += 1
            total_generated_moments += analysis_result.generated_count
            imported_game["critical_moments_generated"] = (
                analysis_result.generated_count > 0
            )
            imported_game["generated_moments_count"] = analysis_result.generated_count
            imported_game["generated_moment_ply_indexes"] = [
                moment.ply_index for moment in analysis_result.generated_moments
            ]

    return BroadcastImportResponse(
        source_type="broadcast",
        round_id=round_data["round_id"],
        round_url=round_data["round_url"],
        tournament_id=round_data["tournament_id"],
        tournament_name=round_data["tournament_name"],
        round_name=round_data["round_name"],
        quality=quality,
        generate_critical_moments=payload.generate_critical_moments,
        requested_count=len(requested_external_ids),
        imported_count=len(imported_games),
        skipped_count=len(skipped_games),
        analyzed_count=analyzed_count,
        total_generated_moments=total_generated_moments,
        imported_games=imported_games,
        skipped_games=skipped_games,
    )


def resolve_requested_external_ids(
    *,
    round_data: dict[str, object],
    explicit_external_ids: list[str] | None,
    limit: int,
) -> list[str]:
    if explicit_external_ids is not None:
        return explicit_external_ids

    games = round_data.get("games")
    if not isinstance(games, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lichess Broadcast response did not include games to import.",
        )

    external_ids = [
        game["external_id"]
        for game in games[:limit]
        if isinstance(game, dict) and isinstance(game.get("external_id"), str)
    ]
    if not external_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No importable Lichess game ids were found in this Broadcast round. "
                "Try a different round_url or provide explicit external_ids."
            ),
        )

    return external_ids


def raise_http_from_broadcast_error(exc: BroadcastPreviewError) -> None:
    message = str(exc)
    status_code = (
        status.HTTP_422_UNPROCESSABLE_ENTITY
        if "round_" in message or "resource not found" in message
        else status.HTTP_502_BAD_GATEWAY
    )
    raise HTTPException(status_code=status_code, detail=message) from exc


def format_http_exception_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail

    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
        return str(detail)

    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)

    return "Analysis failed."
