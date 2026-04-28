from __future__ import annotations

import json
import re
from io import StringIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import chess.pgn

from app.services.pgn_utils import compute_pgn_hash


LICHESS_HOST = "lichess.org"
ROUND_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{8}$")
DEFAULT_TIMEOUT_SECONDS = 20
PGN_SNIPPET_LENGTH = 600
USER_AGENT = "LaboraTobi/0.1"


class BroadcastPreviewError(Exception):
    pass


def fetch_broadcast_round_data(
    *,
    round_id: str | None,
    round_url: str | None = None,
) -> dict[str, Any]:
    resolved_round_id = resolve_round_id(round_id=round_id, round_url=round_url)
    round_metadata = fetch_round_metadata(resolved_round_id)
    round_pgn = fetch_round_pgn(resolved_round_id)

    metadata_games = round_metadata.get("games")
    games = build_broadcast_games(round_pgn)
    games_found = len(metadata_games) if isinstance(metadata_games, list) else len(games)

    round_info = round_metadata.get("round") or {}
    tournament_info = round_metadata.get("tour") or {}
    resolved_round_url = build_round_url(
        round_id=resolved_round_id,
        round_payload=round_info,
    )

    return {
        "source_type": "broadcast",
        "source_url": resolved_round_url,
        "source_host": LICHESS_HOST,
        "round_id": resolved_round_id,
        "round_url": resolved_round_url,
        "tournament_id": string_or_none(tournament_info.get("id")),
        "tournament_name": clean_value(
            tournament_info.get("name"),
            fallback="Unknown broadcast tournament",
        ),
        "round_name": clean_value(
            round_info.get("name"),
            fallback="Unknown round",
        ),
        "games_found": games_found,
        "games": games,
    }


def fetch_broadcast_round_preview(
    *,
    round_id: str | None,
    round_url: str | None,
    limit: int,
    include_pgn_text: bool,
) -> dict[str, Any]:
    resolved_round_id = resolve_round_id(round_id=round_id, round_url=round_url)
    round_data = fetch_broadcast_round_data(round_id=resolved_round_id)
    preview_games = [
        serialize_broadcast_game(
            game,
            include_pgn_text=include_pgn_text,
        )
        for game in round_data["games"][:limit]
    ]

    return {
        "source_type": round_data["source_type"],
        "source_url": round_data["source_url"],
        "source_host": round_data["source_host"],
        "round_id": round_data["round_id"],
        "round_url": round_data["round_url"],
        "tournament_id": round_data["tournament_id"],
        "tournament_name": round_data["tournament_name"],
        "round_name": round_data["round_name"],
        "games_found": round_data["games_found"],
        "games_previewed": len(preview_games),
        "games": preview_games,
    }


def resolve_round_id(*, round_id: str | None, round_url: str | None) -> str:
    if round_id:
        normalized_round_id = round_id.strip()
        validate_round_id(normalized_round_id)
        return normalized_round_id

    if not round_url:
        raise BroadcastPreviewError("Provide round_id or round_url.")

    parsed_url = urlparse(round_url)
    if parsed_url.netloc not in {LICHESS_HOST, f"www.{LICHESS_HOST}"}:
        raise BroadcastPreviewError("round_url must point to lichess.org.")

    path_segments = [segment for segment in parsed_url.path.split("/") if segment]
    if len(path_segments) < 4 or path_segments[0] != "broadcast":
        raise BroadcastPreviewError(
            "round_url must point to a concrete Lichess Broadcast round."
        )

    candidate_round_id = path_segments[3]
    validate_round_id(candidate_round_id)
    return candidate_round_id


def validate_round_id(round_id: str) -> None:
    if not ROUND_ID_PATTERN.fullmatch(round_id):
        raise BroadcastPreviewError("round_id must be an 8-character Lichess ID.")


def fetch_round_metadata(round_id: str) -> dict[str, Any]:
    metadata_url = f"https://{LICHESS_HOST}/api/broadcast/-/-/{round_id}"
    try:
        payload = fetch_json(metadata_url)
    except BroadcastPreviewError as exc:
        raise BroadcastPreviewError(
            f"Could not fetch Lichess Broadcast round metadata: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise BroadcastPreviewError("Lichess Broadcast metadata response was invalid.")

    return payload


def fetch_round_pgn(round_id: str) -> str:
    pgn_url = (
        f"https://{LICHESS_HOST}/api/broadcast/round/{round_id}.pgn"
        "?clocks=false&comments=false"
    )
    try:
        pgn_text = fetch_text(pgn_url)
    except BroadcastPreviewError as exc:
        raise BroadcastPreviewError(
            f"Could not fetch Lichess Broadcast round PGN: {exc}"
        ) from exc

    if not pgn_text.strip():
        raise BroadcastPreviewError("Lichess Broadcast round PGN was empty.")

    return pgn_text


def fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise build_http_error(url, exc) from exc
    except URLError as exc:
        raise BroadcastPreviewError(f"network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise BroadcastPreviewError(f"invalid JSON payload: {exc}") from exc


def fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/x-chess-pgn, text/plain",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        raise build_http_error(url, exc) from exc
    except URLError as exc:
        raise BroadcastPreviewError(f"network error: {exc.reason}") from exc


def build_http_error(url: str, exc: HTTPError) -> BroadcastPreviewError:
    if exc.code == 404:
        return BroadcastPreviewError(f"resource not found at {url}")

    return BroadcastPreviewError(f"HTTP {exc.code} from {url}")


def build_broadcast_games(pgn_text: str) -> list[dict[str, Any]]:
    handle = StringIO(pgn_text)
    broadcast_games: list[dict[str, Any]] = []

    while True:
        parsed_game = chess.pgn.read_game(handle)
        if parsed_game is None:
            break

        normalized_pgn = export_pgn(parsed_game)
        headers = parsed_game.headers
        game_url = first_non_empty(
            headers.get("GameURL"),
            headers.get("Site"),
        )
        ply_count = sum(1 for _ in parsed_game.mainline_moves())
        is_setup_position = string_or_none(headers.get("SetUp")) == "1"

        broadcast_games.append(
            {
                "event_name": clean_value(
                    headers.get("Event"),
                    fallback="Unknown event",
                ),
                "white_player": clean_value(
                    headers.get("White"),
                    fallback="Unknown white player",
                ),
                "black_player": clean_value(
                    headers.get("Black"),
                    fallback="Unknown black player",
                ),
                "result": clean_value(headers.get("Result"), fallback="*"),
                "external_id": extract_game_id(game_url),
                "game_url": game_url,
                "site_url": string_or_none(headers.get("Site")),
                "variant": string_or_none(headers.get("Variant")),
                "white_title": string_or_none(headers.get("WhiteTitle")),
                "black_title": string_or_none(headers.get("BlackTitle")),
                "white_elo": string_or_none(headers.get("WhiteElo")),
                "black_elo": string_or_none(headers.get("BlackElo")),
                "white_fide_id": string_or_none(headers.get("WhiteFideId")),
                "black_fide_id": string_or_none(headers.get("BlackFideId")),
                "ply_count": ply_count,
                "is_setup_position": is_setup_position,
                "pgn_hash": compute_pgn_hash(normalized_pgn),
                "pgn_snippet": build_pgn_snippet(normalized_pgn),
                "pgn_text": normalized_pgn,
            }
        )

    return broadcast_games


def serialize_broadcast_game(
    game: dict[str, Any],
    *,
    include_pgn_text: bool,
) -> dict[str, Any]:
    return {
        "event_name": game["event_name"],
        "white_player": game["white_player"],
        "black_player": game["black_player"],
        "result": game["result"],
        "external_id": game["external_id"],
        "game_url": game["game_url"],
        "site_url": game["site_url"],
        "variant": game["variant"],
        "white_title": game["white_title"],
        "black_title": game["black_title"],
        "white_elo": game["white_elo"],
        "black_elo": game["black_elo"],
        "white_fide_id": game["white_fide_id"],
        "black_fide_id": game["black_fide_id"],
        "pgn_snippet": game["pgn_snippet"],
        "pgn_text": game["pgn_text"] if include_pgn_text else None,
    }


def export_pgn(parsed_game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(
        headers=True,
        variations=True,
        comments=True,
    )
    return parsed_game.accept(exporter).strip()


def build_pgn_snippet(pgn_text: str) -> str:
    normalized_pgn = " ".join(pgn_text.split())
    if len(normalized_pgn) <= PGN_SNIPPET_LENGTH:
        return normalized_pgn

    return f"{normalized_pgn[:PGN_SNIPPET_LENGTH].rstrip()}..."


def build_round_url(round_id: str, round_payload: dict[str, Any]) -> str:
    payload_url = string_or_none(round_payload.get("url"))
    if payload_url:
        return payload_url

    return f"https://{LICHESS_HOST}/broadcast/-/-/{round_id}"


def extract_game_id(game_url: str | None) -> str | None:
    if not game_url:
        return None

    parsed_url = urlparse(game_url)
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]
    if not path_segments:
        return None

    candidate_game_id = path_segments[-1]
    return candidate_game_id if ROUND_ID_PATTERN.fullmatch(candidate_game_id) else None


def clean_value(value: Any, fallback: str) -> str:
    if value is None:
        return fallback

    normalized = str(value).strip()
    if not normalized or normalized == "?":
        return fallback

    return normalized


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        normalized = string_or_none(value)
        if normalized is not None:
            return normalized

    return None
