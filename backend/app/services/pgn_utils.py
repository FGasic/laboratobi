from __future__ import annotations

import hashlib
import re


def normalize_pgn_text(pgn_text: str) -> str:
    return pgn_text.replace("\r\n", "\n").strip()


def compute_pgn_hash(pgn_text: str) -> str:
    normalized_pgn = normalize_pgn_text(pgn_text)
    return hashlib.sha256(normalized_pgn.encode("utf-8")).hexdigest()


def normalize_san_for_compare(san_move: str | None) -> str | None:
    if san_move is None:
        return None

    normalized = san_move.strip()
    if not normalized:
        return None

    normalized = re.sub(r"[!?+#]+$", "", normalized).strip()
    normalized = normalized.replace("0-0-0", "O-O-O").replace("0-0", "O-O")

    return normalized or None
