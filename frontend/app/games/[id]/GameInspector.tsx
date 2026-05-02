"use client";

import { Chess } from "chess.js";
import { useCallback, useEffect, useMemo, useState } from "react";

import { FeaturedBoard, type BoardSolutionMove } from "../../FeaturedBoard";

export type GamePositionSummary = {
  ply_index: number;
  fullmove_number: number;
  san_move: string;
  fen: string;
  side_to_move: "w" | "b";
};

export type GamePositionDetail = GamePositionSummary & {
  game_id: number;
  event_name: string;
  white_player: string;
  black_player: string;
  result: string;
  from_square: string;
  to_square: string;
  next_moves: string[];
};

export type CriticalMoment = {
  id: number;
  game_id: number;
  ply_index: number;
  moment_number: number;
  title: string | null;
  label: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  played_move_ply_index?: number;
  played_move_san?: string | null;
  engine_best_move?: string | null;
  engine_principal_variation?: string[];
  fen_before?: string | null;
  engine_line_eval_cp?: number | null;
  engine_line_mate?: number | null;
  played_move_eval_cp?: number | null;
  played_move_mate?: number | null;
  engine_name?: string | null;
  analysis_depth?: number | null;
};

export type StudyModeConfig = {
  onNextGame: () => void;
};

type GameInspectorProps = {
  apiBaseUrl: string;
  initialPosition: GamePositionDetail;
  positions: GamePositionSummary[];
  criticalMoments: CriticalMoment[];
  studyMode?: StudyModeConfig;
};

const AUTO_PLAY_DELAY_MS = 400;
const DEFAULT_CRITICAL_MOMENT_REVIEW_DEPTH = 25;

export function GameInspector({
  apiBaseUrl,
  initialPosition,
  positions,
  criticalMoments,
  studyMode,
}: GameInspectorProps) {
  const [position, setPosition] = useState(initialPosition);
  const [selectedPlyIndex, setSelectedPlyIndex] = useState(
    initialPosition.ply_index,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [showContinuation, setShowContinuation] = useState(false);
  const [isAutoPlaying, setIsAutoPlaying] = useState(false);
  const [revealedCriticalMomentIds, setRevealedCriticalMomentIds] = useState<
    number[]
  >([]);

  const isStudyMode = studyMode !== undefined;
  const lastPlyIndex = positions.length;
  const currentPlyIndex = Number(position.ply_index);
  const activeCriticalMoments = useMemo(
    () =>
      [...criticalMoments]
        .filter((moment) => moment.is_active)
        .sort((left, right) => Number(left.ply_index) - Number(right.ply_index)),
    [criticalMoments],
  );
  const currentCriticalMoment = activeCriticalMoments.find(
    (moment) => Number(moment.ply_index) === currentPlyIndex,
  );
  const currentCriticalMomentId = currentCriticalMoment?.id;
  const currentCriticalMomentVisualIndex =
    currentCriticalMomentId === undefined
      ? null
      : activeCriticalMoments.findIndex(
            (moment) => moment.id === currentCriticalMomentId,
          ) + 1;
  const criticalMomentLabel =
    currentCriticalMomentVisualIndex === null
      ? null
      : activeCriticalMoments.length <= 1
        ? "CRITICAL MOMENT"
        : `CRITICAL MOMENT ${currentCriticalMomentVisualIndex}`;
  const isCriticalMoment = currentCriticalMoment !== undefined;
  const isCriticalSolutionRevealed =
    currentCriticalMomentId !== undefined &&
    revealedCriticalMomentIds.includes(currentCriticalMomentId);
  const isCriticalMomentLocked = isCriticalMoment && !isCriticalSolutionRevealed;
  const canGoPrevious = position.ply_index > 1 && !isLoading;
  const canGoNext =
    position.ply_index < lastPlyIndex && !isLoading && !isCriticalMomentLocked;
  const canAutoPlay =
    currentPlyIndex < lastPlyIndex && !isLoading && !isCriticalMomentLocked;
  const isAtGameEnd = currentPlyIndex >= lastPlyIndex;
  const finalResultLabel = isAtGameEnd
    ? getFinalResultLabel(position.result)
    : null;
  const sideToMoveLabel =
    position.side_to_move === "w" ? "White to move" : "Black to move";
  const viewerTitle = criticalMomentLabel ?? "LaboraTobi";
  const viewerModeClass = isCriticalMoment ? "viewer-critical" : "viewer-normal";
  const showPlySelector =
    !isStudyMode &&
    showContinuation &&
    (!isCriticalMoment || isCriticalSolutionRevealed);
  const showRegularContinuation =
    !isStudyMode && showContinuation && !isCriticalMoment;
  const nextStudyMoment = getNextStudyMoment(
    currentPlyIndex,
    activeCriticalMoments,
  );
  const revealedSolutionMove = useMemo(
    () =>
      isCriticalSolutionRevealed
        ? getBoardSolutionMove(
            currentCriticalMoment?.fen_before ?? position.fen,
            currentCriticalMoment?.engine_best_move,
          )
        : null,
    [
      currentCriticalMoment?.engine_best_move,
      currentCriticalMoment?.fen_before,
      isCriticalSolutionRevealed,
      position.fen,
    ],
  );

  const revealCriticalSolution = useCallback(() => {
    if (currentCriticalMomentId === undefined) {
      return;
    }

    setIsAutoPlaying(false);
    setRevealedCriticalMomentIds((momentIds) =>
      momentIds.includes(currentCriticalMomentId)
        ? momentIds
        : [...momentIds, currentCriticalMomentId],
    );
    setShowContinuation(true);
  }, [currentCriticalMomentId]);

  const loadPosition = useCallback(
    async (nextPlyIndex: number) => {
      const clampedPlyIndex = Math.min(Math.max(nextPlyIndex, 1), lastPlyIndex);
      const requestUrl = `${apiBaseUrl}/games/${initialPosition.game_id}/positions/${clampedPlyIndex}`;

      setSelectedPlyIndex(clampedPlyIndex);
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await fetch(requestUrl, { cache: "no-store" });

        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as {
            detail?: string | { message?: string };
          } | null;
          const detail =
            typeof payload?.detail === "string"
              ? payload.detail
              : payload?.detail?.message;
          throw new Error(
            detail ??
              `We could not load the requested position (HTTP ${response.status}).`,
          );
        }

        const nextPosition = (await response.json()) as GamePositionDetail;
        setPosition(nextPosition);
      } catch (error) {
        console.error("Failed to load game position", {
          error,
          gameId: initialPosition.game_id,
          requestedPlyIndex: clampedPlyIndex,
          requestUrl,
        });

        setErrorMessage(
          error instanceof Error
            ? error.message === "Failed to fetch"
              ? `We could not load ply ${clampedPlyIndex}. Check the backend connection.`
              : error.message
            : "We could not load that position.",
        );
        setIsAutoPlaying(false);
      } finally {
        setIsLoading(false);
      }
    },
    [apiBaseUrl, initialPosition.game_id, lastPlyIndex],
  );

  const goToPly = useCallback(
    (nextPlyIndex: number, options?: { preserveAutoPlay?: boolean }) => {
      if (!options?.preserveAutoPlay) {
        setIsAutoPlaying(false);
      }

      void loadPosition(nextPlyIndex);
    },
    [loadPosition],
  );

  const handlePreviousPosition = useCallback(() => {
    if (!canGoPrevious) {
      return;
    }

    goToPly(position.ply_index - 1);
  }, [canGoPrevious, goToPly, position.ply_index]);

  const handleNextPosition = useCallback(() => {
    if (!canGoNext) {
      return;
    }

    goToPly(position.ply_index + 1);
  }, [canGoNext, goToPly, position.ply_index]);

  const toggleAutoPlay = useCallback(() => {
    if (isAutoPlaying) {
      setIsAutoPlaying(false);
      return;
    }

    if (!canAutoPlay) {
      return;
    }

    setIsAutoPlaying(true);
  }, [canAutoPlay, isAutoPlaying]);

  const handleStudyContinue = useCallback(() => {
    if (!currentCriticalMoment || !isCriticalSolutionRevealed) {
      return;
    }

    const targetPlyIndex =
      currentCriticalMoment.played_move_ply_index ?? currentPlyIndex + 1;
    if (targetPlyIndex === currentPlyIndex) {
      return;
    }

    goToPly(Number(targetPlyIndex));
  }, [
    currentCriticalMoment,
    currentPlyIndex,
    goToPly,
    isCriticalSolutionRevealed,
  ]);

  const handleStudyEndOfGame = useCallback(() => {
    if (!studyMode) {
      return;
    }

    studyMode.onNextGame();
  }, [studyMode]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLSelectElement ||
        target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      if (event.key === "ArrowLeft" && canGoPrevious) {
        event.preventDefault();
        goToPly(position.ply_index - 1);
      }

      if (event.key === "ArrowRight" && canGoNext) {
        event.preventDefault();
        goToPly(position.ply_index + 1);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canGoNext, canGoPrevious, goToPly, position.ply_index]);

  useEffect(() => {
    if (!isAutoPlaying) {
      return;
    }

    if (isLoading) {
      return;
    }

    if (isCriticalMomentLocked || currentPlyIndex >= lastPlyIndex) {
      setIsAutoPlaying(false);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void loadPosition(currentPlyIndex + 1);
    }, AUTO_PLAY_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [
    currentPlyIndex,
    isAutoPlaying,
    isCriticalMomentLocked,
    isLoading,
    lastPlyIndex,
    loadPosition,
  ]);

  if (isStudyMode && studyMode) {
    return (
      <section
        className={`game-viewer study-viewer ${viewerModeClass}`}
        aria-label="Study session"
      >
        <header className="study-focus-header">
          <h1>LaboraTobi</h1>
          <div className="study-focus-summary" aria-label="Game details">
            <p className="study-focus-event">{position.event_name}</p>
            <p className="study-focus-players">
              <span className="study-focus-player">{position.white_player}</span>
              <span className="study-focus-separator" aria-hidden="true">
                vs
              </span>
              <span className="study-focus-player">{position.black_player}</span>
            </p>
          </div>
        </header>

        <div className="study-stage">
          <div className="game-board-column study-board-column">
            <div className="game-board-stage">
              <FeaturedBoard
                boardId={`game-${position.game_id}-ply-${position.ply_index}`}
                eventName={position.event_name}
                fen={position.fen}
                highlightedSquares={[position.from_square, position.to_square]}
                positionId={position.ply_index}
                solutionMove={revealedSolutionMove}
                variant={isCriticalMoment ? "critical" : "default"}
              />
            </div>
          </div>

          <aside className="panel study-control-panel">
            <div className="study-control-summary">
              <strong>{formatPlyMove(position.ply_index, position.san_move)}</strong>
              <span>{isAtGameEnd ? "Game complete" : sideToMoveLabel}</span>
              {criticalMomentLabel ? (
                <span className="study-critical-indicator">{criticalMomentLabel}</span>
              ) : null}
            </div>

            {isCriticalMoment ? (
              <div className="study-critical-block">
                {isCriticalSolutionRevealed ? (
                  <>
                    <div className="study-solution-block">
                      <p className="panel-label">Solution</p>
                      <CriticalMomentSolution moment={currentCriticalMoment} />
                    </div>

                    <button
                      className="primary-button study-next-button"
                      type="button"
                      onClick={studyMode.onNextGame}
                    >
                      Next Game
                    </button>

                    <button
                      className="primary-button study-next-button"
                      type="button"
                      onClick={handleStudyContinue}
                    >
                      Continue game
                    </button>
                  </>
                ) : (
                  <button
                    className="critical-action-button study-friction-button"
                    type="button"
                    onClick={revealCriticalSolution}
                  >
                    View solution
                  </button>
                )}
              </div>
            ) : (
              <>
                <div
                  className="move-navigation move-navigation-with-play study-navigation"
                  aria-label="Move navigation"
                >
                  <button
                    className="nav-button"
                    type="button"
                    aria-label="Go to previous position"
                    disabled={!canGoPrevious}
                    onClick={handlePreviousPosition}
                  >
                    &larr;
                  </button>

                  <div className="move-status study-navigation-status">
                    <span>
                      {isAtGameEnd
                        ? finalResultLabel
                          ? "Game complete"
                          : "You reached the end of this game."
                        : ""}
                    </span>
                  </div>

                  <button
                    className="nav-button play-button"
                    type="button"
                    aria-label={
                      isAutoPlaying
                        ? "Pause automatic playback"
                        : "Play game automatically"
                    }
                    aria-pressed={isAutoPlaying}
                    disabled={!isAutoPlaying && !canAutoPlay}
                    onClick={toggleAutoPlay}
                  >
                    {isAutoPlaying ? "Pause" : "Play"}
                  </button>

                  <button
                    className="nav-button"
                    type="button"
                    aria-label="Go to next position"
                    disabled={!canGoNext}
                    onClick={handleNextPosition}
                  >
                    &rarr;
                  </button>
                </div>

                {!nextStudyMoment && isAtGameEnd ? (
                  <>
                    {finalResultLabel ? (
                      <div className="study-final-result" aria-live="polite">
                        <span>Game complete</span>
                        <strong>{finalResultLabel}</strong>
                      </div>
                    ) : null}

                    <button
                      className="primary-button study-next-button"
                      type="button"
                      onClick={handleStudyEndOfGame}
                    >
                      Next Game
                    </button>
                  </>
                ) : null}
              </>
            )}
          </aside>

          {errorMessage ? <p className="error-text">{errorMessage}</p> : null}
        </div>
      </section>
    );
  }

  return (
    <section className={`game-viewer ${viewerModeClass}`} aria-label="Game viewer">
      <div className="game-board-column">
        <div className="game-title-stage" aria-live="polite">
          <div
            className={
              currentCriticalMoment
                ? "critical-moment-title"
                : "viewer-default-title"
            }
            data-current-ply={position.ply_index}
          >
            <span>{viewerTitle}</span>
          </div>
        </div>

        <div className="game-board-stage">
          <FeaturedBoard
            boardId={`game-${position.game_id}-ply-${position.ply_index}`}
            eventName={position.event_name}
            fen={position.fen}
            highlightedSquares={[position.from_square, position.to_square]}
            positionId={position.ply_index}
            solutionMove={revealedSolutionMove}
            variant={isCriticalMoment ? "critical" : "default"}
          />
        </div>

        {!isCriticalMomentLocked ? (
          <div
            className="move-navigation move-navigation-with-play"
            aria-label="Move navigation"
          >
            <button
              className="nav-button"
              type="button"
              aria-label="Go to previous position"
              disabled={!canGoPrevious}
              onClick={handlePreviousPosition}
            >
              &larr;
            </button>

            <div className="move-status">
              <strong>{formatPlyMove(position.ply_index, position.san_move)}</strong>
              <span>{isAtGameEnd ? "Game complete" : sideToMoveLabel}</span>
            </div>

            <button
              className="nav-button play-button"
              type="button"
              aria-label={
                isAutoPlaying
                  ? "Pause automatic playback"
                  : "Play game automatically"
              }
              aria-pressed={isAutoPlaying}
              disabled={!isAutoPlaying && !canAutoPlay}
              onClick={toggleAutoPlay}
            >
              {isAutoPlaying ? "Pause" : "Play"}
            </button>

            <button
              className="nav-button"
              type="button"
              aria-label="Go to next position"
              disabled={!canGoNext}
              onClick={handleNextPosition}
            >
              &rarr;
            </button>
          </div>
        ) : null}

        {showPlySelector ? (
          <div className="ply-fallback">
            <label className="field-label" htmlFor="ply-index">
              Go to move
            </label>
            <select
              id="ply-index"
              className="select-control"
              value={selectedPlyIndex}
              disabled={isLoading}
              onChange={(event) => {
                void loadPosition(Number(event.target.value));
              }}
            >
              {positions.map((option) => (
                <option key={option.ply_index} value={option.ply_index}>
                  {formatPlyMove(option.ply_index, option.san_move)}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {errorMessage ? <p className="error-text">{errorMessage}</p> : null}
      </div>

      <aside className="panel game-info-panel">
        <div className="game-meta-list">
          <div>
            <span className="meta-label">Event</span>
            <strong>{position.event_name}</strong>
          </div>
          <div>
            <span className="meta-label">White</span>
            <strong>{position.white_player}</strong>
          </div>
          <div>
            <span className="meta-label">Black</span>
            <strong>{position.black_player}</strong>
          </div>
          {finalResultLabel ? (
            <div className="final-result-row">
              <span className="meta-label">Game complete</span>
              <strong>{finalResultLabel}</strong>
            </div>
          ) : (
            <div>
              <span className="meta-label">Side to move</span>
              <strong>{position.side_to_move === "w" ? "White" : "Black"}</strong>
            </div>
          )}
        </div>

        {isCriticalMoment ? (
          <div className="critical-control-block">
            {isCriticalSolutionRevealed ? (
              <div className="critical-solution-block">
                <p className="panel-label">Solution</p>
                <CriticalMomentSolution moment={currentCriticalMoment} />
              </div>
            ) : (
              <button
                className="critical-action-button"
                type="button"
                onClick={revealCriticalSolution}
              >
                View solution
              </button>
            )}
          </div>
        ) : (
          <>
            <button
              className="primary-button"
              type="button"
              onClick={() => setShowContinuation(true)}
            >
              View continuation
            </button>

            {showRegularContinuation ? (
              <div className="continuation-block">
                <p className="panel-label">Continuation</p>
                <MoveLineList
                  emptyText="There are no more moves in the game."
                  moves={position.next_moves}
                  startPlyIndex={position.ply_index + 1}
                />
              </div>
            ) : null}
          </>
        )}
      </aside>
    </section>
  );
}

function CriticalMomentSolution({ moment }: { moment: CriticalMoment }) {
  const engineLineSummary = formatAnalysisSummary({
    evalCp: moment.engine_line_eval_cp,
    mate: moment.engine_line_mate,
    engineName: moment.engine_name,
    depth: moment.analysis_depth,
  });
  const playedMoveSummary = formatAnalysisSummary({
    evalCp: moment.played_move_eval_cp,
    mate: moment.played_move_mate,
    engineName: moment.engine_name,
    depth: moment.analysis_depth,
  });

  return (
    <div className="study-solution-copy">
      <p>
        <strong>Engine line {engineLineSummary}:</strong>{" "}
        {formatPrincipalVariation(
          moment.played_move_ply_index,
          moment.engine_principal_variation ?? [],
        )}
      </p>
      <p>
        <strong>Played move {playedMoveSummary}:</strong>{" "}
        {formatMaybePlyMove(
          moment.played_move_ply_index,
          moment.played_move_san,
          "Not available.",
        )}
      </p>
    </div>
  );
}

function MoveLineList({
  moves,
  startPlyIndex,
  emptyText,
}: {
  moves: string[];
  startPlyIndex: number;
  emptyText: string;
}) {
  if (moves.length === 0) {
    return <p className="muted-text">{emptyText}</p>;
  }

  return (
    <ul className="continuation-list">
      {moves.map((move, index) => {
        const continuationPlyIndex = startPlyIndex + index;
        return (
          <li key={`${move}-${continuationPlyIndex}`}>
            {formatPlyMove(continuationPlyIndex, move)}
          </li>
        );
      })}
    </ul>
  );
}

function formatPlyMove(plyIndex: number, sanMove: string): string {
  if (plyIndex % 2 === 1) {
    return `${Math.floor(plyIndex / 2) + 1}. ${sanMove}`;
  }

  return `${plyIndex / 2}... ${sanMove}`;
}

function getNextStudyMoment(
  currentPlyIndex: number,
  criticalMoments: CriticalMoment[],
): CriticalMoment | null {
  return (
    criticalMoments.find(
      (moment) => Number(moment.ply_index) > currentPlyIndex,
    ) ?? null
  );
}

function formatMaybePlyMove(
  plyIndex: number | undefined,
  sanMove: string | null | undefined,
  fallback: string,
): string {
  if (!plyIndex || !sanMove) {
    return fallback;
  }

  return formatPlyMove(plyIndex, sanMove);
}

function formatPrincipalVariation(
  startPlyIndex: number | undefined,
  moves: string[],
): string {
  if (!startPlyIndex || moves.length === 0) {
    return "Not available.";
  }

  return moves
    .map((move, index) => formatPlyMove(startPlyIndex + index, move))
    .join(" ");
}

function formatAnalysisSummary({
  evalCp,
  mate,
  engineName,
  depth,
}: {
  evalCp: number | null | undefined;
  mate: number | null | undefined;
  engineName: string | null | undefined;
  depth: number | null | undefined;
}): string {
  const normalizedEngineName = engineName?.trim() || "Stockfish";
  const depthUsed =
    typeof depth === "number" && Number.isFinite(depth)
      ? depth
      : DEFAULT_CRITICAL_MOMENT_REVIEW_DEPTH;

  return `{${formatEvaluation(evalCp, mate)} ${normalizedEngineName} depth:${depthUsed}}`;
}

function formatEvaluation(
  evalCp: number | null | undefined,
  mate: number | null | undefined,
): string {
  if (typeof mate === "number" && Number.isFinite(mate)) {
    return mate > 0 ? `M+${mate}` : `M${mate}`;
  }

  if (typeof evalCp !== "number" || !Number.isFinite(evalCp)) {
    return "n/a";
  }

  const pawns = evalCp / 100;
  const normalizedPawns = Math.abs(pawns) < 0.05 ? 0 : pawns;
  const sign = normalizedPawns > 0 ? "+" : "";
  return `${sign}${normalizedPawns.toFixed(1)}`;
}

function getFinalResultLabel(result: string): string | null {
  const normalizedResult = result.trim();
  if (normalizedResult === "1-0") {
    return "White wins";
  }

  if (normalizedResult === "0-1") {
    return "Black wins";
  }

  if (normalizedResult === "1/2-1/2") {
    return "Draw";
  }

  return null;
}

function getBoardSolutionMove(
  fen: string,
  moveText: string | null | undefined,
): BoardSolutionMove | null {
  const normalizedMove = normalizeEngineMoveText(moveText);
  if (!normalizedMove) {
    return null;
  }

  const uciMatch = normalizedMove.match(/^([a-h][1-8])([a-h][1-8])([qrbn])?$/i);
  if (uciMatch) {
    try {
      const chess = new Chess(fen);
      const move = chess.move({
        from: uciMatch[1].toLowerCase(),
        to: uciMatch[2].toLowerCase(),
        promotion: uciMatch[3]?.toLowerCase(),
      });
      return { from: move.from, to: move.to };
    } catch {
      return null;
    }
  }

  try {
    const chess = new Chess(fen);
    const move = chess.move(normalizedMove, { strict: false });
    return { from: move.from, to: move.to };
  } catch {
    return null;
  }
}

function normalizeEngineMoveText(
  moveText: string | null | undefined,
): string | null {
  if (!moveText) {
    return null;
  }

  const normalized = moveText
    .trim()
    .replace(/^\d+\.(?:\.\.)?\s*/, "")
    .replace(/[!?]+$/g, "")
    .replace(/^0-0-0/i, "O-O-O")
    .replace(/^0-0/i, "O-O");

  return normalized || null;
}
