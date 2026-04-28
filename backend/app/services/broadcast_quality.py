from __future__ import annotations

import math
import re
from typing import Any, Literal


BLOCKING_NAME_KEYWORDS = {
    "puzzle",
    "puzzles",
    "study",
    "studies",
    "training",
    "trainer",
    "lesson",
    "exercise",
    "tactic",
    "tactics",
    "practice",
}
SERIOUS_EVENT_KEYWORDS = {
    "championship",
    "championships",
    "masters",
    "master",
    "grandmaster",
    "invitational",
    "superbet",
    "bundesliga",
    "olympiad",
    "olympiade",
    "candidates",
    "grand swiss",
    "grand prix",
    "world cup",
    "continental",
    "memorial",
    "classical",
    "cup",
    "fide",
}
RECOGNIZED_TITLES = {
    "GM",
    "IM",
    "FM",
    "CM",
    "WGM",
    "WIM",
    "WFM",
    "WCM",
    "NM",
    "WNM",
}
SHORT_GAME_PLY_THRESHOLD = 12
SETUP_BLOCK_RATIO = 0.4
NOISE_BLOCK_RATIO = 0.7
SERIOUS_SCORE_THRESHOLD = 55
BASE_QUALITY_SCORE = 45
TITLE_MANY_BONUS = 18
TITLE_SOME_BONUS = 10
FIDE_ID_MANY_BONUS = 12
FIDE_ID_SOME_BONUS = 6
HIGH_RATING_BONUS = 16
MID_RATING_BONUS = 12
LOW_MASTER_RATING_BONUS = 8
SOME_RATING_BONUS = 4
SERIOUS_NAME_BONUS = 10
KNOWN_PLAYERS_BONUS = 6
LONG_GAMES_BONUS = 10
MEDIUM_GAMES_BONUS = 6
CONSISTENT_METADATA_BONUS = 6
NO_TITLES_PENALTY = 8
NO_RATINGS_PENALTY = 8
NO_FIDE_IDS_PENALTY = 8
UNKNOWN_PLAYERS_HIGH_PENALTY = 12
UNKNOWN_PLAYERS_SOME_PENALTY = 6
SHORT_GAMES_HIGH_PENALTY = 12
SHORT_GAMES_SOME_PENALTY = 6
SPARSE_METADATA_HIGH_PENALTY = 10
SINGLE_SUSPICIOUS_EVENT_PENALTY = 12
SOME_SETUP_PENALTY = 10


def evaluate_broadcast_quality(round_data: dict[str, Any]) -> dict[str, Any]:
    games = round_data.get("games") or []
    games_analyzed = len(games)
    if games_analyzed == 0:
        return {
            "is_serious_gm_broadcast": False,
            "quality_score": 0,
            "confidence": "high",
            "reasons": ["No games were available in the round preview."],
            "blocking_reasons": ["Broadcast round contains no games."],
            "summary": {
                "games_analyzed": 0,
                "games_with_titles": 0,
                "games_with_ratings": 0,
                "games_with_fide_ids": 0,
                "average_known_rating": None,
                "average_ply_count": 0,
                "short_games_count": 0,
                "setup_games_count": 0,
                "unknown_player_count": 0,
            },
        }

    round_text = " ".join(
        [
            normalize_text(round_data.get("tournament_name")),
            normalize_text(round_data.get("round_name")),
        ]
    )
    suspicious_event_name_count = 0
    games_with_titles = 0
    games_with_ratings = 0
    games_with_fide_ids = 0
    short_games_count = 0
    setup_games_count = 0
    unknown_player_count = 0
    sparse_metadata_games_count = 0
    rating_values: list[int] = []
    ply_counts: list[int] = []

    for game in games:
        white_title = normalize_title(game.get("white_title"))
        black_title = normalize_title(game.get("black_title"))
        title_count = int(white_title in RECOGNIZED_TITLES) + int(
            black_title in RECOGNIZED_TITLES
        )
        if title_count > 0:
            games_with_titles += 1

        game_ratings = extract_known_ratings(game)
        if game_ratings:
            games_with_ratings += 1
            rating_values.extend(game_ratings)

        fide_id_count = int(bool(game.get("white_fide_id"))) + int(
            bool(game.get("black_fide_id"))
        )
        if fide_id_count > 0:
            games_with_fide_ids += 1

        if is_unknown_player_name(game.get("white_player")):
            unknown_player_count += 1
        if is_unknown_player_name(game.get("black_player")):
            unknown_player_count += 1

        ply_count = int(game.get("ply_count") or 0)
        ply_counts.append(ply_count)
        if 0 < ply_count <= SHORT_GAME_PLY_THRESHOLD:
            short_games_count += 1

        if bool(game.get("is_setup_position")) or normalize_text(
            game.get("variant")
        ) == "from position":
            setup_games_count += 1

        if title_count == 0 and not game_ratings and fide_id_count == 0:
            sparse_metadata_games_count += 1

        if contains_blocking_keyword(game.get("event_name")):
            suspicious_event_name_count += 1

    average_known_rating = (
        round(sum(rating_values) / len(rating_values)) if rating_values else None
    )
    average_ply_count = round(sum(ply_counts) / len(ply_counts), 1) if ply_counts else 0

    blocking_reasons: list[str] = []
    reasons: list[str] = []

    if contains_blocking_keyword(round_text):
        blocking_reasons.append(
            "Tournament or round name contains puzzle/study/training keywords."
        )

    if setup_games_count >= threshold_count(games_analyzed, SETUP_BLOCK_RATIO):
        blocking_reasons.append(
            "A large share of games are from setup/from-position PGNs."
        )

    if suspicious_event_name_count >= threshold_count(games_analyzed, SETUP_BLOCK_RATIO):
        blocking_reasons.append(
            "Many game event names contain puzzle/study/training keywords."
        )

    if (
        games_analyzed >= 3
        and short_games_count >= threshold_count(games_analyzed, NOISE_BLOCK_RATIO)
        and unknown_player_count >= threshold_count(games_analyzed * 2, NOISE_BLOCK_RATIO)
        and games_with_titles == 0
        and games_with_ratings == 0
        and games_with_fide_ids == 0
    ):
        blocking_reasons.append(
            "Round looks like obvious low-information noise: very short games, unknown players, and no serious metadata."
        )

    quality_score = BASE_QUALITY_SCORE

    if games_with_titles >= threshold_count(games_analyzed, 0.25):
        quality_score += TITLE_MANY_BONUS
        reasons.append(
            f"{games_with_titles} games include recognized chess titles (+{TITLE_MANY_BONUS})."
        )
    elif games_with_titles > 0:
        quality_score += TITLE_SOME_BONUS
        reasons.append(
            f"{games_with_titles} games include recognized chess titles (+{TITLE_SOME_BONUS})."
        )
    else:
        quality_score -= NO_TITLES_PENALTY
        reasons.append(f"No recognized titles found (-{NO_TITLES_PENALTY}).")

    if average_known_rating is not None:
        if average_known_rating >= 2500:
            quality_score += HIGH_RATING_BONUS
            reasons.append(
                f"Average known rating is {average_known_rating} (+{HIGH_RATING_BONUS})."
            )
        elif average_known_rating >= 2350:
            quality_score += MID_RATING_BONUS
            reasons.append(
                f"Average known rating is {average_known_rating} (+{MID_RATING_BONUS})."
            )
        elif average_known_rating >= 2200:
            quality_score += LOW_MASTER_RATING_BONUS
            reasons.append(
                f"Average known rating is {average_known_rating} (+{LOW_MASTER_RATING_BONUS})."
            )
        else:
            quality_score += SOME_RATING_BONUS
            reasons.append(
                f"Some ratings are present, average known rating is {average_known_rating} (+{SOME_RATING_BONUS})."
            )
    else:
        quality_score -= NO_RATINGS_PENALTY
        reasons.append(f"No ratings found (-{NO_RATINGS_PENALTY}).")

    if games_with_fide_ids >= threshold_count(games_analyzed, 0.25):
        quality_score += FIDE_ID_MANY_BONUS
        reasons.append(
            f"{games_with_fide_ids} games include FIDE IDs (+{FIDE_ID_MANY_BONUS})."
        )
    elif games_with_fide_ids > 0:
        quality_score += FIDE_ID_SOME_BONUS
        reasons.append(
            f"{games_with_fide_ids} games include FIDE IDs (+{FIDE_ID_SOME_BONUS})."
        )
    else:
        quality_score -= NO_FIDE_IDS_PENALTY
        reasons.append(f"No FIDE IDs found (-{NO_FIDE_IDS_PENALTY}).")

    if contains_serious_event_keyword(round_text):
        quality_score += SERIOUS_NAME_BONUS
        reasons.append(
            f"Tournament or round name looks like a serious event (+{SERIOUS_NAME_BONUS})."
        )

    if unknown_player_count == 0 and games_analyzed >= 2:
        quality_score += KNOWN_PLAYERS_BONUS
        reasons.append(
            f"Player names are known across the round (+{KNOWN_PLAYERS_BONUS})."
        )
    elif unknown_player_count >= threshold_count(games_analyzed * 2, 0.5):
        quality_score -= UNKNOWN_PLAYERS_HIGH_PENALTY
        reasons.append(
            f"Many players are unknown placeholders (-{UNKNOWN_PLAYERS_HIGH_PENALTY})."
        )
    elif unknown_player_count > 0:
        quality_score -= UNKNOWN_PLAYERS_SOME_PENALTY
        reasons.append(
            f"Some players are unknown placeholders (-{UNKNOWN_PLAYERS_SOME_PENALTY})."
        )

    if average_ply_count >= 40:
        quality_score += LONG_GAMES_BONUS
        reasons.append(
            f"Average game length is {average_ply_count} plies (+{LONG_GAMES_BONUS})."
        )
    elif average_ply_count >= 28:
        quality_score += MEDIUM_GAMES_BONUS
        reasons.append(
            f"Average game length is {average_ply_count} plies (+{MEDIUM_GAMES_BONUS})."
        )

    if short_games_count >= threshold_count(games_analyzed, 0.5):
        quality_score -= SHORT_GAMES_HIGH_PENALTY
        reasons.append(
            f"Many games are very short (-{SHORT_GAMES_HIGH_PENALTY})."
        )
    elif short_games_count > 0:
        quality_score -= SHORT_GAMES_SOME_PENALTY
        reasons.append(
            f"Some games are very short (-{SHORT_GAMES_SOME_PENALTY})."
        )

    if sparse_metadata_games_count >= threshold_count(games_analyzed, 0.5):
        quality_score -= SPARSE_METADATA_HIGH_PENALTY
        reasons.append(
            f"Most games have sparse metadata (-{SPARSE_METADATA_HIGH_PENALTY})."
        )
    elif sparse_metadata_games_count <= math.floor(games_analyzed / 3):
        quality_score += CONSISTENT_METADATA_BONUS
        reasons.append(
            f"Metadata looks reasonably consistent across the round (+{CONSISTENT_METADATA_BONUS})."
        )

    if suspicious_event_name_count > 0 and suspicious_event_name_count < threshold_count(
        games_analyzed,
        SETUP_BLOCK_RATIO,
    ):
        quality_score -= SINGLE_SUSPICIOUS_EVENT_PENALTY
        reasons.append(
            f"Some game event names look like puzzles/studies (-{SINGLE_SUSPICIOUS_EVENT_PENALTY})."
        )

    if 0 < setup_games_count < threshold_count(games_analyzed, SETUP_BLOCK_RATIO):
        quality_score -= SOME_SETUP_PENALTY
        reasons.append(
            f"Some games are from setup/from-position PGNs (-{SOME_SETUP_PENALTY})."
        )

    quality_score = max(0, min(100, quality_score))
    is_serious = not blocking_reasons and quality_score >= SERIOUS_SCORE_THRESHOLD

    return {
        "is_serious_gm_broadcast": is_serious,
        "quality_score": quality_score,
        "confidence": infer_confidence(
            games_analyzed=games_analyzed,
            quality_score=quality_score,
            blocking_reasons=blocking_reasons,
        ),
        "reasons": reasons,
        "blocking_reasons": blocking_reasons,
        "summary": {
            "games_analyzed": games_analyzed,
            "games_with_titles": games_with_titles,
            "games_with_ratings": games_with_ratings,
            "games_with_fide_ids": games_with_fide_ids,
            "average_known_rating": average_known_rating,
            "average_ply_count": average_ply_count,
            "short_games_count": short_games_count,
            "setup_games_count": setup_games_count,
            "unknown_player_count": unknown_player_count,
        },
    }


def contains_blocking_keyword(value: Any) -> bool:
    normalized = normalize_text(value)
    return any(keyword in normalized for keyword in BLOCKING_NAME_KEYWORDS)


def contains_serious_event_keyword(value: Any) -> bool:
    normalized = normalize_text(value)
    return any(keyword in normalized for keyword in SERIOUS_EVENT_KEYWORDS)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    normalized = str(value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def normalize_title(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().upper()
    return normalized or None


def extract_known_ratings(game: dict[str, Any]) -> list[int]:
    rating_values: list[int] = []
    for key in ("white_elo", "black_elo"):
        rating_value = parse_int(game.get(key))
        if rating_value is not None:
            rating_values.append(rating_value)

    return rating_values


def parse_int(value: Any) -> int | None:
    if value is None:
        return None

    normalized = str(value).strip()
    if not normalized.isdigit():
        return None

    return int(normalized)


def is_unknown_player_name(value: Any) -> bool:
    normalized = normalize_text(value)
    return normalized.startswith("unknown ")


def threshold_count(total: int, ratio: float) -> int:
    return max(1, math.ceil(total * ratio))


def infer_confidence(
    *,
    games_analyzed: int,
    quality_score: int,
    blocking_reasons: list[str],
) -> Literal["low", "medium", "high"]:
    if blocking_reasons:
        return "high" if games_analyzed >= 2 or len(blocking_reasons) >= 2 else "medium"

    if games_analyzed >= 4 and (quality_score >= 75 or quality_score <= 35):
        return "high"

    if games_analyzed >= 2 and (quality_score >= 60 or quality_score <= 45):
        return "medium"

    return "low"
