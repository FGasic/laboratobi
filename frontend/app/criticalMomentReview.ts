import type {
  CriticalMoment,
  GamePositionSummary,
} from "./games/[id]/GameInspector";

export const criticalMomentReviewDepth = 25;

export type CriticalMomentReview = {
  ply_index: number;
  played_move_san: string;
  engine_best_move: string | null;
  engine_principal_variation: string[];
  fen_before: string;
  engine_line_eval_cp: number | null;
  engine_line_mate: number | null;
  played_move_eval_cp: number | null;
  played_move_mate: number | null;
  engine_name: string;
  depth_used: number;
};

export type CriticalMomentReviewResponse = {
  moments: CriticalMomentReview[];
};

export function buildReviewedCriticalMoment(
  moment: CriticalMoment,
  positions: GamePositionSummary[],
  review: CriticalMomentReview | undefined,
): CriticalMoment | null {
  if (!review) {
    return null;
  }

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
    played_move_san: review.played_move_san ?? playedMove?.san_move ?? null,
    engine_best_move: review.engine_best_move,
    engine_principal_variation: review.engine_principal_variation,
    fen_before: review.fen_before,
    engine_line_eval_cp: review.engine_line_eval_cp,
    engine_line_mate: review.engine_line_mate,
    played_move_eval_cp: review.played_move_eval_cp,
    played_move_mate: review.played_move_mate,
    engine_name: review.engine_name,
    analysis_depth: review.depth_used,
  };
}
