"use client";

import { useState } from "react";

import {
  type CriticalMoment,
  GameInspector,
  type GamePositionDetail,
  type GamePositionSummary,
} from "../games/[id]/GameInspector";

export type StudySessionGame = {
  id: number;
  display_event_name: string;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
  critical_moments_count: number;
  critical_moments: CriticalMoment[];
  positions: GamePositionSummary[];
  initial_position: GamePositionDetail;
};

type StudySessionProps = {
  apiBaseUrl: string;
  games: StudySessionGame[];
};

export function StudySession({ apiBaseUrl, games }: StudySessionProps) {
  const [currentGameIndex, setCurrentGameIndex] = useState(
    () => findNextStudyGameIndex(games, -1) ?? 0,
  );
  const [gameVisitKey, setGameVisitKey] = useState(0);

  const currentGame = games[currentGameIndex] ?? null;

  if (!currentGame || !hasStudyCriticalMoments(currentGame)) {
    return (
      <main className="game-shell study-shell">
        <section className="panel empty-state study-finish-panel">
          <h2>We could not prepare the session.</h2>
          <p>Reload the page or check that the backend is available.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="game-shell study-shell">
      <GameInspector
        key={`${currentGame.id}-${gameVisitKey}`}
        apiBaseUrl={apiBaseUrl}
        initialPosition={currentGame.initial_position}
        positions={currentGame.positions}
        criticalMoments={currentGame.critical_moments}
        studyMode={{
          onNextGame: () => {
            setCurrentGameIndex((value) => {
              const nextIndex = findNextStudyGameIndex(games, value);
              return nextIndex ?? value;
            });
            setGameVisitKey((value) => value + 1);
          },
        }}
      />
    </main>
  );
}

function findNextStudyGameIndex(
  games: StudySessionGame[],
  currentIndex: number,
): number | null {
  if (games.length === 0) {
    return null;
  }

  for (let offset = 1; offset <= games.length; offset += 1) {
    const nextIndex = (currentIndex + offset + games.length) % games.length;
    if (hasStudyCriticalMoments(games[nextIndex])) {
      return nextIndex;
    }
  }

  return null;
}

function hasStudyCriticalMoments(
  game: StudySessionGame | null | undefined,
): game is StudySessionGame {
  return (
    game !== null &&
    game !== undefined &&
    game.critical_moments.some((moment) => moment.is_active !== false)
  );
}
