from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine

from app.core.config import settings

DEFAULT_DEPTH = 12
ENGINE_TIMEOUT_SECONDS = 10.0
LINUX_CONTAINER_STOCKFISH_PATH = Path("/usr/games/stockfish")
WINDOWS_LOCAL_STOCKFISH_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "stockfish.exe"
)

logger = logging.getLogger("uvicorn.error")


class InvalidFenError(Exception):
    pass


class StockfishConfigurationError(Exception):
    pass


class StockfishEngineError(Exception):
    pass


@dataclass(frozen=True)
class StockfishPathResolution:
    path: Path
    platform_mode: str
    configured_path: str | None
    reason: str


def evaluate_fen(fen: str, depth: int | None = None) -> dict[str, Any]:
    board = parse_board(fen)
    depth_used = depth or DEFAULT_DEPTH

    engine = None
    try:
        engine = open_stockfish_engine()
        return analyse_board(engine, board, fen, depth_used)
    except (OSError, chess.engine.EngineError, TimeoutError) as exc:
        raise StockfishEngineError(
            f"Stockfish failed while evaluating the FEN: {exc}"
        ) from exc
    finally:
        if engine is not None:
            try:
                engine.quit()
            except (OSError, chess.engine.EngineError, TimeoutError):
                pass


def evaluate_fens(fens: list[str], depth: int | None = None) -> list[dict[str, Any]]:
    boards = [parse_board(fen) for fen in fens]
    depth_used = depth or DEFAULT_DEPTH

    engine = None
    try:
        engine = open_stockfish_engine()
        return [
            analyse_board(engine, board, fen, depth_used)
            for board, fen in zip(boards, fens)
        ]
    except (OSError, chess.engine.EngineError, TimeoutError) as exc:
        raise StockfishEngineError(
            f"Stockfish failed while evaluating the FEN list: {exc}"
        ) from exc
    finally:
        if engine is not None:
            try:
                engine.quit()
            except (OSError, chess.engine.EngineError, TimeoutError):
                pass


def evaluate_fens_top_moves(
    fens: list[str],
    depth: int | None = None,
    multipv: int = 5,
) -> list[list[dict[str, Any]]]:
    boards = [parse_board(fen) for fen in fens]
    depth_used = depth or DEFAULT_DEPTH

    engine = None
    try:
        engine = open_stockfish_engine()
        return [
            analyse_board_top_moves(engine, board, fen, depth_used, multipv)
            for board, fen in zip(boards, fens)
        ]
    except (OSError, chess.engine.EngineError, TimeoutError) as exc:
        raise StockfishEngineError(
            f"Stockfish failed while evaluating top moves: {exc}"
        ) from exc
    finally:
        if engine is not None:
            try:
                engine.quit()
            except (OSError, chess.engine.EngineError, TimeoutError):
                pass


def analyse_board(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    fen: str,
    depth_used: int,
) -> dict[str, Any]:
    info = engine.analyse(board, chess.engine.Limit(depth=depth_used))
    score = info.get("score")
    if score is None:
        raise StockfishEngineError("Stockfish did not return an evaluation score.")

    score_for_side_to_move = score.pov(board.turn)
    mate = score_for_side_to_move.mate()
    evaluation_cp = score_for_side_to_move.score() if mate is None else None
    score_for_white = score.white()
    mate_white = score_for_white.mate()
    evaluation_white_cp = score_for_white.score() if mate_white is None else None
    principal_variation = [move.uci() for move in info.get("pv", [])]

    return {
        "fen": fen,
        "evaluation_cp": evaluation_cp,
        "mate": mate,
        "evaluation_white_cp": evaluation_white_cp,
        "mate_white": mate_white,
        "best_move": principal_variation[0] if principal_variation else None,
        "principal_variation": principal_variation,
        "depth_used": int(info.get("depth") or depth_used),
    }


def analyse_board_top_moves(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    fen: str,
    depth_used: int,
    multipv: int,
) -> list[dict[str, Any]]:
    infos = engine.analyse(
        board,
        chess.engine.Limit(depth=depth_used),
        multipv=max(1, multipv),
    )
    if isinstance(infos, dict):
        infos = [infos]

    top_moves: list[dict[str, Any]] = []
    for info_index, info in enumerate(infos, start=1):
        score = info.get("score")
        principal_variation = info.get("pv", [])
        if score is None or not principal_variation:
            continue

        score_for_side_to_move = score.pov(board.turn)
        mate = score_for_side_to_move.mate()
        evaluation_cp = score_for_side_to_move.score() if mate is None else None
        score_for_white = score.white()
        mate_white = score_for_white.mate()
        evaluation_white_cp = score_for_white.score() if mate_white is None else None

        top_moves.append(
            {
                "fen": fen,
                "move": principal_variation[0].uci(),
                "evaluation_cp": evaluation_cp,
                "mate": mate,
                "evaluation_white_cp": evaluation_white_cp,
                "mate_white": mate_white,
                "principal_variation": [
                    move.uci() for move in principal_variation
                ],
                "depth_used": int(info.get("depth") or depth_used),
                "multipv": int(info.get("multipv") or info_index),
            }
        )

    return sorted(top_moves, key=lambda move: move["multipv"])


def parse_board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise InvalidFenError(f"Invalid FEN: {exc}") from exc

    if not board.is_valid():
        raise InvalidFenError(
            "Invalid FEN: position is not a valid standard chess position."
        )

    return board


def get_stockfish_path() -> str:
    resolution = resolve_stockfish_path()
    validate_stockfish_resolution(resolution)
    return str(resolution.path)


def open_stockfish_engine() -> chess.engine.SimpleEngine:
    resolution = resolve_stockfish_path()
    try:
        validate_stockfish_resolution(resolution)
    except StockfishConfigurationError as exc:
        log_stockfish_resolution(
            event="stockfish_engine_invocation",
            resolution=resolution,
            invocation_ok=False,
            failure_reason=str(exc),
        )
        raise

    stockfish_path = str(resolution.path)

    try:
        engine = chess.engine.SimpleEngine.popen_uci(
            [stockfish_path],
            timeout=ENGINE_TIMEOUT_SECONDS,
        )
    except (OSError, chess.engine.EngineError, TimeoutError) as exc:
        log_stockfish_resolution(
            event="stockfish_engine_invocation",
            resolution=resolution,
            invocation_ok=False,
            failure_reason=str(exc),
        )
        raise

    log_stockfish_resolution(
        event="stockfish_engine_invocation",
        resolution=resolution,
        invocation_ok=True,
    )
    return engine


def log_stockfish_startup_resolution() -> None:
    try:
        resolution = resolve_stockfish_path()
        validate_stockfish_resolution(resolution)
    except StockfishConfigurationError as exc:
        resolution = resolve_stockfish_path()
        log_stockfish_resolution(
            event="stockfish_startup_resolution",
            resolution=resolution,
            invocation_ok=False,
            failure_reason=str(exc),
        )
        return

    log_stockfish_resolution(
        event="stockfish_startup_resolution",
        resolution=resolution,
    )


def resolve_stockfish_path() -> StockfishPathResolution:
    configured_path = normalize_configured_stockfish_path(settings.stockfish_path)
    system_name = platform.system().lower()

    if system_name == "linux":
        return StockfishPathResolution(
            path=LINUX_CONTAINER_STOCKFISH_PATH,
            platform_mode=get_linux_platform_mode(),
            configured_path=configured_path,
            reason=get_linux_resolution_reason(configured_path),
        )

    if system_name == "windows":
        if configured_path and Path(configured_path).suffix.lower() == ".exe":
            return StockfishPathResolution(
                path=Path(configured_path),
                platform_mode="windows_local",
                configured_path=configured_path,
                reason="windows_local_configured_exe",
            )

        reason = "windows_local_repo_exe"
        if configured_path:
            reason = "windows_local_ignored_non_windows_path"

        return StockfishPathResolution(
            path=WINDOWS_LOCAL_STOCKFISH_PATH,
            platform_mode="windows_local",
            configured_path=configured_path,
            reason=reason,
        )

    return StockfishPathResolution(
        path=Path(""),
        platform_mode=f"unsupported_{system_name or 'unknown'}",
        configured_path=configured_path,
        reason="unsupported_platform",
    )


def validate_stockfish_resolution(resolution: StockfishPathResolution) -> None:
    if resolution.reason == "unsupported_platform":
        raise StockfishConfigurationError(
            "Stockfish platform is unsupported. Expected Linux container or "
            "Windows local runtime."
        )

    executable = resolution.path
    if not executable.exists():
        raise StockfishConfigurationError(
            "Stockfish binary was not found at resolved_stockfish_path="
            f"'{executable}' with stockfish_platform_mode="
            f"'{resolution.platform_mode}'."
        )

    if executable.is_dir():
        raise StockfishConfigurationError(
            "Resolved Stockfish path points to a directory, not a binary: "
            f"'{executable}'."
        )

    if not os.access(executable, os.X_OK):
        raise StockfishConfigurationError(
            f"Stockfish binary is not executable: '{executable}'."
        )


def normalize_configured_stockfish_path(stockfish_path: str | None) -> str | None:
    if stockfish_path is None:
        return None

    normalized_path = stockfish_path.strip()
    return normalized_path or None


def get_linux_platform_mode() -> str:
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "linux_container"

    return "linux_local"


def get_linux_resolution_reason(configured_path: str | None) -> str:
    if configured_path is None:
        return "linux_runtime_system_stockfish"

    if Path(configured_path).suffix.lower() == ".exe":
        return "linux_runtime_ignored_windows_exe"

    if Path(configured_path) != LINUX_CONTAINER_STOCKFISH_PATH:
        return "linux_runtime_forced_system_stockfish"

    return "linux_runtime_configured_system_stockfish"


def log_stockfish_resolution(
    *,
    event: str,
    resolution: StockfishPathResolution,
    invocation_ok: bool | None = None,
    failure_reason: str | None = None,
) -> None:
    log_method = logger.error if failure_reason else logger.info
    invocation_field = ""
    if invocation_ok is not None:
        invocation_field = f" stockfish_invocation_ok={format_bool(invocation_ok)}"

    failure_field = ""
    if failure_reason:
        failure_field = f" stockfish_failure_reason={failure_reason!r}"

    log_method(
        "%s resolved_stockfish_path=%s stockfish_platform_mode=%s "
        "stockfish_exists=%s configured_stockfish_path=%s "
        "stockfish_resolution_reason=%s%s%s",
        event,
        resolution.path,
        resolution.platform_mode,
        format_bool(resolution.path.exists()),
        resolution.configured_path or "unset",
        resolution.reason,
        invocation_field,
        failure_field,
    )


def format_bool(value: bool) -> str:
    return "true" if value else "false"
