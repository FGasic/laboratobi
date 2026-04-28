from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
import json
import logging

import chess

from app.services.pgn_utils import normalize_san_for_compare
from app.services.broadcast_quality import (
    contains_blocking_keyword,
    contains_serious_event_keyword,
    is_unknown_player_name,
)

logger = logging.getLogger(__name__)

MINIMUM_IMPACT_CP = 70
SERIOUS_CONTEXT_MIN_ELO = 2400
CANDIDATE_BAND_CP = 60
SCORING_MULTIPV = 5

AUTOMATIC_RECAPTURE_MAX_SWING_CP = 160
GROTESQUE_QUEEN_BLUNDER_MIN_SWING_CP = 300
GROTESQUE_PIECE_BLUNDER_MIN_SWING_CP = 500

SCORE_WEIGHTS = {
    "candidate_richness_score": 0.35,
    "opponent_resource_pressure_score": 0.25,
    "objective_consequence_clarity_score": 0.20,
    "difficulty_adequacy_score": 0.20,
}

THEME_CANDIDATE_MOVES = "candidate_moves"
THEME_OPPONENT_RESOURCES = "opponent_resources"
THEME_PROPHYLAXIS = "prophylaxis"
THEME_TECHNICAL_CONVERSION = "technical_conversion"
ALLOWED_V1_THEMES = {
    THEME_CANDIDATE_MOVES,
    THEME_OPPONENT_RESOURCES,
    THEME_PROPHYLAXIS,
    THEME_TECHNICAL_CONVERSION,
}

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}


@dataclass(frozen=True)
class CandidateMomentScoring:
    game_id: int
    ply_index: int
    fullmove_number: int | None
    played_move_san: str | None
    engine_best_move: str | None
    different_move_pass: bool
    minimum_impact_pass: bool
    serious_context_pass: bool
    serious_context_route: str | None
    serious_context_reason: str | None
    not_trivial_pass: bool
    humanly_explainable_pass: bool
    candidate_richness_score: float
    opponent_resource_pressure_score: float
    objective_consequence_clarity_score: float
    difficulty_adequacy_score: float
    primary_theme: str | None
    secondary_themes: list[str]
    transferable_idea_score: float
    transferable_idea_reason: str | None
    swing_cp: int | None
    candidate_count: int | None
    best_move_stability: float | None
    moment_score_partial: float
    moment_score_with_transferable: float
    exclusion_reason: str | None
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def is_eligible(self) -> bool:
        return self.exclusion_reason is None

    def to_public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("trace", None)
        return data

    def to_log_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["accepted"] = self.is_eligible
        return data


def score_candidate_moment(
    *,
    game_id: int,
    game_headers: Mapping[str, str],
    game_context: Mapping[str, str | None],
    candidate: Any,
    review_candidate: Any | None,
    evaluation_before: Mapping[str, Any],
    evaluation_after: Mapping[str, Any],
    top_moves_before: list[Mapping[str, Any]],
    previous_position: Any | None,
) -> CandidateMomentScoring:
    played_move_san = (
        getattr(review_candidate, "played_move_san", None)
        if review_candidate is not None
        else getattr(candidate, "san_move", None)
    )
    engine_best_move = (
        getattr(review_candidate, "engine_best_move", None)
        if review_candidate is not None
        else None
    )
    engine_principal_variation = (
        getattr(review_candidate, "engine_principal_variation", [])
        if review_candidate is not None
        else []
    )
    fen_before = (
        getattr(review_candidate, "fen_before", None)
        if review_candidate is not None
        else None
    )
    fen_after = (
        getattr(review_candidate, "fen_after", None)
        if review_candidate is not None
        else getattr(candidate, "fen", None)
    )
    swing_cp = getattr(candidate, "swing_cp", None)

    normalized_played_move = normalize_san_for_compare(played_move_san)
    normalized_engine_move = normalize_san_for_compare(engine_best_move)
    different_move_pass = (
        normalized_played_move is not None
        and normalized_engine_move is not None
        and normalized_played_move != normalized_engine_move
    )

    minimum_impact_pass = has_minimum_impact(
        swing_cp=swing_cp,
        mate_before=evaluation_before.get("mate_white"),
        mate_after=evaluation_after.get("mate_white"),
    )
    serious_context_result = evaluate_serious_context(
        game_headers=game_headers,
        game_context=game_context,
    )
    serious_context_pass = serious_context_result["pass"]
    serious_context_route = serious_context_result["route"]
    serious_context_reason = serious_context_result["reason"]
    not_trivial_pass, not_trivial_detail = evaluate_not_trivial(
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        fen_before=fen_before,
        fen_after=fen_after,
        evaluation_after=evaluation_after,
        previous_position=previous_position,
        swing_cp=swing_cp,
        different_move_pass=different_move_pass,
    )
    humanly_explainable_pass, humanly_explainable_detail = (
        evaluate_humanly_explainable(
            played_move_san=played_move_san,
            engine_best_move=engine_best_move,
            engine_principal_variation=engine_principal_variation,
        )
    )

    candidate_richness_score, candidate_count, richness_detail = (
        score_candidate_richness(top_moves_before)
    )
    opponent_resource_pressure_score, pressure_detail = (
        score_opponent_resource_pressure(
            fen_after=fen_after,
            evaluation_after=evaluation_after,
            swing_cp=swing_cp,
        )
    )
    objective_consequence_clarity_score = score_objective_consequence_clarity(
        swing_cp=swing_cp,
        mate_before=evaluation_before.get("mate_white"),
        mate_after=evaluation_after.get("mate_white"),
    )
    difficulty_adequacy_score, difficulty_detail = score_difficulty_adequacy(
        candidate_richness_score=candidate_richness_score,
        swing_cp=swing_cp,
        pv_length=len(engine_principal_variation),
    )
    moment_score_partial = compute_moment_score_partial(
        candidate_richness_score=candidate_richness_score,
        opponent_resource_pressure_score=opponent_resource_pressure_score,
        objective_consequence_clarity_score=objective_consequence_clarity_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
    )
    theme_result = infer_transferable_idea(
        fen_before=fen_before,
        evaluation_before=evaluation_before,
        fen_after=fen_after,
        evaluation_after=evaluation_after,
        top_moves_before=top_moves_before,
        candidate_richness_score=candidate_richness_score,
        opponent_resource_pressure_score=opponent_resource_pressure_score,
        objective_consequence_clarity_score=objective_consequence_clarity_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
        candidate_count=candidate_count,
        swing_cp=swing_cp,
    )
    moment_score_with_transferable = compute_moment_score_with_transferable(
        moment_score_partial=moment_score_partial,
        transferable_idea_score=theme_result["score"],
    )

    exclusion_reason = first_exclusion_reason(
        [
            (
                "different_move",
                different_move_pass,
                (
                    "played_move_san and engine_best_move normalize to the "
                    f"same value or are missing "
                    f"(played={normalized_played_move!r}, "
                    f"engine={normalized_engine_move!r})"
                ),
            ),
            (
                "minimum_impact",
                minimum_impact_pass,
                f"swing_cp={swing_cp} below threshold {MINIMUM_IMPACT_CP}",
            ),
            (
                "serious_context",
                serious_context_pass,
                serious_context_reason,
            ),
            (
                "not_trivial",
                not_trivial_pass,
                not_trivial_detail,
            ),
            (
                "humanly_explainable",
                humanly_explainable_pass,
                humanly_explainable_detail,
            ),
        ]
    )

    # TODO: populate this when the pipeline evaluates the same candidate at
    # multiple depths. In this phase there is only one depth sample.
    best_move_stability = None

    return CandidateMomentScoring(
        game_id=game_id,
        ply_index=getattr(candidate, "ply_index"),
        fullmove_number=getattr(candidate, "fullmove_number", None),
        played_move_san=played_move_san,
        engine_best_move=engine_best_move,
        different_move_pass=different_move_pass,
        minimum_impact_pass=minimum_impact_pass,
        serious_context_pass=serious_context_pass,
        serious_context_route=serious_context_route,
        serious_context_reason=serious_context_reason,
        not_trivial_pass=not_trivial_pass,
        humanly_explainable_pass=humanly_explainable_pass,
        candidate_richness_score=candidate_richness_score,
        opponent_resource_pressure_score=opponent_resource_pressure_score,
        objective_consequence_clarity_score=objective_consequence_clarity_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
        primary_theme=theme_result["primary_theme"],
        secondary_themes=theme_result["secondary_themes"],
        transferable_idea_score=theme_result["score"],
        transferable_idea_reason=theme_result["reason"],
        swing_cp=swing_cp,
        candidate_count=candidate_count,
        best_move_stability=best_move_stability,
        moment_score_partial=moment_score_partial,
        moment_score_with_transferable=moment_score_with_transferable,
        exclusion_reason=exclusion_reason,
        trace={
            "normalized_played_move": normalized_played_move,
            "normalized_engine_best_move": normalized_engine_move,
            "minimum_impact_cp": MINIMUM_IMPACT_CP,
            "candidate_band_cp": CANDIDATE_BAND_CP,
            "serious_context": {
                "route": serious_context_route,
                "reason": serious_context_reason,
            },
            "not_trivial": not_trivial_detail,
            "humanly_explainable": humanly_explainable_detail,
            "candidate_richness": richness_detail,
            "opponent_resource_pressure": pressure_detail,
            "difficulty_adequacy": difficulty_detail,
            "theme_inference": theme_result["trace"],
            "top_moves_before": compact_top_moves(top_moves_before),
        },
    )


def log_candidate_scoring(scoring: CandidateMomentScoring) -> None:
    if scoring.serious_context_pass:
        logger.info(
            "serious_context: pass via %s reason=%s",
            scoring.serious_context_route,
            scoring.serious_context_reason,
        )
    else:
        logger.info(
            "serious_context: fail reason=%s",
            scoring.serious_context_reason,
        )
    logger.info(
        "theme_inference: primary=%s secondary=%s reason=%s",
        scoring.primary_theme,
        scoring.secondary_themes,
        scoring.transferable_idea_reason or "no_clear_theme",
    )
    logger.info(
        "transferable_idea_score: score=%s reason=%s",
        scoring.transferable_idea_score,
        scoring.transferable_idea_reason or "no_clear_theme",
    )
    logger.info(
        "critical_moment_candidate_scoring %s",
        json.dumps(scoring.to_log_dict(), sort_keys=True),
    )


def has_minimum_impact(
    *,
    swing_cp: int | None,
    mate_before: int | None,
    mate_after: int | None,
) -> bool:
    if swing_cp is not None and swing_cp >= MINIMUM_IMPACT_CP:
        return True

    return has_relevant_mate_swing(mate_before, mate_after)


def has_relevant_mate_swing(
    mate_before: int | None,
    mate_after: int | None,
) -> bool:
    if mate_before is None and mate_after is None:
        return False

    if mate_before == mate_after:
        return False

    if mate_before is None or mate_after is None:
        return True

    return (mate_before > 0) != (mate_after > 0) or abs(
        abs(mate_after) - abs(mate_before)
    ) >= 2


def evaluate_serious_context(
    *,
    game_headers: Mapping[str, str],
    game_context: Mapping[str, str | None],
) -> dict[str, Any]:
    # V1 correction: Broadcast import is already quality-gated by
    # evaluate_broadcast_quality unless allow_low_quality is explicitly used.
    # The quality decision is not persisted, so the durable evidence available
    # here is the persisted source metadata on Game.
    broadcast_pass, broadcast_reason = evaluate_broadcast_context(game_context)
    if broadcast_pass:
        return {
            "pass": True,
            "route": "broadcast_context",
            "reason": broadcast_reason,
        }

    white_elo = parse_rating(game_headers.get("WhiteElo"))
    black_elo = parse_rating(game_headers.get("BlackElo"))
    player_elo_pass = (
        white_elo is not None
        and black_elo is not None
        and white_elo >= SERIOUS_CONTEXT_MIN_ELO
        and black_elo >= SERIOUS_CONTEXT_MIN_ELO
    )
    if player_elo_pass:
        return {
            "pass": True,
            "route": "player_elo",
            "reason": (
                f"player_elo white_elo={white_elo} black_elo={black_elo} "
                f"threshold={SERIOUS_CONTEXT_MIN_ELO}"
            ),
        }

    return {
        "pass": False,
        "route": "none",
        "reason": (
            "missing_broadcast_context_and_missing_or_low_elo "
            f"broadcast_reason=({broadcast_reason}) "
            f"white_elo={white_elo} black_elo={black_elo} "
            f"threshold={SERIOUS_CONTEXT_MIN_ELO}"
        ),
    }


def evaluate_broadcast_context(
    game_context: Mapping[str, str | None],
) -> tuple[bool, str]:
    source_type = normalize_optional_text(game_context.get("source_type"))
    source_type = source_type.lower() if source_type is not None else None
    external_id = normalize_optional_text(game_context.get("external_id"))
    source_url = normalize_optional_text(game_context.get("source_url"))
    round_id = normalize_optional_text(game_context.get("round_id"))
    tournament_id = normalize_optional_text(game_context.get("tournament_id"))
    event_name = normalize_optional_text(game_context.get("event_name"))
    white_player = normalize_optional_text(game_context.get("white_player"))
    black_player = normalize_optional_text(game_context.get("black_player"))

    broadcast_markers = [
        marker
        for marker in [round_id, external_id, source_url, tournament_id]
        if marker is not None
    ]
    has_broadcast_origin = source_type == "broadcast" and bool(broadcast_markers)
    has_blocking_name = contains_blocking_keyword(event_name)
    has_serious_event_name = contains_serious_event_keyword(event_name)
    has_known_players = (
        white_player is not None
        and black_player is not None
        and not is_unknown_player_name(white_player)
        and not is_unknown_player_name(black_player)
    )

    if (
        has_broadcast_origin
        and not has_blocking_name
        and (has_serious_event_name or has_known_players)
    ):
        return (
            True,
            (
                "broadcast_context "
                f"source_type={source_type} round_id={round_id} "
                f"external_id={external_id} source_url={source_url} "
                f"tournament_id={tournament_id} "
                f"serious_event_name={has_serious_event_name} "
                f"known_players={has_known_players}"
            ),
        )

    return (
        False,
        (
            "missing_broadcast_context "
            f"source_type={source_type} round_id={round_id} "
            f"external_id={external_id} source_url={source_url} "
            f"tournament_id={tournament_id} "
            f"has_broadcast_origin={has_broadcast_origin} "
            f"blocking_name={has_blocking_name} "
            f"serious_event_name={has_serious_event_name} "
            f"known_players={has_known_players}"
        ),
    )


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def parse_rating(value: str | None) -> int | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped or stripped in {"?", "-"}:
        return None

    try:
        return int(stripped)
    except ValueError:
        return None


def evaluate_not_trivial(
    *,
    played_move_san: str | None,
    engine_best_move: str | None,
    fen_before: str | None,
    fen_after: str | None,
    evaluation_after: Mapping[str, Any],
    previous_position: Any | None,
    swing_cp: int | None,
    different_move_pass: bool,
) -> tuple[bool, str]:
    # Exact V1 rules:
    # 1. Same played/engine move is trivial, but the earlier different_move
    #    filter owns that exclusion reason.
    # 2. Automatic recapture on the previous move's destination is considered
    #    trivial only when the objective swing is still modest (<160 cp).
    # 3. Immediate mate-in-one best responses are too elementary for this pass.
    # 4. Huge queen/piece drops to the opponent's first engine move are treated
    #    as low pedagogical value material blunders.
    if not different_move_pass:
        return False, "same move is handled by the different_move hard filter"

    if engine_best_move and engine_best_move.strip().endswith("#"):
        return False, "engine best move is immediate mate"

    if evaluation_after.get("mate") is not None and abs(evaluation_after["mate"]) == 1:
        return False, "opponent has mate in one after the played move"

    if is_automatic_recapture_without_content(
        played_move_san=played_move_san,
        fen_before=fen_before,
        previous_position=previous_position,
        swing_cp=swing_cp,
    ):
        return (
            False,
            (
                "automatic recapture on previous move destination with "
                f"swing_cp<{AUTOMATIC_RECAPTURE_MAX_SWING_CP}"
            ),
        )

    grotesque_blunder_reason = evaluate_grotesque_material_blunder(
        fen_after=fen_after,
        best_response_uci=evaluation_after.get("best_move"),
        swing_cp=swing_cp,
    )
    if grotesque_blunder_reason is not None:
        return False, grotesque_blunder_reason

    return True, "passed minimal not_trivial checks"


def is_automatic_recapture_without_content(
    *,
    played_move_san: str | None,
    fen_before: str | None,
    previous_position: Any | None,
    swing_cp: int | None,
) -> bool:
    if (
        played_move_san is None
        or fen_before is None
        or previous_position is None
        or swing_cp is None
        or swing_cp >= AUTOMATIC_RECAPTURE_MAX_SWING_CP
    ):
        return False

    previous_to_square = getattr(previous_position, "to_square", None)
    if previous_to_square is None:
        return False

    try:
        board = chess.Board(fen_before)
        played_move = board.parse_san(played_move_san)
    except ValueError:
        return False

    return (
        board.is_capture(played_move)
        and chess.square_name(played_move.to_square) == previous_to_square
    )


def evaluate_grotesque_material_blunder(
    *,
    fen_after: str | None,
    best_response_uci: str | None,
    swing_cp: int | None,
) -> str | None:
    if fen_after is None or best_response_uci is None or swing_cp is None:
        return None

    try:
        board = chess.Board(fen_after)
        move = chess.Move.from_uci(best_response_uci)
    except ValueError:
        return None

    if move not in board.legal_moves or not board.is_capture(move):
        return None

    captured_piece = captured_piece_for_move(board, move)
    if captured_piece is None:
        return None

    if (
        captured_piece.piece_type == chess.QUEEN
        and swing_cp >= GROTESQUE_QUEEN_BLUNDER_MIN_SWING_CP
    ):
        return "opponent best response wins a queen immediately"

    if (
        captured_piece.piece_type in {chess.ROOK, chess.BISHOP, chess.KNIGHT}
        and swing_cp >= GROTESQUE_PIECE_BLUNDER_MIN_SWING_CP
    ):
        return "opponent best response wins a major/minor piece immediately"

    return None


def captured_piece_for_move(board: chess.Board, move: chess.Move) -> chess.Piece | None:
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        return board.piece_at(capture_square)

    return board.piece_at(move.to_square)


def evaluate_humanly_explainable(
    *,
    played_move_san: str | None,
    engine_best_move: str | None,
    engine_principal_variation: list[str],
) -> tuple[bool, str]:
    if not played_move_san:
        return False, "missing played_move"

    if not engine_best_move:
        return False, "missing best_move"

    if not engine_principal_variation:
        return False, "missing principal variation"

    return True, "played_move, best_move, and PV are present"


def score_candidate_richness(
    top_moves: list[Mapping[str, Any]],
) -> tuple[float, int | None, str]:
    scored_moves = [
        move for move in top_moves if move.get("move") and move.get("evaluation_cp") is not None
    ]
    if not scored_moves:
        return 0.0, None, "no centipawn top-move data"

    top_eval = scored_moves[0]["evaluation_cp"]
    moves_in_band = [
        move
        for move in scored_moves
        if top_eval - int(move["evaluation_cp"]) <= CANDIDATE_BAND_CP
    ]
    candidate_count = len(moves_in_band)

    if candidate_count <= 1:
        second_gap = None
        if len(scored_moves) > 1:
            second_gap = top_eval - int(scored_moves[1]["evaluation_cp"])
        score = 1.0 if second_gap is not None and second_gap <= CANDIDATE_BAND_CP * 2 else 0.0
        return score, candidate_count, f"candidate_count={candidate_count}, second_gap={second_gap}"

    if candidate_count == 2:
        spread = top_eval - int(moves_in_band[-1]["evaluation_cp"])
        score = 3.0 if spread <= CANDIDATE_BAND_CP / 2 else 2.0
        return score, candidate_count, f"candidate_count=2, spread={spread}"

    if candidate_count == 3:
        return 4.0, candidate_count, "candidate_count=3"

    return 5.0, candidate_count, f"candidate_count={candidate_count}"


def score_opponent_resource_pressure(
    *,
    fen_after: str | None,
    evaluation_after: Mapping[str, Any],
    swing_cp: int | None,
) -> tuple[float, str]:
    best_response_uci = evaluation_after.get("best_move")
    if fen_after is None or best_response_uci is None:
        return 0.0, "missing fen_after or opponent best response"

    try:
        board = chess.Board(fen_after)
        best_response = chess.Move.from_uci(best_response_uci)
    except ValueError:
        return 0.0, "invalid fen_after or best response UCI"

    if best_response not in board.legal_moves:
        return 0.0, "opponent best response is illegal in fen_after"

    score = 1.0
    signals: list[str] = ["legal_response"]

    if board.gives_check(best_response):
        score += 1.5
        signals.append("check")

    captured_piece = captured_piece_for_move(board, best_response)
    if captured_piece is not None:
        captured_value = PIECE_VALUES.get(captured_piece.piece_type, 0)
        if captured_value >= 9:
            score += 2.0
        elif captured_value >= 5:
            score += 1.5
        elif captured_value >= 3:
            score += 1.0
        else:
            score += 0.5
        signals.append(f"capture_value={captured_value}")

    if best_response.promotion is not None:
        score += 1.0
        signals.append("promotion")

    forcing_moves = count_forcing_moves(
        fen=fen_after,
        pv_uci=evaluation_after.get("principal_variation") or [],
        max_plies=3,
    )
    if forcing_moves >= 2:
        score += 1.0
    elif forcing_moves == 1:
        score += 0.5
    signals.append(f"forcing_moves_first_3={forcing_moves}")

    if swing_cp is not None and swing_cp >= 400:
        score += 1.0
        signals.append("swing>=400")
    elif swing_cp is not None and swing_cp >= 250:
        score += 0.5
        signals.append("swing>=250")

    return clamp_score(score), ", ".join(signals)


def count_forcing_moves(*, fen: str, pv_uci: list[str], max_plies: int) -> int:
    try:
        board = chess.Board(fen)
    except ValueError:
        return 0

    forcing_moves = 0
    for move_uci in pv_uci[:max_plies]:
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            break

        if move not in board.legal_moves:
            break

        if board.gives_check(move) or board.is_capture(move) or move.promotion is not None:
            forcing_moves += 1

        board.push(move)

    return forcing_moves


def score_objective_consequence_clarity(
    *,
    swing_cp: int | None,
    mate_before: int | None,
    mate_after: int | None,
) -> float:
    if has_relevant_mate_swing(mate_before, mate_after):
        return 5.0

    if swing_cp is None or swing_cp < MINIMUM_IMPACT_CP:
        return 0.0

    if swing_cp < 100:
        return 1.0

    if swing_cp < 160:
        return 2.0

    if swing_cp < 250:
        return 3.0

    if swing_cp < 400:
        return 4.0

    return 5.0


def score_difficulty_adequacy(
    *,
    candidate_richness_score: float,
    swing_cp: int | None,
    pv_length: int,
) -> tuple[float, str]:
    # V1 approximation: positions are treated as better training material when
    # there are several plausible candidates, the PV has enough length to show
    # a line, and the swing is meaningful without being just a giant drop.
    score = 0.0
    details: list[str] = []

    if candidate_richness_score >= 4:
        score += 2.0
        details.append("rich_candidates")
    elif candidate_richness_score >= 2:
        score += 1.5
        details.append("some_candidates")
    elif candidate_richness_score >= 1:
        score += 0.5
        details.append("near_unique")

    if 3 <= pv_length <= 6:
        score += 2.0
        details.append(f"pv_length={pv_length}")
    elif pv_length >= 2:
        score += 1.0
        details.append(f"pv_length={pv_length}")

    if swing_cp is None:
        details.append("missing_swing")
    elif swing_cp < MINIMUM_IMPACT_CP:
        details.append("swing_below_minimum")
    elif swing_cp < 130:
        score += 1.5
        details.append("moderate_swing")
    elif swing_cp < 300:
        score += 2.0
        details.append("clear_swing")
    elif swing_cp < 500:
        score += 1.0
        details.append("large_swing")
    else:
        score += 0.5
        details.append("very_large_swing")

    if candidate_richness_score <= 1 and swing_cp is not None and swing_cp >= 400:
        score -= 1.0
        details.append("penalty_for_forced_large_swing")

    return clamp_score(score), ", ".join(details) or "no difficulty signals"


def infer_transferable_idea(
    *,
    fen_before: str | None,
    evaluation_before: Mapping[str, Any],
    fen_after: str | None,
    evaluation_after: Mapping[str, Any],
    top_moves_before: list[Mapping[str, Any]],
    candidate_richness_score: float,
    opponent_resource_pressure_score: float,
    objective_consequence_clarity_score: float,
    difficulty_adequacy_score: float,
    candidate_count: int | None,
    swing_cp: int | None,
) -> dict[str, Any]:
    # V1 theme priority is explicit and conservative:
    # prophylaxis > opponent_resources > candidate_moves > technical_conversion.
    # TODO: future iterations can add comparison, elimination, intermediate_move,
    # imagination, combinational_vision, schematic_thinking, and
    # strategy_calculation_integration after this small taxonomy is observed.
    top_move_spread = compute_top_move_spread(top_moves_before)
    best_move_profile = describe_move_profile(
        fen_before,
        evaluation_before.get("best_move"),
    )
    opponent_response_profile = describe_move_profile(
        fen_after,
        evaluation_after.get("best_move"),
    )
    forcing_after = count_forcing_moves(
        fen=fen_after or "",
        pv_uci=evaluation_after.get("principal_variation") or [],
        max_plies=3,
    )
    endgameish = is_endgameish_position(fen_before)

    broad_candidate_moves_signal = (
        candidate_count is not None
        and candidate_count >= 2
        and candidate_richness_score >= 3.0
        and top_move_spread is not None
        and top_move_spread <= CANDIDATE_BAND_CP
        and opponent_resource_pressure_score < 3.0
    )
    opponent_resources_signal = (
        opponent_resource_pressure_score >= 3.0
        or (
            opponent_resource_pressure_score >= 2.5
            and (
                forcing_after >= 2
                or objective_consequence_clarity_score >= 3.0
                or opponent_response_profile["gives_check"]
                or opponent_response_profile["captured_value"] >= 3
                or opponent_response_profile["is_promotion"]
            )
        )
    )
    prophylaxis_signal = (
        best_move_profile["is_quiet"]
        and (
            opponent_resource_pressure_score >= 3.0
            or (opponent_resource_pressure_score >= 2.5 and forcing_after >= 2)
        )
        and objective_consequence_clarity_score <= 3.0
    )
    technical_conversion_signal = (
        objective_consequence_clarity_score >= 3.0
        and opponent_resource_pressure_score <= 2.5
        and not opponent_response_profile["gives_check"]
        and (
            endgameish
            or best_move_profile["is_quiet"]
            or best_move_profile["is_capture"]
        )
        and candidate_richness_score <= 3.0
    )
    candidate_choice_is_real = (
        candidate_count is not None
        and (
            candidate_count >= 3
            or (
                candidate_count == 2
                and top_move_spread is not None
                and top_move_spread <= CANDIDATE_BAND_CP / 2
                and difficulty_adequacy_score >= 4.0
            )
        )
    )
    candidate_moves_signal = (
        candidate_choice_is_real
        and candidate_richness_score >= 3.0
        and top_move_spread is not None
        and top_move_spread <= CANDIDATE_BAND_CP * 0.75
        and opponent_resource_pressure_score <= 2.0
        and objective_consequence_clarity_score <= 3.0
        and difficulty_adequacy_score >= 3.0
        and not prophylaxis_signal
        and not opponent_resources_signal
        and not technical_conversion_signal
    )
    candidate_moves_rejection_reason = build_candidate_moves_rejection_reason(
        broad_signal=broad_candidate_moves_signal,
        strict_signal=candidate_moves_signal,
        candidate_choice_is_real=candidate_choice_is_real,
        candidate_count=candidate_count,
        candidate_richness_score=candidate_richness_score,
        top_move_spread=top_move_spread,
        opponent_resource_pressure_score=opponent_resource_pressure_score,
        objective_consequence_clarity_score=objective_consequence_clarity_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
        prophylaxis_signal=prophylaxis_signal,
        opponent_resources_signal=opponent_resources_signal,
        technical_conversion_signal=technical_conversion_signal,
    )

    theme_signals = {
        THEME_PROPHYLAXIS: prophylaxis_signal,
        THEME_OPPONENT_RESOURCES: opponent_resources_signal,
        THEME_TECHNICAL_CONVERSION: technical_conversion_signal,
        THEME_CANDIDATE_MOVES: candidate_moves_signal,
    }
    primary_theme = next(
        (theme for theme, matched in theme_signals.items() if matched),
        None,
    )

    secondary_themes = [
        theme
        for theme, matched in theme_signals.items()
        if matched and theme != primary_theme
    ][:2]

    score, score_reason = score_transferable_idea(
        primary_theme=primary_theme,
        secondary_themes=secondary_themes,
        candidate_richness_score=candidate_richness_score,
        opponent_resource_pressure_score=opponent_resource_pressure_score,
        objective_consequence_clarity_score=objective_consequence_clarity_score,
        difficulty_adequacy_score=difficulty_adequacy_score,
        candidate_count=candidate_count,
        top_move_spread=top_move_spread,
        forcing_after=forcing_after,
        best_move_profile=best_move_profile,
        endgameish=endgameish,
    )

    if primary_theme is None:
        reason = (
            "no_clear_theme_after_strict_rules "
            f"candidate_richness_score={candidate_richness_score} "
            f"candidate_count={candidate_count} "
            f"top_move_spread={top_move_spread} "
            f"opponent_resource_pressure_score={opponent_resource_pressure_score} "
            f"objective_consequence_clarity_score={objective_consequence_clarity_score} "
            f"forcing_after={forcing_after} endgameish={endgameish} "
            f"{candidate_moves_rejection_reason}"
        )
    else:
        reason = (
            f"primary={primary_theme} secondary={secondary_themes} "
            f"{score_reason}"
        )

    return {
        "primary_theme": primary_theme,
        "secondary_themes": secondary_themes,
        "score": score,
        "reason": reason,
        "trace": {
            "theme_priority": [
                THEME_PROPHYLAXIS,
                THEME_OPPONENT_RESOURCES,
                THEME_TECHNICAL_CONVERSION,
                THEME_CANDIDATE_MOVES,
            ],
            "broad_candidate_moves_signal": broad_candidate_moves_signal,
            "candidate_moves_rejection_reason": candidate_moves_rejection_reason,
            "theme_signals": theme_signals,
            "top_move_spread": top_move_spread,
            "best_move_profile": best_move_profile,
            "opponent_response_profile": opponent_response_profile,
            "forcing_after_first_3": forcing_after,
            "endgameish": endgameish,
            "score_reason": score_reason,
            "swing_cp": swing_cp,
        },
    }


def score_transferable_idea(
    *,
    primary_theme: str | None,
    secondary_themes: list[str],
    candidate_richness_score: float,
    opponent_resource_pressure_score: float,
    objective_consequence_clarity_score: float,
    difficulty_adequacy_score: float,
    candidate_count: int | None,
    top_move_spread: int | None,
    forcing_after: int,
    best_move_profile: dict[str, Any],
    endgameish: bool,
) -> tuple[float, str]:
    if primary_theme is None:
        weak_signal = (
            candidate_richness_score >= 2.0
            or opponent_resource_pressure_score >= 2.0
            or objective_consequence_clarity_score >= 2.0
        )
        score = 1.0 if weak_signal else 0.0
        return score, f"no_clear_theme weak_signal={weak_signal}"

    score = 3.0
    reasons: list[str] = [f"base=3.0 for {primary_theme}"]

    if primary_theme == THEME_CANDIDATE_MOVES:
        if candidate_richness_score >= 4.0 and (candidate_count or 0) >= 3:
            score = 3.5
            reasons.append("rich candidate set")
        if (
            candidate_richness_score >= 5.0
            and difficulty_adequacy_score >= 4.0
            and opponent_resource_pressure_score <= 2.0
        ):
            score = 4.0
            reasons.append("very rich decision without dominant resource")
        if top_move_spread is not None and top_move_spread <= CANDIDATE_BAND_CP / 2:
            score += 0.25
            reasons.append("tight top-move spread")

    elif primary_theme == THEME_OPPONENT_RESOURCES:
        if opponent_resource_pressure_score >= 4.0 or objective_consequence_clarity_score >= 4.0:
            score = 4.0
            reasons.append("strong rival resource or clear consequence")
        if opponent_resource_pressure_score >= 4.5 and objective_consequence_clarity_score >= 4.0:
            score = 4.5
            reasons.append("decisive rival resource")
        if forcing_after >= 2:
            score += 0.25
            reasons.append("forcing PV after bad move")

    elif primary_theme == THEME_PROPHYLAXIS:
        if (
            opponent_resource_pressure_score >= 3.5
            and best_move_profile["is_quiet"]
            and forcing_after >= 2
        ):
            score = 4.0
            reasons.append("quiet best move prevents forcing resource")
        if objective_consequence_clarity_score >= 3.0 and candidate_richness_score >= 2.0:
            score += 0.25
            reasons.append("preventive idea has clear objective cost")

    elif primary_theme == THEME_TECHNICAL_CONVERSION:
        if objective_consequence_clarity_score >= 4.0 and (
            endgameish or best_move_profile["is_quiet"]
        ):
            score = 4.0
            reasons.append("clean technical conversion signal")
        if objective_consequence_clarity_score >= 5.0 and opponent_resource_pressure_score <= 1.5:
            score = 4.5
            reasons.append("decisive clean conversion")

    if secondary_themes:
        score += 0.5 if len(secondary_themes) == 1 else 0.75
        reasons.append(f"coherent secondary themes={secondary_themes}")

    if primary_theme == THEME_TECHNICAL_CONVERSION and candidate_richness_score >= 4.0:
        score -= 0.5
        reasons.append("penalty: rich candidate set blurs technical theme")

    if difficulty_adequacy_score < 2.0:
        score -= 0.5
        reasons.append("penalty: low difficulty adequacy")

    return clamp_score(score), "; ".join(reasons)


def build_candidate_moves_rejection_reason(
    *,
    broad_signal: bool,
    strict_signal: bool,
    candidate_choice_is_real: bool,
    candidate_count: int | None,
    candidate_richness_score: float,
    top_move_spread: int | None,
    opponent_resource_pressure_score: float,
    objective_consequence_clarity_score: float,
    difficulty_adequacy_score: float,
    prophylaxis_signal: bool,
    opponent_resources_signal: bool,
    technical_conversion_signal: bool,
) -> str:
    if strict_signal:
        return "strict_candidate_moves_passed"

    reasons: list[str] = []
    if broad_signal:
        reasons.append("strict_candidate_moves_rejected_from_old_broad_signal")
    if not candidate_choice_is_real:
        reasons.append(
            f"not_enough_real_candidate_choice candidate_count={candidate_count}"
        )
    if candidate_richness_score < 3.0:
        reasons.append(f"candidate_richness_score<{3.0}")
    if top_move_spread is None:
        reasons.append("missing_top_move_spread")
    elif top_move_spread > CANDIDATE_BAND_CP * 0.75:
        reasons.append(f"top_move_spread>{CANDIDATE_BAND_CP * 0.75:g}")
    if opponent_resource_pressure_score > 2.0:
        reasons.append("opponent_resource_pressure_dominates")
    if objective_consequence_clarity_score > 3.0:
        reasons.append("consequence_too_forcing_for_candidate_moves")
    if difficulty_adequacy_score < 3.0:
        reasons.append("difficulty_adequacy_too_low")
    if prophylaxis_signal:
        reasons.append("prophylaxis_signal_has_priority")
    if opponent_resources_signal:
        reasons.append("opponent_resources_signal_has_priority")
    if technical_conversion_signal:
        reasons.append("technical_conversion_signal_has_priority")

    return "candidate_moves_not_applicable " + ",".join(reasons)


def compute_top_move_spread(top_moves: list[Mapping[str, Any]]) -> int | None:
    scored_moves = [
        move for move in top_moves if move.get("evaluation_cp") is not None
    ]
    if not scored_moves:
        return None

    top_eval = int(scored_moves[0]["evaluation_cp"])
    moves_in_band = [
        move
        for move in scored_moves
        if top_eval - int(move["evaluation_cp"]) <= CANDIDATE_BAND_CP
    ]
    if not moves_in_band:
        return None

    return top_eval - int(moves_in_band[-1]["evaluation_cp"])


def describe_move_profile(
    fen: str | None,
    move_uci: str | None,
) -> dict[str, Any]:
    profile = {
        "is_valid": False,
        "move": move_uci,
        "is_capture": False,
        "captured_value": 0,
        "gives_check": False,
        "is_promotion": False,
        "is_quiet": False,
    }
    if fen is None or move_uci is None:
        return profile

    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        return profile

    if move not in board.legal_moves:
        return profile

    captured_piece = captured_piece_for_move(board, move)
    is_capture = captured_piece is not None
    gives_check = board.gives_check(move)
    is_promotion = move.promotion is not None

    return {
        "is_valid": True,
        "move": move_uci,
        "is_capture": is_capture,
        "captured_value": (
            PIECE_VALUES.get(captured_piece.piece_type, 0)
            if captured_piece is not None
            else 0
        ),
        "gives_check": gives_check,
        "is_promotion": is_promotion,
        "is_quiet": not is_capture and not gives_check and not is_promotion,
    }


def is_endgameish_position(fen: str | None) -> bool:
    if fen is None:
        return False

    try:
        board = chess.Board(fen)
    except ValueError:
        return False

    non_king_pieces = [
        piece for piece in board.piece_map().values()
        if piece.piece_type != chess.KING
    ]
    queens = [piece for piece in non_king_pieces if piece.piece_type == chess.QUEEN]
    return len(queens) == 0 or len(non_king_pieces) <= 12


def compute_moment_score_partial(
    *,
    candidate_richness_score: float,
    opponent_resource_pressure_score: float,
    objective_consequence_clarity_score: float,
    difficulty_adequacy_score: float,
) -> float:
    weighted_score = (
        candidate_richness_score * SCORE_WEIGHTS["candidate_richness_score"]
        + opponent_resource_pressure_score
        * SCORE_WEIGHTS["opponent_resource_pressure_score"]
        + objective_consequence_clarity_score
        * SCORE_WEIGHTS["objective_consequence_clarity_score"]
        + difficulty_adequacy_score * SCORE_WEIGHTS["difficulty_adequacy_score"]
    )
    return round((weighted_score / 5.0) * 100.0, 2)


def compute_moment_score_with_transferable(
    *,
    moment_score_partial: float,
    transferable_idea_score: float,
) -> float:
    transferable_normalized = (transferable_idea_score / 5.0) * 100.0
    return round(moment_score_partial * 0.8 + transferable_normalized * 0.2, 2)


def first_exclusion_reason(
    checks: list[tuple[str, bool, str]],
) -> str | None:
    for check_name, passed, detail in checks:
        if not passed:
            return f"{check_name}: {detail}"

    return None


def compact_top_moves(top_moves: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "move": move.get("move"),
            "evaluation_cp": move.get("evaluation_cp"),
            "mate": move.get("mate"),
            "multipv": move.get("multipv"),
        }
        for move in top_moves
    ]


def clamp_score(value: float) -> float:
    return round(max(0.0, min(5.0, value)), 2)
