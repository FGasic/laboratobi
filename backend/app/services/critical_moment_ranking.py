from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import chess

from app.services.critical_moment_validation import CriticalMomentReviewValidation

logger = logging.getLogger("uvicorn.error")

PER_GAME_ACTIVE_MOMENT_LIMIT = 1
OBJECTIVE_GAP_SCORE_CAP_CP = 400

FINAL_SCORE_OBJECTIVE_WEIGHT = 0.30
FINAL_SCORE_TRANSFERABLE_WEIGHT = 0.20
FINAL_SCORE_OBJECTIVE_GAP_WEIGHT = 0.15
FINAL_SCORE_PHASE_WEIGHT = 0.35


@dataclass(frozen=True)
class PhasePreference:
    phase: str
    phase_preference_score: float
    reason: str


@dataclass(frozen=True)
class CandidateRanking:
    game_id: int
    ply_index: int
    played_move_san: str | None
    engine_best_move: str | None
    objective_score: float
    transferable_idea_score: float
    objective_gap_cp: int
    objective_gap_score: float
    phase: str
    phase_preference_score: float
    difficulty_adequacy_score: float
    final_candidate_score: float
    phase_reason: str
    validation: CriticalMomentReviewValidation


def infer_phase_preference(
    *,
    game_id: int,
    ply_index: int,
    total_plies: int,
    fen_before: str,
) -> PhasePreference:
    board = chess.Board(fen_before)
    non_king_pieces = [
        piece for piece in board.piece_map().values()
        if piece.piece_type != chess.KING
    ]
    non_king_count = len(non_king_pieces)
    queens = [
        piece for piece in non_king_pieces
        if piece.piece_type == chess.QUEEN
    ]
    has_queens = bool(queens)
    ply_ratio = ply_index / max(total_plies, 1)

    if not has_queens and (non_king_count <= 10 or ply_ratio >= 0.70):
        result = PhasePreference(
            phase="endgame",
            phase_preference_score=1.0,
            reason=(
                f"no_queens non_king_count={non_king_count} "
                f"ply_ratio={ply_ratio:.2f}"
            ),
        )
    elif non_king_count <= 14 or ply_ratio >= 0.62:
        result = PhasePreference(
            phase="late_middlegame_early_endgame",
            phase_preference_score=3.0,
            reason=(
                f"non_king_count={non_king_count} has_queens={has_queens} "
                f"ply_ratio={ply_ratio:.2f}"
            ),
        )
    elif ply_index < 16:
        result = PhasePreference(
            phase="early_opening",
            phase_preference_score=3.0,
            reason=f"ply_index={ply_index}<16",
        )
    elif ply_index < 28:
        result = PhasePreference(
            phase="opening_to_middlegame",
            phase_preference_score=4.25,
            reason=f"16<=ply_index={ply_index}<28",
        )
    else:
        result = PhasePreference(
            phase="middlegame",
            phase_preference_score=5.0,
            reason=(
                f"central_phase ply_index={ply_index} "
                f"non_king_count={non_king_count} has_queens={has_queens} "
                f"ply_ratio={ply_ratio:.2f}"
            ),
        )

    logger.info(
        "phase_inference: game_id=%s ply_index=%s phase=%s score=%s reason=%s",
        game_id,
        ply_index,
        result.phase,
        result.phase_preference_score,
        result.reason,
    )
    return result


def build_candidate_ranking(
    *,
    game_id: int,
    ply_index: int,
    total_plies: int,
    fen_before: str,
    played_move_san: str | None,
    engine_best_move: str | None,
    objective_score: float,
    transferable_idea_score: float,
    difficulty_adequacy_score: float,
    validation: CriticalMomentReviewValidation,
) -> CandidateRanking:
    phase_preference = infer_phase_preference(
        game_id=game_id,
        ply_index=ply_index,
        total_plies=total_plies,
        fen_before=fen_before,
    )
    objective_gap_cp = max(validation.objective_gap_cp or 0, 0)
    objective_gap_score = normalize_objective_gap_score(objective_gap_cp)
    transferable_normalized = normalize_five_point_score(transferable_idea_score)
    phase_normalized = normalize_five_point_score(
        phase_preference.phase_preference_score
    )
    final_candidate_score = round(
        objective_score * FINAL_SCORE_OBJECTIVE_WEIGHT
        + transferable_normalized * FINAL_SCORE_TRANSFERABLE_WEIGHT
        + objective_gap_score * FINAL_SCORE_OBJECTIVE_GAP_WEIGHT
        + phase_normalized * FINAL_SCORE_PHASE_WEIGHT,
        2,
    )

    ranking = CandidateRanking(
        game_id=game_id,
        ply_index=ply_index,
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        objective_score=objective_score,
        transferable_idea_score=transferable_idea_score,
        objective_gap_cp=objective_gap_cp,
        objective_gap_score=objective_gap_score,
        phase=phase_preference.phase,
        phase_preference_score=phase_preference.phase_preference_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
        final_candidate_score=final_candidate_score,
        phase_reason=phase_preference.reason,
        validation=validation,
    )
    log_candidate_ranking(ranking)
    return ranking


def select_best_candidate_ranking(
    rankings: list[CandidateRanking],
) -> CandidateRanking | None:
    if not rankings:
        return None

    return sorted(rankings, key=candidate_ranking_sort_key)[0]


def candidate_ranking_sort_key(ranking: CandidateRanking) -> tuple[float, int, float, float, int]:
    return (
        -ranking.final_candidate_score,
        -ranking.objective_gap_cp,
        -ranking.transferable_idea_score,
        -ranking.difficulty_adequacy_score,
        ranking.ply_index,
    )


def log_candidate_ranking(ranking: CandidateRanking) -> None:
    logger.info(
        "candidate_ranking: game_id=%s ply_index=%s final_score=%s "
        "objective_score=%s objective_gap=%s objective_gap_score=%s "
        "transferable=%s phase=%s phase_score=%s difficulty=%s",
        ranking.game_id,
        ranking.ply_index,
        ranking.final_candidate_score,
        ranking.objective_score,
        ranking.objective_gap_cp,
        ranking.objective_gap_score,
        ranking.transferable_idea_score,
        ranking.phase,
        ranking.phase_preference_score,
        ranking.difficulty_adequacy_score,
    )


def log_per_game_selection(
    *,
    game_id: int,
    selected: CandidateRanking | None,
    rejected: list[CandidateRanking],
) -> None:
    selected_ply = selected.ply_index if selected is not None else "none"
    rejected_payload = [
        {
            "ply_index": ranking.ply_index,
            "final_score": ranking.final_candidate_score,
            "phase": ranking.phase,
            "phase_score": ranking.phase_preference_score,
            "objective_gap_cp": ranking.objective_gap_cp,
        }
        for ranking in rejected
    ]
    logger.info(
        "per_game_selection: game_id=%s selected_ply=%s rejected_other_candidates=%s",
        game_id,
        selected_ply,
        rejected_payload,
    )

    if selected is None:
        logger.info(
            "per_game_selection_reason: game_id=%s no_valid_candidate_after_filters",
            game_id,
        )
        return

    later_phase_penalized = [
        ranking for ranking in rejected
        if ranking.phase in {"late_middlegame_early_endgame", "endgame"}
        and ranking.ply_index > selected.ply_index
    ]
    if later_phase_penalized and selected.phase in {
        "opening_to_middlegame",
        "middlegame",
    }:
        later_phase = later_phase_penalized[0].phase
        logger.info(
            "per_game_selection_reason: game_id=%s preferred earlier %s "
            "candidate over later %s candidate",
            game_id,
            selected.phase,
            later_phase,
        )
        return

    logger.info(
        "per_game_selection_reason: game_id=%s selected highest final score "
        "with tie_breakers final_score, objective_gap, transferable, "
        "difficulty, earlier_ply",
        game_id,
    )


def normalize_five_point_score(value: float) -> float:
    return round(max(0.0, min(value, 5.0)) * 20.0, 2)


def normalize_objective_gap_score(objective_gap_cp: int) -> float:
    capped_gap = max(0, min(objective_gap_cp, OBJECTIVE_GAP_SCORE_CAP_CP))
    return round((capped_gap / OBJECTIVE_GAP_SCORE_CAP_CP) * 100.0, 2)


def apply_ranking_metadata(*, moment: Any, ranking: CandidateRanking) -> None:
    moment.ranking_phase = ranking.phase
    moment.ranking_phase_preference_score = ranking.phase_preference_score
    moment.ranking_final_candidate_score = ranking.final_candidate_score
    moment.ranking_objective_score = ranking.objective_score
    moment.ranking_transferable_idea_score = ranking.transferable_idea_score
    moment.ranking_objective_gap_score = ranking.objective_gap_score
    moment.ranking_difficulty_adequacy_score = ranking.difficulty_adequacy_score
