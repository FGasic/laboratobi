import {
  CandidatesReview,
  type CandidatesReviewPayload,
} from "./CandidatesReview";

type Game = {
  id: number;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
};

type PageProps = {
  params: Promise<{
    id: string;
  }>;
  searchParams?: Promise<{
    depth?: string;
    threshold?: string;
    swing_threshold_cp?: string;
  }>;
};

const internalApiBaseUrl =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const publicApiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const defaultDepth = 8;
const defaultSwingThresholdCp = 100;

export const dynamic = "force-dynamic";

export default async function GameCandidatesPage({
  params,
  searchParams,
}: PageProps) {
  const { id } = await params;
  const query = searchParams ? await searchParams : {};
  const gameId = Number(id);

  if (!Number.isInteger(gameId) || gameId < 1) {
    return (
      <GameCandidatesMessage
        title="Partida invalida"
        message="El id debe ser un numero entero positivo."
      />
    );
  }

  const depth = readPositiveInteger(query.depth, defaultDepth);
  const swingThresholdCp = readPositiveInteger(
    query.swing_threshold_cp ?? query.threshold,
    defaultSwingThresholdCp,
  );

  const [game, review] = await Promise.all([
    fetchGame(gameId),
    fetchCandidatesReview(gameId, depth, swingThresholdCp),
  ]);

  if (!game) {
    return (
      <GameCandidatesMessage
        title="Partida no encontrada"
        message="No existe una partida importada con ese id."
      />
    );
  }

  if (!review) {
    return (
      <GameCandidatesMessage
        title="No pudimos cargar candidatas"
        message="Revisa que el backend y Stockfish esten disponibles."
      />
    );
  }

  return (
    <main className="game-shell">
      <header className="game-header">
        <a className="header-link-left" href={`/games/${game.id}`}>
          Partida
        </a>
        <h1>LaboraTobi</h1>
        <a href={`${publicApiBaseUrl}/docs`} target="_blank" rel="noreferrer">
          API docs
        </a>
      </header>

      <CandidatesReview game={game} review={review} />
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

async function fetchCandidatesReview(
  gameId: number,
  depth: number,
  swingThresholdCp: number,
): Promise<CandidatesReviewPayload | null> {
  try {
    const response = await fetch(
      `${internalApiBaseUrl}/analysis/review-game-candidates`,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          game_id: gameId,
          depth,
          swing_threshold_cp: swingThresholdCp,
        }),
      },
    );

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as CandidatesReviewPayload;
  } catch {
    return null;
  }
}

function readPositiveInteger(
  value: string | undefined,
  fallback: number,
): number {
  const parsedValue = Number(value);
  if (!Number.isInteger(parsedValue) || parsedValue < 1) {
    return fallback;
  }

  return parsedValue;
}

function GameCandidatesMessage({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <main className="game-shell">
      <section className="panel empty-state">
        <p className="panel-label">Revision de candidatas</p>
        <h2>{title}</h2>
        <p>{message}</p>
      </section>
    </main>
  );
}
