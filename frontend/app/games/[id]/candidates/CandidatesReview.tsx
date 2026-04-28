"use client";

import { useMemo, useState } from "react";

import { FeaturedBoard } from "../../../FeaturedBoard";

type Game = {
  id: number;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
};

type ReviewedCandidate = {
  ply_index: number;
  fullmove_number: number;
  played_move_san: string;
  side_that_played: "w" | "b";
  fen_before: string;
  fen_after: string;
  evaluation_before_cp: number;
  evaluation_after_cp: number;
  swing_cp: number;
  engine_best_move: string | null;
  engine_principal_variation: string[];
};

export type CandidatesReviewPayload = {
  game_id: number;
  depth_used: number;
  swing_threshold_cp: number;
  evaluation_perspective: "white";
  candidate_count: number;
  candidates: ReviewedCandidate[];
};

type CandidatesReviewProps = {
  game: Game;
  review: CandidatesReviewPayload;
};

export function CandidatesReview({ game, review }: CandidatesReviewProps) {
  const [candidateIndex, setCandidateIndex] = useState(0);
  const candidate = review.candidates[candidateIndex];

  const canGoPrevious = candidateIndex > 0;
  const canGoNext = candidateIndex < review.candidates.length - 1;
  const candidateLabel = useMemo(() => {
    if (!candidate) {
      return "0 / 0";
    }

    return `${candidateIndex + 1} / ${review.candidates.length}`;
  }, [candidate, candidateIndex, review.candidates.length]);

  if (!candidate) {
    return (
      <section className="panel empty-state">
        <p className="panel-label">Revision de candidatas</p>
        <h2>Sin candidatas</h2>
        <p>
          No hay jugadas que superen el umbral configurado para esta partida.
        </p>
      </section>
    );
  }

  return (
    <section className="candidate-review" aria-label="Revision de candidatas">
      <div className="game-board-column">
        <div className="candidate-board-heading">
          <p className="panel-label">Posicion previa</p>
          <h2>{formatPlyMove(candidate.ply_index, candidate.played_move_san)}</h2>
        </div>

        <div className="game-board-stage">
          <FeaturedBoard
            boardId={`candidate-${review.game_id}-${candidate.ply_index}`}
            eventName={game.event_name}
            fen={candidate.fen_before}
            positionId={candidate.ply_index}
          />
        </div>

        <div className="move-navigation" aria-label="Navegacion de candidatas">
          <button
            className="nav-button"
            type="button"
            aria-label="Ir a la candidata anterior"
            disabled={!canGoPrevious}
            onClick={() => setCandidateIndex((current) => current - 1)}
          >
            &larr;
          </button>

          <div className="move-status">
            <strong>{candidateLabel}</strong>
            <span>{review.candidate_count} candidatas</span>
          </div>

          <button
            className="nav-button"
            type="button"
            aria-label="Ir a la candidata siguiente"
            disabled={!canGoNext}
            onClick={() => setCandidateIndex((current) => current + 1)}
          >
            &rarr;
          </button>
        </div>
      </div>

      <aside className="panel candidate-info-panel">
        <div className="candidate-title-block">
          <p className="panel-label">Shortlist preliminar</p>
          <h2>{game.event_name}</h2>
          <p className="player-line">
            {game.white_player} vs {game.black_player} - {game.result}
          </p>
        </div>

        <div className="candidate-facts">
          <Fact label="Jugada partida" value={candidate.played_move_san} />
          <Fact
            label="Bando"
            value={candidate.side_that_played === "w" ? "Blancas" : "Negras"}
          />
          <Fact
            label="Mejor motor"
            value={candidate.engine_best_move ?? "Sin linea"}
          />
          <Fact
            label="Swing"
            value={`${candidate.swing_cp} cp`}
            tone={candidate.swing_cp >= 150 ? "strong" : "normal"}
          />
          <Fact
            label="Antes"
            value={formatCentipawns(candidate.evaluation_before_cp)}
          />
          <Fact
            label="Despues"
            value={formatCentipawns(candidate.evaluation_after_cp)}
          />
        </div>

        <div className="candidate-line-block">
          <p className="meta-label">Linea motor</p>
          <p>{formatPrincipalVariation(candidate.engine_principal_variation)}</p>
        </div>

        <div className="candidate-settings">
          <span>Depth {review.depth_used}</span>
          <span>Umbral {review.swing_threshold_cp} cp</span>
        </div>
      </aside>
    </section>
  );
}

function Fact({
  label,
  value,
  tone = "normal",
}: {
  label: string;
  value: string;
  tone?: "normal" | "strong";
}) {
  return (
    <div>
      <span className="meta-label">{label}</span>
      <strong className={tone === "strong" ? "accent-value" : undefined}>
        {value}
      </strong>
    </div>
  );
}

function formatPlyMove(plyIndex: number, sanMove: string): string {
  if (plyIndex % 2 === 1) {
    return `${Math.floor(plyIndex / 2) + 1}. ${sanMove}`;
  }

  return `${plyIndex / 2}... ${sanMove}`;
}

function formatCentipawns(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value} cp`;
}

function formatPrincipalVariation(moves: string[]): string {
  if (moves.length === 0) {
    return "Sin linea";
  }

  return moves.join(" ");
}
