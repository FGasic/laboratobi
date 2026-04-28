from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Sequence

import chess

from app.services.pgn_utils import normalize_san_for_compare
from app.services.stockfish import (
    StockfishConfigurationError,
    StockfishEngineError,
    evaluate_fens,
)

BASELINE_DEPTH = 20
BORDERLINE_RECHECK_DEPTH = 24
OBJECTIVE_GAP_THRESHOLD_CP = 80
EQUIVALENT_BAND_CP = 50
DRAWISH_BAND_CP = 120
BORDERLINE_MARGIN_CP = 40
MATE_SCORE_CP = 100000
MATE_DISTANCE_WEIGHT_CP = 10

CriticalMomentInvalidReason = Literal[
    "same_move",
    "missing_engine_best_move",
    "missing_engine_principal_variation",
    "review_runtime_failed",
    "invalid_review_payload",
    "objective_gap_too_small",
    "equivalent_move_band",
    "depth24_recheck_failed",
]

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class CriticalMomentReviewValidation:
    is_valid: bool
    invalid_reason: CriticalMomentInvalidReason | None
    same_move_pass: bool
    has_engine_best_move: bool
    has_engine_principal_variation: bool
    review_runtime_ok: bool
    objective_gap_pass: bool
    equivalent_move_band_reject: bool
    normalized_played_move: str | None
    normalized_engine_best_move: str | None
    best_eval_cp: int | None = None
    played_eval_cp: int | None = None
    objective_gap_cp: int | None = None
    objective_gap_depth: int | None = None
    objective_gap_reason: str | None = None
    equivalent_move_band_reason: str | None = None
    borderline_recheck: bool = False
    depth24_gap_cp: int | None = None


@dataclass(frozen=True)
class ObjectiveGapEvaluation:
    best_eval_cp: int | None
    played_eval_cp: int | None
    objective_gap_cp: int | None
    depth: int
    objective_gap_pass: bool
    objective_gap_reason: str
    equivalent_move_band_reject: bool
    equivalent_move_band_reason: str | None
    borderline_recheck: bool
    depth24_gap_cp: int | None = None
    depth24_recheck_failed: bool = False
    error: str | None = None


def validate_critical_moment_review(
    *,
    played_move_san: str | None,
    engine_best_move: str | None,
    engine_principal_variation: Sequence[str] | None,
    review_runtime_ok: bool = True,
    objective_gap: ObjectiveGapEvaluation | None = None,
    require_objective_gap: bool = False,
) -> CriticalMomentReviewValidation:
    normalized_played_move = normalize_san_for_compare(played_move_san)
    normalized_engine_best_move = normalize_san_for_compare(engine_best_move)
    has_engine_best_move = normalized_engine_best_move is not None
    has_engine_principal_variation = (
        isinstance(engine_principal_variation, list)
        and any(normalize_san_for_compare(move) for move in engine_principal_variation)
    )
    same_move_pass = (
        normalized_played_move is None
        or normalized_engine_best_move is None
        or normalized_played_move != normalized_engine_best_move
    )

    invalid_reason: CriticalMomentInvalidReason | None = None
    if not review_runtime_ok:
        invalid_reason = "review_runtime_failed"
    elif normalized_played_move is None or not isinstance(
        engine_principal_variation, list
    ):
        invalid_reason = "invalid_review_payload"
    elif not has_engine_best_move:
        invalid_reason = "missing_engine_best_move"
    elif not has_engine_principal_variation:
        invalid_reason = "missing_engine_principal_variation"
    elif not same_move_pass:
        invalid_reason = "same_move"
    elif require_objective_gap and objective_gap is None:
        invalid_reason = "review_runtime_failed"
    elif objective_gap is not None and objective_gap.error is not None:
        if objective_gap.depth24_recheck_failed:
            invalid_reason = "depth24_recheck_failed"
        elif objective_gap.objective_gap_reason == "invalid_review_payload":
            invalid_reason = "invalid_review_payload"
        else:
            invalid_reason = "review_runtime_failed"
    elif objective_gap is not None and objective_gap.equivalent_move_band_reject:
        invalid_reason = "equivalent_move_band"
    elif objective_gap is not None and not objective_gap.objective_gap_pass:
        invalid_reason = "objective_gap_too_small"

    return CriticalMomentReviewValidation(
        is_valid=invalid_reason is None,
        invalid_reason=invalid_reason,
        same_move_pass=same_move_pass,
        has_engine_best_move=has_engine_best_move,
        has_engine_principal_variation=has_engine_principal_variation,
        review_runtime_ok=review_runtime_ok,
        objective_gap_pass=(
            objective_gap.objective_gap_pass if objective_gap is not None else False
        ),
        equivalent_move_band_reject=(
            objective_gap.equivalent_move_band_reject
            if objective_gap is not None
            else False
        ),
        normalized_played_move=normalized_played_move,
        normalized_engine_best_move=normalized_engine_best_move,
        best_eval_cp=objective_gap.best_eval_cp if objective_gap is not None else None,
        played_eval_cp=(
            objective_gap.played_eval_cp if objective_gap is not None else None
        ),
        objective_gap_cp=(
            objective_gap.objective_gap_cp if objective_gap is not None else None
        ),
        objective_gap_depth=objective_gap.depth if objective_gap is not None else None,
        objective_gap_reason=(
            objective_gap.objective_gap_reason if objective_gap is not None else None
        ),
        equivalent_move_band_reason=(
            objective_gap.equivalent_move_band_reason
            if objective_gap is not None
            else None
        ),
        borderline_recheck=(
            objective_gap.borderline_recheck if objective_gap is not None else False
        ),
        depth24_gap_cp=(
            objective_gap.depth24_gap_cp if objective_gap is not None else None
        ),
    )


def validate_critical_moment_review_with_objective_gap(
    *,
    fen_before: str | None,
    played_move_san: str | None,
    engine_best_move: str | None,
    engine_principal_variation: Sequence[str] | None,
    review_runtime_ok: bool = True,
) -> CriticalMomentReviewValidation:
    preliminary_validation = validate_critical_moment_review(
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        engine_principal_variation=engine_principal_variation,
        review_runtime_ok=review_runtime_ok,
    )
    if not preliminary_validation.is_valid:
        return preliminary_validation

    if fen_before is None or not fen_before.strip():
        return validate_critical_moment_review(
            played_move_san=played_move_san,
            engine_best_move=engine_best_move,
            engine_principal_variation=engine_principal_variation,
            review_runtime_ok=review_runtime_ok,
            objective_gap=ObjectiveGapEvaluation(
                best_eval_cp=None,
                played_eval_cp=None,
                objective_gap_cp=None,
                depth=BASELINE_DEPTH,
                objective_gap_pass=False,
                objective_gap_reason="invalid_review_payload",
                equivalent_move_band_reject=False,
                equivalent_move_band_reason=None,
                borderline_recheck=False,
                error="missing_fen_before",
            ),
            require_objective_gap=True,
        )

    objective_gap = evaluate_candidate_depth20_then_depth24_if_borderline(
        fen_before=fen_before,
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
    )
    return validate_critical_moment_review(
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        engine_principal_variation=engine_principal_variation,
        review_runtime_ok=review_runtime_ok,
        objective_gap=objective_gap,
        require_objective_gap=True,
    )


def evaluate_candidate_depth20_then_depth24_if_borderline(
    *,
    fen_before: str,
    played_move_san: str,
    engine_best_move: str,
) -> ObjectiveGapEvaluation:
    baseline = evaluate_objective_gap(
        fen_before=fen_before,
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        depth=BASELINE_DEPTH,
    )
    log_objective_gap_eval(event="objective_gap_eval", evaluation=baseline)
    if baseline.error is not None:
        return baseline

    if not should_recheck_at_depth_24(baseline):
        return baseline

    recheck = evaluate_objective_gap(
        fen_before=fen_before,
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        depth=BORDERLINE_RECHECK_DEPTH,
        borderline_recheck=True,
    )
    log_objective_gap_eval(event="objective_gap_recheck", evaluation=recheck)
    if recheck.error is not None:
        return ObjectiveGapEvaluation(
            best_eval_cp=baseline.best_eval_cp,
            played_eval_cp=baseline.played_eval_cp,
            objective_gap_cp=baseline.objective_gap_cp,
            depth=BORDERLINE_RECHECK_DEPTH,
            objective_gap_pass=False,
            objective_gap_reason="depth24_recheck_failed",
            equivalent_move_band_reject=False,
            equivalent_move_band_reason=None,
            borderline_recheck=True,
            depth24_gap_cp=None,
            depth24_recheck_failed=True,
            error=recheck.error,
        )

    return ObjectiveGapEvaluation(
        best_eval_cp=recheck.best_eval_cp,
        played_eval_cp=recheck.played_eval_cp,
        objective_gap_cp=recheck.objective_gap_cp,
        depth=BORDERLINE_RECHECK_DEPTH,
        objective_gap_pass=recheck.objective_gap_pass,
        objective_gap_reason=recheck.objective_gap_reason,
        equivalent_move_band_reject=recheck.equivalent_move_band_reject,
        equivalent_move_band_reason=recheck.equivalent_move_band_reason,
        borderline_recheck=True,
        depth24_gap_cp=recheck.objective_gap_cp,
    )


def evaluate_objective_gap(
    *,
    fen_before: str,
    played_move_san: str,
    engine_best_move: str,
    depth: int,
    borderline_recheck: bool = False,
) -> ObjectiveGapEvaluation:
    try:
        board = chess.Board(fen_before)
        best_move = parse_san_or_uci_move(board, engine_best_move)
        played_move = parse_san_or_uci_move(board, played_move_san)
    except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError) as exc:
        return ObjectiveGapEvaluation(
            best_eval_cp=None,
            played_eval_cp=None,
            objective_gap_cp=None,
            depth=depth,
            objective_gap_pass=False,
            objective_gap_reason="invalid_review_payload",
            equivalent_move_band_reject=False,
            equivalent_move_band_reason=None,
            borderline_recheck=borderline_recheck,
            error=str(exc),
        )

    best_board = board.copy(stack=False)
    best_board.push(best_move)
    played_board = board.copy(stack=False)
    played_board.push(played_move)

    try:
        best_evaluation, played_evaluation = evaluate_fens(
            [best_board.fen(), played_board.fen()],
            depth,
        )
    except (StockfishConfigurationError, StockfishEngineError, TimeoutError) as exc:
        return ObjectiveGapEvaluation(
            best_eval_cp=None,
            played_eval_cp=None,
            objective_gap_cp=None,
            depth=depth,
            objective_gap_pass=False,
            objective_gap_reason="review_runtime_failed",
            equivalent_move_band_reject=False,
            equivalent_move_band_reason=None,
            borderline_recheck=borderline_recheck,
            error=str(exc),
        )

    try:
        side_multiplier = 1 if board.turn == chess.WHITE else -1
        best_eval_cp = side_multiplier * evaluation_to_white_cp(best_evaluation)
        played_eval_cp = side_multiplier * evaluation_to_white_cp(played_evaluation)
    except StockfishEngineError as exc:
        return ObjectiveGapEvaluation(
            best_eval_cp=None,
            played_eval_cp=None,
            objective_gap_cp=None,
            depth=depth,
            objective_gap_pass=False,
            objective_gap_reason="review_runtime_failed",
            equivalent_move_band_reject=False,
            equivalent_move_band_reason=None,
            borderline_recheck=borderline_recheck,
            error=str(exc),
        )

    objective_gap_cp = best_eval_cp - played_eval_cp
    (
        objective_gap_pass,
        objective_gap_reason,
        equivalent_move_band_reject,
        equivalent_move_band_reason,
    ) = classify_objective_gap(
        best_eval_cp=best_eval_cp,
        played_eval_cp=played_eval_cp,
        objective_gap_cp=objective_gap_cp,
    )

    return ObjectiveGapEvaluation(
        best_eval_cp=best_eval_cp,
        played_eval_cp=played_eval_cp,
        objective_gap_cp=objective_gap_cp,
        depth=int(best_evaluation.get("depth_used") or depth),
        objective_gap_pass=objective_gap_pass,
        objective_gap_reason=objective_gap_reason,
        equivalent_move_band_reject=equivalent_move_band_reject,
        equivalent_move_band_reason=equivalent_move_band_reason,
        borderline_recheck=borderline_recheck,
    )


def should_recheck_at_depth_24(evaluation: ObjectiveGapEvaluation) -> bool:
    if evaluation.objective_gap_cp is None:
        return False

    lower_margin = OBJECTIVE_GAP_THRESHOLD_CP - BORDERLINE_MARGIN_CP
    upper_margin = OBJECTIVE_GAP_THRESHOLD_CP + BORDERLINE_MARGIN_CP
    if lower_margin <= evaluation.objective_gap_cp <= upper_margin:
        return True

    if (
        is_drawish_pair(evaluation.best_eval_cp, evaluation.played_eval_cp)
        and evaluation.objective_gap_cp <= EQUIVALENT_BAND_CP + BORDERLINE_MARGIN_CP
    ):
        return True

    return False


def classify_objective_gap(
    *,
    best_eval_cp: int,
    played_eval_cp: int,
    objective_gap_cp: int,
) -> tuple[bool, str, bool, str | None]:
    if (
        is_drawish_pair(best_eval_cp, played_eval_cp)
        and objective_gap_cp <= EQUIVALENT_BAND_CP
    ):
        return (
            False,
            "equivalent_move_band",
            True,
            (
                f"abs(best_eval_cp) and abs(played_eval_cp) <= {DRAWISH_BAND_CP} "
                f"and gap <= {EQUIVALENT_BAND_CP}"
            ),
        )

    if objective_gap_cp < OBJECTIVE_GAP_THRESHOLD_CP:
        return (
            False,
            "objective_gap_too_small",
            False,
            None,
        )

    return True, "objective_gap_pass", False, None


def parse_san_or_uci_move(board: chess.Board, move_text: str) -> chess.Move:
    try:
        move = board.parse_san(move_text)
    except ValueError:
        move = chess.Move.from_uci(move_text)
        if move not in board.legal_moves:
            raise chess.IllegalMoveError(f"Illegal move: {move_text}")

    return move


def evaluation_to_white_cp(evaluation: dict[str, object]) -> int:
    evaluation_white_cp = evaluation.get("evaluation_white_cp")
    if isinstance(evaluation_white_cp, int):
        return evaluation_white_cp

    mate_white = evaluation.get("mate_white")
    if isinstance(mate_white, int):
        mate_score = max(
            MATE_SCORE_CP - abs(mate_white) * MATE_DISTANCE_WEIGHT_CP,
            OBJECTIVE_GAP_THRESHOLD_CP,
        )
        return mate_score if mate_white > 0 else -mate_score

    raise StockfishEngineError("Stockfish evaluation has no centipawn or mate score.")


def is_drawish_pair(best_eval_cp: int | None, played_eval_cp: int | None) -> bool:
    if best_eval_cp is None or played_eval_cp is None:
        return False

    return (
        abs(best_eval_cp) <= DRAWISH_BAND_CP
        and abs(played_eval_cp) <= DRAWISH_BAND_CP
    )


def log_objective_gap_eval(
    *,
    event: str,
    evaluation: ObjectiveGapEvaluation,
) -> None:
    logger.info(
        "%s depth=%s best_eval=%s played_eval=%s gap=%s "
        "objective_gap_pass=%s objective_gap_reason=%s "
        "equivalent_move_band_reject=%s equivalent_move_band_reason=%s "
        "borderline_candidate_rechecked=%s error=%s",
        event,
        evaluation.depth,
        format_optional_int(evaluation.best_eval_cp),
        format_optional_int(evaluation.played_eval_cp),
        format_optional_int(evaluation.objective_gap_cp),
        format_bool(evaluation.objective_gap_pass),
        evaluation.objective_gap_reason,
        format_bool(evaluation.equivalent_move_band_reject),
        evaluation.equivalent_move_band_reason or "none",
        format_bool(evaluation.borderline_recheck),
        evaluation.error or "none",
    )


def log_critical_moment_validation(
    *,
    game_id: int,
    ply_index: int,
    validation: CriticalMomentReviewValidation,
) -> None:
    reason = validation.invalid_reason or "none"
    logger.info(
        "critical_moment_validation: game_id=%s ply_index=%s valid=%s "
        "reason=%s normalized_played_move=%s normalized_engine_best_move=%s "
        "has_engine_best_move=%s has_engine_principal_variation=%s "
        "review_runtime_ok=%s objective_gap_pass=%s "
        "equivalent_move_band_reject=%s best_eval=%s played_eval=%s gap=%s "
        "depth=%s borderline_recheck=%s depth24_gap=%s final_valid=%s",
        game_id,
        ply_index,
        format_bool(validation.is_valid),
        reason,
        validation.normalized_played_move or "none",
        validation.normalized_engine_best_move or "none",
        format_bool(validation.has_engine_best_move),
        format_bool(validation.has_engine_principal_variation),
        format_bool(validation.review_runtime_ok),
        format_bool(validation.objective_gap_pass),
        format_bool(validation.equivalent_move_band_reject),
        format_optional_int(validation.best_eval_cp),
        format_optional_int(validation.played_eval_cp),
        format_optional_int(validation.objective_gap_cp),
        format_optional_int(validation.objective_gap_depth),
        format_bool(validation.borderline_recheck),
        format_optional_int(validation.depth24_gap_cp),
        format_bool(validation.is_valid),
    )


def log_critical_moment_review_runtime_failed(
    *,
    game_id: int,
    ply_index: int,
    error: str,
) -> None:
    logger.error(
        "critical_moment_review_runtime_failed: game_id=%s ply_index=%s error=%r",
        game_id,
        ply_index,
        error,
    )


def format_bool(value: bool) -> str:
    return "true" if value else "false"


def format_optional_int(value: int | None) -> str:
    return str(value) if value is not None else "none"
