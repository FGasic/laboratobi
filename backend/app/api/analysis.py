from typing import Annotated, Any

import chess
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.games import build_game_positions, get_position_at_ply, parse_pgn_text
from app.db import get_db
from app.models import CriticalMoment, Game
from app.schemas.analysis import (
    FenEvaluationRequest,
    FenEvaluationResponse,
    FindGameCandidatesRequest,
    FindGameCandidatesResponse,
    GenerateCriticalMomentsRequest,
    GenerateCriticalMomentsResponse,
    GameCandidateResponse,
    GamePositionEvaluationRequest,
    GamePositionEvaluationResponse,
    GeneratedCriticalMomentResponse,
    ReviewCriticalMomentsRequest,
    ReviewCriticalMomentsResponse,
    ReviewGameCandidatesRequest,
    ReviewGameCandidatesResponse,
    ReviewedCriticalMomentResponse,
    ReviewedGameCandidateResponse,
    SanitizeBroadcastSessionRequest,
    SanitizeBroadcastSessionResponse,
    SanitizedCriticalMomentResponse,
    SanitizedGameResponse,
)
from app.services.critical_moment_scoring import (
    SCORING_MULTIPV,
    CandidateMomentScoring,
    log_candidate_scoring,
    score_candidate_moment,
)
from app.services.critical_moment_review import (
    build_critical_moment_review_payload,
    build_critical_moment_review_payload_from_position_pair,
)
from app.services.critical_moment_ranking import (
    PER_GAME_ACTIVE_MOMENT_LIMIT,
    apply_ranking_metadata,
    build_candidate_ranking,
    log_per_game_selection,
    select_best_candidate_ranking,
)
from app.services.critical_moment_metadata import (
    apply_critical_moment_validation_metadata,
)
from app.services.critical_moment_validation import (
    BASELINE_DEPTH,
    CriticalMomentReviewValidation,
    log_critical_moment_review_runtime_failed,
    log_critical_moment_validation,
    validate_critical_moment_review,
    validate_critical_moment_review_with_objective_gap,
)
from app.services.stockfish import (
    DEFAULT_DEPTH,
    InvalidFenError,
    StockfishConfigurationError,
    StockfishEngineError,
    evaluate_fen,
    evaluate_fens,
    evaluate_fens_top_moves,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])
SessionDep = Annotated[Session, Depends(get_db)]
CRITICAL_MOMENT_REVIEW_DEPTH = 25


@router.post("/evaluate-fen", response_model=FenEvaluationResponse)
def evaluate_fen_endpoint(payload: FenEvaluationRequest) -> FenEvaluationResponse:
    result = evaluate_fen_or_raise_http(payload.fen, payload.depth)
    return FenEvaluationResponse(**result)


@router.post("/evaluate-game-position", response_model=GamePositionEvaluationResponse)
def evaluate_game_position_endpoint(
    payload: GamePositionEvaluationRequest,
    db: SessionDep,
) -> GamePositionEvaluationResponse:
    game = db.get(Game, payload.game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    parsed_game = parse_pgn_text(game.pgn_text)
    position = get_position_at_ply(parsed_game, payload.ply_index)
    evaluation = evaluate_fen_or_raise_http(position.fen, payload.depth)

    return GamePositionEvaluationResponse(
        game_id=game.id,
        ply_index=position.ply_index,
        fullmove_number=position.fullmove_number,
        san_move=position.san_move,
        fen=position.fen,
        side_to_move=position.side_to_move,
        evaluation_cp=evaluation["evaluation_cp"],
        mate=evaluation["mate"],
        best_move=evaluation["best_move"],
        principal_variation=evaluation["principal_variation"],
        depth_used=evaluation["depth_used"],
    )


@router.post("/find-game-candidates", response_model=FindGameCandidatesResponse)
def find_game_candidates_endpoint(
    payload: FindGameCandidatesRequest,
    db: SessionDep,
) -> FindGameCandidatesResponse:
    game = db.get(Game, payload.game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    parsed_game = parse_pgn_text(game.pgn_text)
    positions = build_game_positions(parsed_game)
    evaluations = evaluate_fens_or_raise_http(
        [position.fen for position in positions],
        payload.depth,
    )
    candidates = build_swing_candidates(
        positions=positions,
        evaluations=evaluations,
        swing_threshold_cp=payload.swing_threshold_cp,
    )

    return FindGameCandidatesResponse(
        game_id=game.id,
        depth_used=payload.depth or DEFAULT_DEPTH,
        swing_threshold_cp=payload.swing_threshold_cp,
        candidate_count=len(candidates),
        candidates=candidates,
    )


@router.post("/review-game-candidates", response_model=ReviewGameCandidatesResponse)
def review_game_candidates_endpoint(
    payload: ReviewGameCandidatesRequest,
    db: SessionDep,
) -> ReviewGameCandidatesResponse:
    game = db.get(Game, payload.game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    parsed_game = parse_pgn_text(game.pgn_text)
    positions = build_game_positions(parsed_game)
    depth_used = payload.depth or DEFAULT_DEPTH
    evaluations = evaluate_fens_or_raise_http(
        [position.fen for position in positions],
        depth_used,
    )
    swing_candidates = build_swing_candidates(
        positions=positions,
        evaluations=evaluations,
        swing_threshold_cp=payload.swing_threshold_cp,
    )
    review_candidates = build_review_candidates(
        positions=positions,
        evaluations=evaluations,
        swing_candidates=swing_candidates,
    )
    review_candidates = include_active_critical_moment_reviews(
        db=db,
        game=game,
        positions=positions,
        evaluations=evaluations,
        review_candidates=review_candidates,
    )

    return ReviewGameCandidatesResponse(
        game_id=game.id,
        depth_used=depth_used,
        swing_threshold_cp=payload.swing_threshold_cp,
        candidate_count=len(review_candidates),
        candidates=review_candidates,
    )


@router.post(
    "/review-critical-moments",
    response_model=ReviewCriticalMomentsResponse,
)
def review_critical_moments_endpoint(
    payload: ReviewCriticalMomentsRequest,
    db: SessionDep,
) -> ReviewCriticalMomentsResponse:
    game = db.get(Game, payload.game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    game_id = game.id
    pgn_text = game.pgn_text
    requested_ply_indexes = payload.ply_indexes
    if requested_ply_indexes is None:
        requested_ply_indexes = [
            moment.ply_index
            for moment in get_active_critical_moments(db, game_id)
        ]
    db.close()

    parsed_game = parse_pgn_text(pgn_text)
    positions = build_game_positions(parsed_game)
    depth_used = payload.depth or CRITICAL_MOMENT_REVIEW_DEPTH

    invalid_ply_indexes = [
        ply_index for ply_index in requested_ply_indexes if ply_index < 1
    ]
    if invalid_ply_indexes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All ply_indexes must be positive integers.",
        )

    reviews = build_reviewed_critical_moments(
        game_id=game_id,
        positions=positions,
        ply_indexes=requested_ply_indexes,
        depth=depth_used,
    )
    engine_name = reviews[0].engine_name if reviews else "Stockfish"

    return ReviewCriticalMomentsResponse(
        game_id=game_id,
        depth_used=depth_used,
        engine_name=engine_name,
        moment_count=len(reviews),
        moments=reviews,
    )


@router.post(
    "/generate-critical-moments",
    response_model=GenerateCriticalMomentsResponse,
)
def generate_critical_moments_endpoint(
    payload: GenerateCriticalMomentsRequest,
    db: SessionDep,
) -> GenerateCriticalMomentsResponse:
    game = db.get(Game, payload.game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found.",
        )

    return generate_critical_moments_for_game(
        db=db,
        game=game,
        depth=payload.depth,
        swing_threshold_cp=payload.swing_threshold_cp,
        max_moments=payload.max_moments,
        min_spacing_plies=payload.min_spacing_plies,
        min_remaining_plies=payload.min_remaining_plies,
        commit=True,
    )


@router.post(
    "/sanitize-broadcast-session",
    response_model=SanitizeBroadcastSessionResponse,
)
def sanitize_broadcast_session_endpoint(
    db: SessionDep,
    payload: SanitizeBroadcastSessionRequest | None = None,
) -> SanitizeBroadcastSessionResponse:
    sanitize_payload = payload or SanitizeBroadcastSessionRequest()
    return sanitize_broadcast_study_session(
        db=db,
        depth=sanitize_payload.depth,
        swing_threshold_cp=sanitize_payload.swing_threshold_cp,
        max_moments=sanitize_payload.max_moments,
        min_spacing_plies=sanitize_payload.min_spacing_plies,
        min_remaining_plies=sanitize_payload.min_remaining_plies,
        commit=True,
    )


def generate_critical_moments_for_game(
    *,
    db: Session,
    game: Game,
    depth: int | None,
    swing_threshold_cp: int,
    max_moments: int,
    min_spacing_plies: int,
    min_remaining_plies: int,
    commit: bool,
) -> GenerateCriticalMomentsResponse:
    parsed_game = parse_pgn_text(game.pgn_text)
    positions = build_game_positions(parsed_game)
    depth_used = depth or BASELINE_DEPTH
    evaluations = evaluate_fens_or_raise_http(
        [position.fen for position in positions],
        depth_used,
    )
    candidates = build_swing_candidates(
        positions=positions,
        evaluations=evaluations,
        swing_threshold_cp=swing_threshold_cp,
    )
    review_candidates = build_review_candidates(
        positions=positions,
        evaluations=evaluations,
        swing_candidates=candidates,
    )
    scoring_results = score_candidate_moments(
        game=game,
        parsed_game=parsed_game,
        positions=positions,
        evaluations=evaluations,
        candidates=candidates,
        review_candidates=review_candidates,
        depth=depth_used,
    )
    review_filtered_candidates, discarded_same_move_count, discarded_incomplete_review_count = (
        filter_candidates_with_review_data(game.id, candidates, review_candidates)
    )
    eligible_scoring_by_ply_index = {
        scoring.ply_index: scoring for scoring in scoring_results if scoring.is_eligible
    }
    filtered_candidates = [
        candidate
        for candidate in review_filtered_candidates
        if candidate.ply_index in eligible_scoring_by_ply_index
    ]
    discarded_objective_filter_count = len(review_filtered_candidates) - len(
        filtered_candidates
    )
    ranking_candidates = filter_candidates_for_final_ranking(
        candidates=filtered_candidates,
        total_plies=len(positions),
        min_remaining_plies=min_remaining_plies,
        scoring_by_ply_index=eligible_scoring_by_ply_index,
    )
    candidate_by_ply_index = {
        candidate.ply_index: candidate for candidate in ranking_candidates
    }
    review_by_ply_index = {
        review_candidate.ply_index: review_candidate
        for review_candidate in review_candidates
    }
    final_rankings = build_final_candidate_rankings(
        game_id=game.id,
        total_plies=len(positions),
        candidates=ranking_candidates,
        review_by_ply_index=review_by_ply_index,
        scoring_by_ply_index=eligible_scoring_by_ply_index,
    )
    selected_ranking = select_best_candidate_ranking(final_rankings)
    rejected_rankings = [
        ranking
        for ranking in final_rankings
        if selected_ranking is None or ranking.ply_index != selected_ranking.ply_index
    ]
    log_per_game_selection(
        game_id=game.id,
        selected=selected_ranking,
        rejected=rejected_rankings,
    )
    selected_candidates = (
        [candidate_by_ply_index[selected_ranking.ply_index]]
        if selected_ranking is not None
        else []
    )
    ranking_by_ply_index = {
        ranking.ply_index: ranking for ranking in final_rankings
    }

    active_moments = list(
        db.scalars(
            select(CriticalMoment).where(
                CriticalMoment.game_id == game.id,
                CriticalMoment.is_active.is_(True),
            )
        ).all()
    )
    for moment in active_moments:
        moment.is_active = False

    generated_moments: list[GeneratedCriticalMomentResponse] = []
    for index, candidate in enumerate(selected_candidates, start=1):
        review_candidate = review_by_ply_index.get(candidate.ply_index)
        if review_candidate is None:
            continue

        validation = validate_critical_moment_review_for_candidate(review_candidate)
        if not validation.is_valid:
            log_critical_moment_validation(
                game_id=game.id,
                ply_index=candidate.ply_index,
                validation=validation,
            )
            continue
        ranking = ranking_by_ply_index.get(candidate.ply_index)
        if ranking is None:
            continue

        moment = CriticalMoment(
            game_id=game.id,
            ply_index=candidate.ply_index,
            moment_number=index,
            title=None,
            label="Auto-generated",
            notes=None,
            is_active=True,
        )
        apply_critical_moment_validation_metadata(
            moment=moment,
            validation=validation,
            review_payload=review_candidate.model_dump(),
        )
        apply_ranking_metadata(moment=moment, ranking=ranking)
        db.add(moment)
        generated_moments.append(
            GeneratedCriticalMomentResponse(
                moment_number=index,
                ply_index=candidate.ply_index,
                fullmove_number=candidate.fullmove_number,
                san_move=candidate.san_move,
                swing_cp=candidate.swing_cp,
                objective_scoring=eligible_scoring_by_ply_index[
                    candidate.ply_index
                ].to_public_dict(),
                played_move_san=review_candidate.played_move_san,
                engine_best_move=review_candidate.engine_best_move,
                objective_gap_cp=ranking.objective_gap_cp,
                transferable_idea_score=ranking.transferable_idea_score,
                phase=ranking.phase,
                phase_preference_score=ranking.phase_preference_score,
                final_candidate_score=ranking.final_candidate_score,
            )
        )

    if commit:
        db.commit()
    else:
        db.flush()

    return GenerateCriticalMomentsResponse(
        game_id=game.id,
        depth_used=depth_used,
        swing_threshold_cp=swing_threshold_cp,
        max_moments=PER_GAME_ACTIVE_MOMENT_LIMIT,
        min_spacing_plies=min_spacing_plies,
        min_remaining_plies=min_remaining_plies,
        candidates_found=len(candidates),
        discarded_same_move_count=discarded_same_move_count,
        discarded_incomplete_review_count=discarded_incomplete_review_count,
        scored_candidates_count=len(scoring_results),
        discarded_objective_filter_count=discarded_objective_filter_count,
        eligible_candidates_count=len(filtered_candidates),
        generated_count=len(generated_moments),
        generated_moments=generated_moments,
        candidate_scoring=[
            scoring.to_public_dict() for scoring in scoring_results
        ],
    )


def sanitize_broadcast_study_session(
    *,
    db: Session,
    depth: int | None,
    swing_threshold_cp: int,
    max_moments: int,
    min_spacing_plies: int,
    min_remaining_plies: int,
    commit: bool,
) -> SanitizeBroadcastSessionResponse:
    games = get_current_broadcast_session_games(db)
    sanitized_games: list[SanitizedGameResponse] = []
    total_deactivated = 0
    objective_gap_deactivated_count = 0
    equivalent_band_deactivated_count = 0
    regenerated_games_count = 0

    for game in games:
        active_moments = get_active_critical_moments(db, game.id)
        active_before = len(active_moments)
        events: list[SanitizedCriticalMomentResponse] = []
        deactivated_count = 0

        for moment, validation, review_payload in audit_critical_moments_for_game(
            game=game,
            active_moments=active_moments,
            depth=depth,
        ):
            apply_critical_moment_validation_metadata(
                moment=moment,
                validation=validation,
                review_payload=review_payload,
            )
            if validation.is_valid:
                events.append(
                    build_sanitized_event(
                        game_id=game.id,
                        moment=moment,
                        action="preexisting_valid_rechecked",
                        validation=validation,
                        review_payload=review_payload,
                    )
                )
                continue

            moment.is_active = False
            deactivated_count += 1
            if validation.invalid_reason == "objective_gap_too_small":
                objective_gap_deactivated_count += 1
            elif validation.invalid_reason == "equivalent_move_band":
                equivalent_band_deactivated_count += 1
            events.append(
                build_sanitized_event(
                    game_id=game.id,
                    moment=moment,
                    action="deactivated",
                    validation=validation,
                    review_payload=review_payload,
                )
            )

        db.flush()

        regenerated = True
        regenerated_games_count += 1
        active_valid_after = 0
        try:
            generate_critical_moments_for_game(
                db=db,
                game=game,
                depth=depth,
                swing_threshold_cp=swing_threshold_cp,
                max_moments=PER_GAME_ACTIVE_MOMENT_LIMIT,
                min_spacing_plies=min_spacing_plies,
                min_remaining_plies=min_remaining_plies,
                commit=False,
            )
        except Exception as exc:
            log_critical_moment_review_runtime_failed(
                game_id=game.id,
                ply_index=0,
                error=f"regeneration_failed: {exc}",
            )
            validation = validate_critical_moment_review(
                played_move_san=None,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            events.append(
                SanitizedCriticalMomentResponse(
                    game_id=game.id,
                    moment_id=None,
                    ply_index=0,
                    action="regeneration_failed",
                    invalid_reason=validation.invalid_reason,
                )
            )
            active_valid_after = count_active_valid_moments(
                game=game,
                active_moments=get_active_critical_moments(db, game.id),
                depth=depth,
            )
        else:
            db.flush()
            for moment, validation, review_payload in audit_critical_moments_for_game(
                game=game,
                active_moments=get_active_critical_moments(db, game.id),
                depth=depth,
            ):
                apply_critical_moment_validation_metadata(
                    moment=moment,
                    validation=validation,
                    review_payload=review_payload,
                )
                action = "generated_kept"
                if validation.is_valid:
                    active_valid_after += 1
                else:
                    moment.is_active = False
                    deactivated_count += 1
                    if validation.invalid_reason == "objective_gap_too_small":
                        objective_gap_deactivated_count += 1
                    elif validation.invalid_reason == "equivalent_move_band":
                        equivalent_band_deactivated_count += 1
                    action = "generated_deactivated"

                events.append(
                    build_sanitized_event(
                        game_id=game.id,
                        moment=moment,
                        action=action,
                        validation=validation,
                        review_payload=review_payload,
                    )
                )
            db.flush()

        total_deactivated += deactivated_count
        sanitized_games.append(
            SanitizedGameResponse(
                game_id=game.id,
                active_before=active_before,
                deactivated_count=deactivated_count,
                regenerated=regenerated,
                active_valid_after=active_valid_after,
                events=events,
            )
        )

    if commit:
        db.commit()
    else:
        db.flush()

    return SanitizeBroadcastSessionResponse(
        games_checked=len(sanitized_games),
        games_remaining=sum(
            1 for sanitized_game in sanitized_games if sanitized_game.active_valid_after > 0
        ),
        active_valid_moments=sum(
            sanitized_game.active_valid_after for sanitized_game in sanitized_games
        ),
        deactivated_count=total_deactivated,
        objective_gap_deactivated_count=objective_gap_deactivated_count,
        equivalent_band_deactivated_count=equivalent_band_deactivated_count,
        regenerated_games_count=regenerated_games_count,
        games=sanitized_games,
    )


def get_current_broadcast_session_games(db: Session) -> list[Game]:
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
        select(Game)
        .where(Game.source_type == "broadcast")
        .order_by(
            case((active_moments_count > 0, 1), else_=0).desc(),
            Game.created_at.desc(),
            Game.id.desc(),
        )
        .limit(3)
    )
    return list(db.scalars(statement).all())


def get_active_critical_moments(db: Session, game_id: int) -> list[CriticalMoment]:
    return list(
        db.scalars(
            select(CriticalMoment)
            .where(
                CriticalMoment.game_id == game_id,
                CriticalMoment.is_active.is_(True),
            )
            .order_by(CriticalMoment.moment_number.asc(), CriticalMoment.ply_index.asc())
        ).all()
    )


def audit_critical_moments_for_game(
    *,
    game: Game,
    active_moments: list[CriticalMoment],
    depth: int | None,
) -> list[tuple[CriticalMoment, CriticalMomentReviewValidation, dict[str, Any] | None]]:
    if not active_moments:
        return []

    try:
        parsed_game = parse_pgn_text(game.pgn_text)
        positions = build_game_positions(parsed_game)
    except Exception as exc:
        audit_results = []
        for moment in active_moments:
            log_critical_moment_review_runtime_failed(
                game_id=game.id,
                ply_index=moment.ply_index,
                error=str(exc),
            )
            validation = validate_critical_moment_review(
                played_move_san=None,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            log_critical_moment_validation(
                game_id=game.id,
                ply_index=moment.ply_index,
                validation=validation,
            )
            audit_results.append((moment, validation, None))
        return audit_results

    audit_results = []
    for moment in active_moments:
        position_index = moment.ply_index - 1
        previous_index = position_index - 1
        if previous_index < 0 or position_index >= len(positions):
            review_payload = None
        else:
            try:
                evaluation_before = evaluate_fens_or_raise_http(
                    [positions[previous_index].fen],
                    depth or BASELINE_DEPTH,
                )[0]
            except Exception as exc:
                log_critical_moment_review_runtime_failed(
                    game_id=game.id,
                    ply_index=moment.ply_index,
                    error=str(exc),
                )
                evaluation_before = None

            review_payload = (
                build_critical_moment_review_payload_from_position_pair(
                    ply_index=moment.ply_index,
                    position_before=positions[previous_index],
                    position_after=positions[position_index],
                    evaluation_before=evaluation_before,
                )
                if evaluation_before is not None
                else None
            )
        if review_payload is None:
            log_critical_moment_review_runtime_failed(
                game_id=game.id,
                ply_index=moment.ply_index,
                error="review_payload_missing",
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
                engine_principal_variation=review_payload[
                    "engine_principal_variation"
                ],
            )

        log_critical_moment_validation(
            game_id=game.id,
            ply_index=moment.ply_index,
            validation=validation,
        )
        audit_results.append((moment, validation, review_payload))

    return audit_results


def count_active_valid_moments(
    *,
    game: Game,
    active_moments: list[CriticalMoment],
    depth: int | None,
) -> int:
    return sum(
        1
        for _, validation, _ in audit_critical_moments_for_game(
            game=game,
            active_moments=active_moments,
            depth=depth,
        )
        if validation.is_valid
    )


def build_sanitized_event(
    *,
    game_id: int,
    moment: CriticalMoment,
    action: str,
    validation: CriticalMomentReviewValidation,
    review_payload: dict[str, Any] | None,
) -> SanitizedCriticalMomentResponse:
    return SanitizedCriticalMomentResponse(
        game_id=game_id,
        moment_id=moment.id,
        ply_index=moment.ply_index,
        action=action,
        invalid_reason=validation.invalid_reason,
        played_move_san=(
            review_payload.get("played_move_san") if review_payload is not None else None
        ),
        engine_best_move=(
            review_payload.get("engine_best_move") if review_payload is not None else None
        ),
        engine_principal_variation_count=(
            len(review_payload.get("engine_principal_variation") or [])
            if review_payload is not None
            else 0
        ),
        best_eval_cp=validation.best_eval_cp,
        played_eval_cp=validation.played_eval_cp,
        objective_gap_cp=validation.objective_gap_cp,
        objective_gap_depth=validation.objective_gap_depth,
        objective_gap_pass=validation.objective_gap_pass,
        equivalent_move_band_reject=validation.equivalent_move_band_reject,
        borderline_recheck=validation.borderline_recheck,
        depth24_gap_cp=validation.depth24_gap_cp,
        phase=moment.ranking_phase,
        phase_preference_score=moment.ranking_phase_preference_score,
        final_candidate_score=moment.ranking_final_candidate_score,
        transferable_idea_score=moment.ranking_transferable_idea_score,
    )


def evaluate_fen_or_raise_http(fen: str, depth: int | None) -> dict[str, Any]:
    try:
        return evaluate_fen(fen, depth)
    except InvalidFenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except StockfishConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except StockfishEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def evaluate_fens_or_raise_http(
    fens: list[str],
    depth: int | None,
) -> list[dict[str, Any]]:
    try:
        return evaluate_fens(fens, depth)
    except InvalidFenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except StockfishConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except StockfishEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def evaluate_top_moves_or_raise_http(
    fens: list[str],
    depth: int | None,
    multipv: int,
) -> list[list[dict[str, Any]]]:
    if not fens:
        return []

    try:
        return evaluate_fens_top_moves(fens, depth, multipv)
    except InvalidFenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except StockfishConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except StockfishEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def score_candidate_moments(
    *,
    game: Game,
    parsed_game: chess.pgn.Game,
    positions: list[Any],
    evaluations: list[dict[str, Any]],
    candidates: list[GameCandidateResponse],
    review_candidates: list[ReviewedGameCandidateResponse],
    depth: int | None,
) -> list[CandidateMomentScoring]:
    review_by_ply_index = {
        review_candidate.ply_index: review_candidate
        for review_candidate in review_candidates
    }
    top_move_ply_indexes = [review.ply_index for review in review_candidates]
    top_move_fens = [review.fen_before for review in review_candidates]
    top_move_results = evaluate_top_moves_or_raise_http(
        top_move_fens,
        depth,
        SCORING_MULTIPV,
    )
    top_moves_by_ply_index = dict(zip(top_move_ply_indexes, top_move_results))

    scoring_results: list[CandidateMomentScoring] = []
    for candidate in candidates:
        position_index = candidate.ply_index - 1
        previous_index = position_index - 1
        evaluation_before = evaluations[previous_index] if previous_index >= 0 else {}
        evaluation_after = (
            evaluations[position_index]
            if 0 <= position_index < len(evaluations)
            else {}
        )
        previous_position = (
            positions[previous_index] if previous_index >= 0 else None
        )
        scoring = score_candidate_moment(
            game_id=game.id,
            game_headers=dict(parsed_game.headers),
            game_context={
                "source_type": game.source_type,
                "external_id": game.external_id,
                "source_url": game.source_url,
                "round_id": game.round_id,
                "tournament_id": game.tournament_id,
                "event_name": game.event_name,
                "white_player": game.white_player,
                "black_player": game.black_player,
            },
            candidate=candidate,
            review_candidate=review_by_ply_index.get(candidate.ply_index),
            evaluation_before=evaluation_before,
            evaluation_after=evaluation_after,
            top_moves_before=top_moves_by_ply_index.get(candidate.ply_index, []),
            previous_position=previous_position,
        )
        log_candidate_scoring(scoring)
        scoring_results.append(scoring)

    return scoring_results


def build_swing_candidates(
    positions: list[Any],
    evaluations: list[dict[str, Any]],
    swing_threshold_cp: int,
) -> list[GameCandidateResponse]:
    candidates: list[GameCandidateResponse] = []

    for index in range(1, len(positions)):
        position = positions[index]
        evaluation_before = evaluations[index - 1]
        evaluation_after = evaluations[index]
        evaluation_before_cp = evaluation_before["evaluation_white_cp"]
        evaluation_after_cp = evaluation_after["evaluation_white_cp"]

        if evaluation_before_cp is None or evaluation_after_cp is None:
            continue

        if has_mate_in_one(evaluation_before) or has_mate_in_one(evaluation_after):
            continue

        if best_move_captures_queen(position.fen, evaluation_after["best_move"]):
            continue

        swing_cp = abs(evaluation_after_cp - evaluation_before_cp)
        if swing_cp <= swing_threshold_cp:
            continue

        candidates.append(
            GameCandidateResponse(
                ply_index=position.ply_index,
                fullmove_number=position.fullmove_number,
                san_move=position.san_move,
                fen=position.fen,
                side_to_move=position.side_to_move,
                evaluation_before_cp=evaluation_before_cp,
                evaluation_after_cp=evaluation_after_cp,
                swing_cp=swing_cp,
            )
        )

    return candidates


def build_review_candidates(
    positions: list[Any],
    evaluations: list[dict[str, Any]],
    swing_candidates: list[GameCandidateResponse],
) -> list[ReviewedGameCandidateResponse]:
    reviews: list[ReviewedGameCandidateResponse] = []

    for candidate in swing_candidates:
        review_payload = build_critical_moment_review_payload(
            positions=positions,
            evaluations=evaluations,
            ply_index=candidate.ply_index,
        )
        if review_payload is None:
            continue

        review_payload["evaluation_before_cp"] = candidate.evaluation_before_cp
        review_payload["evaluation_after_cp"] = candidate.evaluation_after_cp
        review_payload["swing_cp"] = candidate.swing_cp
        reviews.append(ReviewedGameCandidateResponse(**review_payload))

    return reviews


def include_active_critical_moment_reviews(
    *,
    db: Session,
    game: Game,
    positions: list[Any],
    evaluations: list[dict[str, Any]],
    review_candidates: list[ReviewedGameCandidateResponse],
) -> list[ReviewedGameCandidateResponse]:
    active_moments = list(
        db.scalars(
            select(CriticalMoment).where(
                CriticalMoment.game_id == game.id,
                CriticalMoment.is_active.is_(True),
            )
        ).all()
    )
    if not active_moments:
        return review_candidates

    reviews_by_ply = {
        review_candidate.ply_index: review_candidate
        for review_candidate in review_candidates
    }
    for moment in active_moments:
        position_index = moment.ply_index - 1
        previous_index = position_index - 1
        if previous_index < 0 or position_index >= len(positions):
            review_payload = None
        else:
            try:
                evaluation_before = evaluate_fens_or_raise_http(
                    [positions[previous_index].fen],
                    BASELINE_DEPTH,
                )[0]
            except Exception as exc:
                log_critical_moment_review_runtime_failed(
                    game_id=game.id,
                    ply_index=moment.ply_index,
                    error=str(exc),
                )
                evaluation_before = None

            review_payload = (
                build_critical_moment_review_payload_from_position_pair(
                    ply_index=moment.ply_index,
                    position_before=positions[previous_index],
                    position_after=positions[position_index],
                    evaluation_before=evaluation_before,
                )
                if evaluation_before is not None
                else None
            )
        if review_payload is None:
            log_critical_moment_review_runtime_failed(
                game_id=game.id,
                ply_index=moment.ply_index,
                error="active_moment_review_payload_missing",
            )
            validation = validate_critical_moment_review(
                played_move_san=None,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            log_critical_moment_validation(
                game_id=game.id,
                ply_index=moment.ply_index,
                validation=validation,
            )
            continue

        validation = validate_critical_moment_review(
            played_move_san=review_payload["played_move_san"],
            engine_best_move=review_payload["engine_best_move"],
            engine_principal_variation=review_payload["engine_principal_variation"],
        )
        log_critical_moment_validation(
            game_id=game.id,
            ply_index=moment.ply_index,
            validation=validation,
        )
        if not validation.is_valid:
            continue

        review_candidate = ReviewedGameCandidateResponse(**review_payload)
        reviews_by_ply[review_candidate.ply_index] = review_candidate

    return sorted(reviews_by_ply.values(), key=lambda review: review.ply_index)


def build_reviewed_critical_moments(
    *,
    game_id: int,
    positions: list[Any],
    ply_indexes: list[int],
    depth: int,
) -> list[ReviewedCriticalMomentResponse]:
    requested_ply_indexes = dedupe_ply_indexes(ply_indexes)
    position_pairs = []

    for ply_index in requested_ply_indexes:
        position_index = ply_index - 1
        previous_index = position_index - 1
        if previous_index < 0 or position_index >= len(positions):
            log_critical_moment_review_runtime_failed(
                game_id=game_id,
                ply_index=ply_index,
                error="critical_moment_review_out_of_range",
            )
            continue

        position_pairs.append(
            (
                ply_index,
                positions[previous_index],
                positions[position_index],
            )
        )

    if not position_pairs:
        return []

    fens: list[str] = []
    for _, position_before, position_after in position_pairs:
        fens.append(position_before.fen)
        fens.append(position_after.fen)

    evaluations = evaluate_fens_or_raise_http(fens, depth)
    reviews: list[ReviewedCriticalMomentResponse] = []
    for index, (ply_index, position_before, position_after) in enumerate(
        position_pairs
    ):
        evaluation_before = evaluations[index * 2]
        evaluation_after = evaluations[index * 2 + 1]
        review_payload = build_critical_moment_review_payload_from_position_pair(
            ply_index=ply_index,
            position_before=position_before,
            position_after=position_after,
            evaluation_before=evaluation_before,
            evaluation_after=evaluation_after,
        )
        if review_payload is None:
            log_critical_moment_review_runtime_failed(
                game_id=game_id,
                ply_index=ply_index,
                error="critical_moment_depth25_review_payload_missing",
            )
            continue

        reviews.append(
            ReviewedCriticalMomentResponse(
                **review_payload,
                engine_line_eval_cp=get_optional_int(
                    evaluation_before.get("evaluation_white_cp")
                ),
                engine_line_mate=get_optional_int(
                    evaluation_before.get("mate_white")
                ),
                played_move_eval_cp=get_optional_int(
                    evaluation_after.get("evaluation_white_cp")
                ),
                played_move_mate=get_optional_int(evaluation_after.get("mate_white")),
                engine_name=get_engine_name_from_evaluation(evaluation_before),
                depth_used=get_depth_used_from_evaluation(evaluation_before, depth),
            )
        )

    return reviews


def dedupe_ply_indexes(ply_indexes: list[int]) -> list[int]:
    seen: set[int] = set()
    unique_ply_indexes: list[int] = []
    for ply_index in ply_indexes:
        if ply_index in seen:
            continue

        seen.add(ply_index)
        unique_ply_indexes.append(ply_index)

    return unique_ply_indexes


def get_optional_int(value: Any) -> int | None:
    return value if type(value) is int else None


def get_depth_used_from_evaluation(evaluation: dict[str, Any], fallback: int) -> int:
    depth = get_optional_int(evaluation.get("depth_used"))
    return depth if depth is not None else fallback


def get_engine_name_from_evaluation(evaluation: dict[str, Any]) -> str:
    engine_name = evaluation.get("engine_name")
    if isinstance(engine_name, str) and engine_name.strip():
        return engine_name.strip()

    return "Stockfish"


def validate_critical_moment_review_for_candidate(
    review_candidate: ReviewedGameCandidateResponse,
) -> CriticalMomentReviewValidation:
    return validate_critical_moment_review_with_objective_gap(
        fen_before=review_candidate.fen_before,
        played_move_san=review_candidate.played_move_san,
        engine_best_move=review_candidate.engine_best_move,
        engine_principal_variation=review_candidate.engine_principal_variation,
    )


def validate_basic_critical_moment_review_for_candidate(
    review_candidate: ReviewedGameCandidateResponse,
) -> CriticalMomentReviewValidation:
    return validate_critical_moment_review(
        played_move_san=review_candidate.played_move_san,
        engine_best_move=review_candidate.engine_best_move,
        engine_principal_variation=review_candidate.engine_principal_variation,
    )


def filter_candidates_for_final_ranking(
    *,
    candidates: list[GameCandidateResponse],
    total_plies: int,
    min_remaining_plies: int,
    scoring_by_ply_index: dict[int, CandidateMomentScoring],
) -> list[GameCandidateResponse]:
    ranking_candidates: list[GameCandidateResponse] = []
    for candidate in candidates:
        if candidate.ply_index not in scoring_by_ply_index:
            continue

        remaining_plies = total_plies - candidate.ply_index
        if remaining_plies < min_remaining_plies:
            continue

        ranking_candidates.append(candidate)

    return sorted(
        ranking_candidates,
        key=lambda candidate: (
            -scoring_by_ply_index[candidate.ply_index].moment_score_with_transferable,
            -scoring_by_ply_index[candidate.ply_index].moment_score_partial,
            -candidate.swing_cp,
            candidate.ply_index,
        ),
    )


def build_final_candidate_rankings(
    *,
    game_id: int,
    total_plies: int,
    candidates: list[GameCandidateResponse],
    review_by_ply_index: dict[int, ReviewedGameCandidateResponse],
    scoring_by_ply_index: dict[int, CandidateMomentScoring],
) -> list[Any]:
    rankings = []

    for candidate in candidates:
        review_candidate = review_by_ply_index.get(candidate.ply_index)
        scoring = scoring_by_ply_index.get(candidate.ply_index)
        if review_candidate is None or scoring is None:
            validation = validate_critical_moment_review(
                played_move_san=candidate.san_move,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            log_critical_moment_review_runtime_failed(
                game_id=game_id,
                ply_index=candidate.ply_index,
                error="ranking_candidate_review_missing",
            )
            log_critical_moment_validation(
                game_id=game_id,
                ply_index=candidate.ply_index,
                validation=validation,
            )
            continue

        validation = validate_critical_moment_review_for_candidate(review_candidate)
        log_critical_moment_validation(
            game_id=game_id,
            ply_index=candidate.ply_index,
            validation=validation,
        )
        if not validation.is_valid:
            continue

        rankings.append(
            build_candidate_ranking(
                game_id=game_id,
                ply_index=candidate.ply_index,
                total_plies=total_plies,
                fen_before=review_candidate.fen_before,
                played_move_san=review_candidate.played_move_san,
                engine_best_move=review_candidate.engine_best_move,
                objective_score=scoring.moment_score_partial,
                transferable_idea_score=scoring.transferable_idea_score,
                difficulty_adequacy_score=scoring.difficulty_adequacy_score,
                validation=validation,
            )
        )

    return rankings


def filter_selected_candidates_with_final_validation(
    *,
    game_id: int,
    selected_candidates: list[GameCandidateResponse],
    review_candidates: list[ReviewedGameCandidateResponse],
) -> list[GameCandidateResponse]:
    review_by_ply_index = {
        review_candidate.ply_index: review_candidate
        for review_candidate in review_candidates
    }
    valid_candidates: list[GameCandidateResponse] = []

    for candidate in selected_candidates:
        review_candidate = review_by_ply_index.get(candidate.ply_index)
        if review_candidate is None:
            validation = validate_critical_moment_review(
                played_move_san=candidate.san_move,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            log_critical_moment_review_runtime_failed(
                game_id=game_id,
                ply_index=candidate.ply_index,
                error="selected_candidate_review_missing",
            )
            log_critical_moment_validation(
                game_id=game_id,
                ply_index=candidate.ply_index,
                validation=validation,
            )
            continue

        validation = validate_critical_moment_review_for_candidate(review_candidate)
        log_critical_moment_validation(
            game_id=game_id,
            ply_index=candidate.ply_index,
            validation=validation,
        )
        if validation.is_valid:
            valid_candidates.append(candidate)

    return valid_candidates


def filter_candidates_with_review_data(
    game_id: int,
    candidates: list[GameCandidateResponse],
    review_candidates: list[ReviewedGameCandidateResponse],
) -> tuple[list[GameCandidateResponse], int, int]:
    review_by_ply_index = {
        review_candidate.ply_index: review_candidate
        for review_candidate in review_candidates
    }
    filtered_candidates: list[GameCandidateResponse] = []
    discarded_same_move_count = 0
    discarded_incomplete_review_count = 0

    for candidate in candidates:
        review_candidate = review_by_ply_index.get(candidate.ply_index)
        if review_candidate is None:
            validation = validate_critical_moment_review(
                played_move_san=candidate.san_move,
                engine_best_move=None,
                engine_principal_variation=[],
                review_runtime_ok=False,
            )
            log_critical_moment_validation(
                game_id=game_id,
                ply_index=candidate.ply_index,
                validation=validation,
            )
            discarded_incomplete_review_count += 1
            continue

        validation = validate_basic_critical_moment_review_for_candidate(
            review_candidate
        )
        log_critical_moment_validation(
            game_id=game_id,
            ply_index=candidate.ply_index,
            validation=validation,
        )
        if validation.invalid_reason == "same_move":
            discarded_same_move_count += 1
            continue

        if not validation.is_valid:
            discarded_incomplete_review_count += 1
            continue

        filtered_candidates.append(candidate)

    return (
        filtered_candidates,
        discarded_same_move_count,
        discarded_incomplete_review_count,
    )


def select_critical_moment_candidates(
    *,
    candidates: list[GameCandidateResponse],
    total_plies: int,
    max_moments: int,
    min_spacing_plies: int,
    min_remaining_plies: int,
) -> list[GameCandidateResponse]:
    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: (-candidate.swing_cp, candidate.ply_index),
    )
    selected_candidates: list[GameCandidateResponse] = []
    selected_ply_indexes: set[int] = set()

    for candidate in sorted_candidates:
        if candidate.ply_index in selected_ply_indexes:
            continue

        remaining_plies = total_plies - candidate.ply_index
        if remaining_plies < min_remaining_plies:
            continue

        if any(
            abs(candidate.ply_index - selected_candidate.ply_index)
            < min_spacing_plies
            for selected_candidate in selected_candidates
        ):
            continue

        selected_candidates.append(candidate)
        selected_ply_indexes.add(candidate.ply_index)

        if len(selected_candidates) >= max_moments:
            break

    return selected_candidates


def format_engine_move_san(fen: str, move_uci: str | None) -> str | None:
    if move_uci is None:
        return None

    line = format_engine_line_san(fen, [move_uci])
    return line[0] if line else move_uci


def format_engine_line_san(fen: str, moves_uci: list[str]) -> list[str]:
    try:
        board = chess.Board(fen)
    except ValueError:
        return moves_uci

    moves_san: list[str] = []
    for move_uci in moves_uci:
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            moves_san.append(move_uci)
            break

        if move not in board.legal_moves:
            moves_san.append(move_uci)
            break

        moves_san.append(board.san(move))
        board.push(move)

    return moves_san


def has_mate_in_one(evaluation: dict[str, Any]) -> bool:
    mate = evaluation["mate"]
    return mate is not None and abs(mate) == 1


def best_move_captures_queen(fen: str, best_move: str | None) -> bool:
    if best_move is None:
        return False

    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(best_move)
    except ValueError:
        return False

    if move not in board.legal_moves:
        return False

    captured_piece = board.piece_at(move.to_square)
    return captured_piece is not None and captured_piece.piece_type == chess.QUEEN
