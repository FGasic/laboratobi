from __future__ import annotations

from typing import Any

import chess


def build_critical_moment_review_payload(
    *,
    positions: list[Any],
    evaluations: list[dict[str, Any]],
    ply_index: int,
) -> dict[str, Any] | None:
    position_index = ply_index - 1
    previous_index = position_index - 1
    if previous_index < 0 or position_index >= len(positions):
        return None

    position_before = positions[previous_index]
    position_after = positions[position_index]
    if previous_index >= len(evaluations) or position_index >= len(evaluations):
        return None

    evaluation_before = evaluations[previous_index]
    evaluation_after = evaluations[position_index]

    return build_critical_moment_review_payload_from_position_pair(
        ply_index=ply_index,
        position_before=position_before,
        position_after=position_after,
        evaluation_before=evaluation_before,
        evaluation_after=evaluation_after,
    )


def build_critical_moment_review_payload_from_position_pair(
    *,
    ply_index: int,
    position_before: Any,
    position_after: Any,
    evaluation_before: dict[str, Any],
    evaluation_after: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    evaluation_before_cp = evaluation_before.get("evaluation_white_cp")
    if evaluation_before_cp is None:
        return None

    evaluation_after_cp = (
        evaluation_after.get("evaluation_white_cp")
        if evaluation_after is not None
        else evaluation_before_cp
    )
    if evaluation_after_cp is None:
        return None

    engine_best_move = format_engine_move_san(
        position_before.fen,
        evaluation_before.get("best_move"),
    )
    engine_principal_variation = format_engine_line_san(
        position_before.fen,
        evaluation_before.get("principal_variation") or [],
    )

    return {
        "ply_index": ply_index,
        "fullmove_number": position_after.fullmove_number,
        "played_move_san": position_after.san_move,
        "side_that_played": position_before.side_to_move,
        "fen_before": position_before.fen,
        "fen_after": position_after.fen,
        "evaluation_before_cp": evaluation_before_cp,
        "evaluation_after_cp": evaluation_after_cp,
        "swing_cp": abs(evaluation_after_cp - evaluation_before_cp),
        "engine_best_move": engine_best_move,
        "engine_principal_variation": engine_principal_variation,
    }


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
