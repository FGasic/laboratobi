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
  const [currentGameIndex, setCurrentGameIndex] = useState(0);
  const [isSessionComplete, setIsSessionComplete] = useState(false);

  const currentGame = games[currentGameIndex] ?? null;
  const hasNextGame = currentGameIndex < games.length - 1;

  if (isSessionComplete) {
    return (
      <main className="game-shell study-shell">
        <section className="panel empty-state study-finish-panel">
          <h2>Session complete</h2>
          <p>You already reviewed every critical moment in this session.</p>
        </section>
      </main>
    );
  }

  if (!currentGame) {
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
        key={currentGame.id}
        apiBaseUrl={apiBaseUrl}
        initialPosition={currentGame.initial_position}
        positions={currentGame.positions}
        criticalMoments={currentGame.critical_moments}
        studyMode={{
          hasNextGame,
          onNextGame: () => {
            if (!hasNextGame) {
              return;
            }

            setCurrentGameIndex((value) => value + 1);
          },
          onCompleteSession: () => {
            setIsSessionComplete(true);
          },
        }}
      />
    </main>
  );
}
