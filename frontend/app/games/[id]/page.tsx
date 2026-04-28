import {
  type CriticalMoment,
  GameInspector,
  type GamePositionDetail,
} from "./GameInspector";

type Game = {
  id: number;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
  pgn_text: string;
  created_at: string;
};

type GamePositionSummary = {
  ply_index: number;
  fullmove_number: number;
  san_move: string;
  fen: string;
  side_to_move: "w" | "b";
};

type PageProps = {
  params: Promise<{
    id: string;
  }>;
};

const internalApiBaseUrl =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const publicApiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const browserApiBaseUrl = "/api/backend";

export const dynamic = "force-dynamic";

export default async function GamePage({ params }: PageProps) {
  const { id } = await params;
  const gameId = Number(id);

  if (!Number.isInteger(gameId) || gameId < 1) {
    return (
      <GamePageMessage
        title="Invalid game"
        message="The id must be a positive integer."
      />
    );
  }

  const game = await fetchGame(gameId);
  if (!game) {
    return (
      <GamePageMessage
        title="Game not found"
        message="There is no imported game with that id."
      />
    );
  }

  const positions = await fetchGamePositions(gameId);
  if (positions.length === 0) {
    return (
      <GamePageMessage
        title={game.event_name}
        message="This game exists, but it has no moves to inspect."
      />
    );
  }

  const initialPlyIndex = Math.min(49, positions.length);
  const [initialPosition, criticalMoments] = await Promise.all([
    fetchGamePosition(gameId, initialPlyIndex),
    fetchCriticalMoments(gameId),
  ]);
  if (!initialPosition) {
    return (
      <GamePageMessage
        title="We could not load the position"
        message="Check that the PGN is valid and the backend is available."
      />
    );
  }

  return (
    <main className="game-shell">
      <header className="game-header">
        <a href={`${publicApiBaseUrl}/docs`} target="_blank" rel="noreferrer">
          API docs
        </a>
      </header>

      <GameInspector
        apiBaseUrl={browserApiBaseUrl}
        initialPosition={initialPosition}
        positions={positions}
        criticalMoments={criticalMoments}
      />
    </main>
  );
}

async function fetchGame(gameId: number): Promise<Game | null> {
  try {
    const response = await fetch(`${internalApiBaseUrl}/games/${gameId}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as Game;
  } catch {
    return null;
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

async function fetchCriticalMoments(gameId: number): Promise<CriticalMoment[]> {
  try {
    const response = await fetch(
      `${internalApiBaseUrl}/games/${gameId}/critical-moments`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      return [];
    }

    return (await response.json()) as CriticalMoment[];
  } catch {
    return [];
  }
}

function GamePageMessage({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <main className="game-shell">
      <section className="panel empty-state">
        <p className="panel-label">Game inspector</p>
        <h2>{title}</h2>
        <p>{message}</p>
      </section>
    </main>
  );
}
