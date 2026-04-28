import type {
  CriticalMoment,
  GamePositionDetail,
  GamePositionSummary,
} from "../games/[id]/GameInspector";
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

const internalApiBaseUrl =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const browserApiBaseUrl = "/api/backend";

export const dynamic = "force-dynamic";

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
    return [];
  }

  const playableGames = session.games.filter(
    (game) => game.critical_moments.length > 0,
  );
  if (playableGames.length === 0) {
    return [];
  }

  const preparedGames = await Promise.all(
    playableGames.map(async (game) => {
      const [positions, reviewedCandidates] = await Promise.all([
        fetchGamePositions(game.id),
        fetchReviewedCandidates(game.id),
      ]);
      if (positions.length === 0) {
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
        return null;
      }

      const initialPosition = await fetchGamePosition(
        game.id,
        Number(positions[0].ply_index),
      );
      if (!initialPosition) {
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

  return preparedGames.filter(
    (game): game is StudySessionGame => game !== null,
  );
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
  try {
    const response = await fetch(`${internalApiBaseUrl}/games/broadcast/session`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as BroadcastSessionResponse;
  } catch {
    return null;
  }
}

async function fetchReviewedCandidates(
  gameId: number,
): Promise<ReviewedCandidate[]> {
  try {
    const response = await fetch(
      `${internalApiBaseUrl}/analysis/review-game-candidates`,
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
      return [];
    }

    const payload = (await response.json()) as ReviewCandidatesResponse;
    return payload.candidates;
  } catch {
    return [];
  }
}

async function fetchGamePositions(
  gameId: number,
): Promise<GamePositionSummary[]> {
  try {
    const response = await fetch(
      `${internalApiBaseUrl}/games/${gameId}/positions`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      return [];
    }

    return (await response.json()) as GamePositionSummary[];
  } catch {
    return [];
  }
}

async function fetchGamePosition(
  gameId: number,
  plyIndex: number,
): Promise<GamePositionDetail | null> {
  try {
    const response = await fetch(
      `${internalApiBaseUrl}/games/${gameId}/positions/${plyIndex}`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as GamePositionDetail;
  } catch {
    return null;
  }
}
