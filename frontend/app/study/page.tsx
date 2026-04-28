import type {
  CriticalMoment,
  GamePositionDetail,
  GamePositionSummary,
} from "../games/[id]/GameInspector";
import { headers } from "next/headers";

import { StudySession, type StudySessionGame } from "./StudySession";

type BroadcastSessionGame = {
  id: number;
  display_event_name: string;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
  critical_moments_count: number;
  critical_moments: CriticalMoment[];
};

type BroadcastSessionResponse = {
  games: BroadcastSessionGame[];
};

type ReviewedCandidate = {
  ply_index: number;
  played_move_san: string;
  engine_best_move: string | null;
  engine_principal_variation: string[];
  fen_before: string;
};

type ReviewCandidatesResponse = {
  candidates: ReviewedCandidate[];
};

const browserApiBaseUrl = "/api/backend";
const backendProxyBasePath = "/api/backend";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function StudyPage() {
  const games = await loadStudyGames();

  if (games.length === 0) {
    return (
      <main className="game-shell study-shell">
        <section className="panel empty-state study-finish-panel">
          <h2>No critical moments are ready to study.</h2>
          <p>
            Import a serious game from Broadcast and generate active critical
            moments to review it here.
          </p>
        </section>
      </main>
    );
  }

  return <StudySession apiBaseUrl={browserApiBaseUrl} games={games} />;
}

async function loadStudyGames(): Promise<StudySessionGame[]> {
  const session = await fetchBroadcastSession();
  if (!session) {
    console.warn("[study] empty session reason", {
      reason: "broadcast_session_fetch_failed",
    });
    return [];
  }

  if (session.games.length === 0) {
    console.warn("[study] empty session reason", {
      reason: "broadcast_session_has_no_games",
    });
    return [];
  }

  for (const game of session.games) {
    console.warn("[study] session game", {
      gameId: game.id,
      criticalMomentsCount: game.critical_moments.length,
    });
  }

  const playableGames = session.games.filter((game) => {
    const hasMoments = game.critical_moments.length > 0;
    if (!hasMoments) {
      console.warn("[study] game rejected", {
        gameId: game.id,
        reason: "no_critical_moments",
      });
    }
    return hasMoments;
  });
  if (playableGames.length === 0) {
    console.warn("[study] empty session reason", {
      reason: "no_games_with_critical_moments",
      gamesCount: session.games.length,
    });
    return [];
  }

  const preparedGames = await Promise.all(
    playableGames.map(async (game) => {
      const [positions, reviewedCandidates] = await Promise.all([
        fetchGamePositions(game.id),
        fetchReviewedCandidates(game.id),
      ]);
      if (positions.length === 0) {
        console.warn("[study] game rejected", {
          gameId: game.id,
          reason: "positions_fetch_returned_empty",
        });
        return null;
      }

      const reviewByPlayedMovePly = new Map(
        reviewedCandidates.map((candidate) => [candidate.ply_index, candidate]),
      );

      const studyCriticalMoments = game.critical_moments
        .map((moment) =>
          buildStudyCriticalMoment(
            moment,
            positions,
            reviewByPlayedMovePly.get(Number(moment.ply_index)),
          ),
        )
        .filter((moment): moment is CriticalMoment => moment !== null);

      if (studyCriticalMoments.length === 0) {
        console.warn("[study] game rejected", {
          gameId: game.id,
          reason: "all_critical_moments_failed_frontend_normalization",
          backendCriticalMomentsCount: game.critical_moments.length,
        });
        return null;
      }

      const firstStudyMoment = studyCriticalMoments[0];
      const initialPosition = await fetchGamePosition(
        game.id,
        Number(firstStudyMoment.ply_index),
      );
      if (!initialPosition) {
        console.warn("[study] game rejected", {
          gameId: game.id,
          reason: "initial_position_fetch_failed",
          requestedPlyIndex: firstStudyMoment.ply_index,
        });
        return null;
      }

      return {
        id: game.id,
        display_event_name: game.display_event_name,
        event_name: game.event_name,
        white_player: game.white_player,
        black_player: game.black_player,
        result: game.result,
        critical_moments_count: studyCriticalMoments.length,
        critical_moments: studyCriticalMoments,
        positions,
        initial_position: initialPosition,
      } satisfies StudySessionGame;
    }),
  );

  const games = preparedGames.filter(
    (game): game is StudySessionGame => game !== null,
  );
  if (games.length === 0) {
    console.warn("[study] empty session reason", {
      reason: "all_games_rejected_after_preparation",
      playableGamesCount: playableGames.length,
    });
  }

  return games;
}

function buildStudyCriticalMoment(
  moment: CriticalMoment,
  positions: GamePositionSummary[],
  reviewedCandidate: ReviewedCandidate | undefined,
): CriticalMoment | null {
  const playedMovePlyIndex = Number(moment.ply_index);
  if (playedMovePlyIndex < 2) {
    return null;
  }

  const triggerPlyIndex = playedMovePlyIndex - 1;
  const playedMove = positions.find(
    (position) => Number(position.ply_index) === playedMovePlyIndex,
  );

  return {
    ...moment,
    ply_index: triggerPlyIndex,
    played_move_ply_index: playedMovePlyIndex,
    played_move_san: reviewedCandidate?.played_move_san ?? playedMove?.san_move ?? null,
    engine_best_move: reviewedCandidate?.engine_best_move ?? null,
    engine_principal_variation:
      reviewedCandidate?.engine_principal_variation ?? [],
    fen_before: reviewedCandidate?.fen_before ?? null,
  };
}

async function fetchBroadcastSession(): Promise<BroadcastSessionResponse | null> {
  const targetUrl = await buildBackendProxyUrl("/games/broadcast/session");
  console.warn("[study] fetching broadcast session", { url: targetUrl });

  try {
    const response = await fetch(targetUrl, {
      cache: "no-store",
    });
    console.warn("[study] broadcast session response", {
      url: targetUrl,
      status: response.status,
    });

    if (!response.ok) {
      return null;
    }

    const payload = normalizeBroadcastSession(await response.json());
    console.warn("[study] broadcast session games received", {
      url: targetUrl,
      gamesCount: payload.games.length,
    });

    return payload;
  } catch (error) {
    console.error("[study] broadcast session fetch failed", {
      url: targetUrl,
      error,
    });
    return null;
  }
}

async function fetchReviewedCandidates(
  gameId: number,
): Promise<ReviewedCandidate[]> {
  try {
    const targetUrl = await buildBackendProxyUrl(
      "/analysis/review-game-candidates",
    );
    const response = await fetch(
      targetUrl,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          game_id: gameId,
          swing_threshold_cp: 1,
        }),
      },
    );

    if (!response.ok) {
      console.warn("[study] reviewed candidates fetch failed", {
        gameId,
        status: response.status,
      });
      return [];
    }

    const payload = (await response.json()) as ReviewCandidatesResponse;
    return payload.candidates;
  } catch (error) {
    console.error("[study] reviewed candidates fetch threw", { gameId, error });
    return [];
  }
}

async function fetchGamePositions(
  gameId: number,
): Promise<GamePositionSummary[]> {
  try {
    const targetUrl = await buildBackendProxyUrl(`/games/${gameId}/positions`);
    const response = await fetch(targetUrl, { cache: "no-store" });

    if (!response.ok) {
      console.warn("[study] positions fetch failed", {
        gameId,
        status: response.status,
      });
      return [];
    }

    return (await response.json()) as GamePositionSummary[];
  } catch (error) {
    console.error("[study] positions fetch threw", { gameId, error });
    return [];
  }
}

async function fetchGamePosition(
  gameId: number,
  plyIndex: number,
): Promise<GamePositionDetail | null> {
  try {
    const targetUrl = await buildBackendProxyUrl(
      `/games/${gameId}/positions/${plyIndex}`,
    );
    const response = await fetch(targetUrl, { cache: "no-store" });

    if (!response.ok) {
      console.warn("[study] initial position fetch failed", {
        gameId,
        plyIndex,
        status: response.status,
      });
      return null;
    }

    return (await response.json()) as GamePositionDetail;
  } catch (error) {
    console.error("[study] initial position fetch threw", {
      gameId,
      plyIndex,
      error,
    });
    return null;
  }
}

async function buildBackendProxyUrl(path: string): Promise<string> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host?.startsWith("localhost") ? "http" : "https");

  if (!host) {
    const fallbackOrigin = "http://localhost:3000";
    return `${fallbackOrigin}${backendProxyBasePath}${path}`;
  }

  return `${protocol}://${host}${backendProxyBasePath}${path}`;
}

function normalizeBroadcastSession(payload: unknown): BroadcastSessionResponse {
  if (!isRecord(payload) || !Array.isArray(payload.games)) {
    console.warn("[study] broadcast session shape mismatch", {
      reason: "payload_games_is_not_array",
    });
    return { games: [] };
  }

  return {
    games: payload.games
      .map(normalizeBroadcastSessionGame)
      .filter((game): game is BroadcastSessionGame => game !== null),
  };
}

function normalizeBroadcastSessionGame(payload: unknown): BroadcastSessionGame | null {
  if (!isRecord(payload)) {
    console.warn("[study] game shape mismatch", {
      reason: "game_is_not_object",
    });
    return null;
  }

  const id = Number(payload.id);
  if (!Number.isInteger(id) || id < 1) {
    console.warn("[study] game shape mismatch", {
      reason: "invalid_game_id",
      rawId: payload.id,
    });
    return null;
  }

  const criticalMoments = Array.isArray(payload.critical_moments)
    ? payload.critical_moments
        .map((moment) => normalizeCriticalMoment(moment, id))
        .filter((moment): moment is CriticalMoment => moment !== null)
    : [];

  if (!Array.isArray(payload.critical_moments)) {
    console.warn("[study] game critical_moments shape mismatch", {
      gameId: id,
      reason: "critical_moments_is_not_array",
      criticalMomentsCount: Number(payload.critical_moments_count) || 0,
    });
  }

  return {
    id,
    display_event_name: stringOrFallback(
      payload.display_event_name,
      "Broadcast game",
    ),
    event_name: stringOrFallback(payload.event_name, "Broadcast game"),
    white_player: stringOrFallback(payload.white_player, "White"),
    black_player: stringOrFallback(payload.black_player, "Black"),
    result: stringOrFallback(payload.result, "*"),
    critical_moments_count:
      Number(payload.critical_moments_count) || criticalMoments.length,
    critical_moments: criticalMoments,
  };
}

function normalizeCriticalMoment(
  payload: unknown,
  fallbackGameId: number,
): CriticalMoment | null {
  if (!isRecord(payload)) {
    console.warn("[study] critical moment shape mismatch", {
      gameId: fallbackGameId,
      reason: "critical_moment_is_not_object",
    });
    return null;
  }

  const id = Number(payload.id);
  const gameId = Number(payload.game_id) || fallbackGameId;
  const plyIndex = Number(payload.ply_index);
  const momentNumber = Number(payload.moment_number) || 1;
  if (!Number.isInteger(id) || !Number.isInteger(plyIndex)) {
    console.warn("[study] critical moment shape mismatch", {
      gameId,
      reason: "invalid_id_or_ply_index",
      rawId: payload.id,
      rawPlyIndex: payload.ply_index,
    });
    return null;
  }

  return {
    id,
    game_id: gameId,
    ply_index: plyIndex,
    moment_number: momentNumber,
    title: nullableString(payload.title),
    label: nullableString(payload.label),
    notes: nullableString(payload.notes),
    is_active: payload.is_active !== false,
    created_at: stringOrFallback(payload.created_at, ""),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringOrFallback(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
