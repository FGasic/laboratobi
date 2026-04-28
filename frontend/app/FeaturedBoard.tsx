"use client";

import type { CSSProperties, ReactNode } from "react";
import { Chessboard } from "react-chessboard";

export type BoardSolutionMove = {
  from: string;
  to: string;
};

type FeaturedBoardProps = {
  boardId?: string;
  eventName: string;
  fen: string;
  highlightedSquares?: string[];
  positionId: number;
  solutionMove?: BoardSolutionMove | null;
  variant?: "default" | "critical";
};

const boardPalettes = {
  default: {
    darkSquare: "#7F919B",
    lightSquare: "#DAD8CF",
    highlightBackground: "rgba(228, 180, 71, 0.36)",
    highlightRing: "rgba(139, 99, 31, 0.34)",
    notationOnDark: "rgba(242, 246, 247, 0.8)",
    notationOnLight: "rgba(45, 58, 67, 0.72)",
    solutionArrow: "rgba(237, 182, 55, 0.86)",
    solutionFill: "rgba(246, 205, 86, 0.34)",
    solutionRing: "rgba(224, 159, 31, 0.92)",
  },
  critical: {
    darkSquare: "#5E8BA8",
    lightSquare: "#E1EAF0",
    highlightBackground: "rgba(244, 192, 64, 0.34)",
    highlightRing: "rgba(237, 182, 55, 0.52)",
    notationOnDark: "rgba(247, 251, 252, 0.86)",
    notationOnLight: "rgba(41, 68, 86, 0.72)",
    solutionArrow: "rgba(247, 203, 66, 0.92)",
    solutionFill: "rgba(251, 213, 78, 0.4)",
    solutionRing: "rgba(246, 194, 54, 0.98)",
  },
} as const;

export function FeaturedBoard({
  boardId,
  eventName,
  fen,
  highlightedSquares = [],
  positionId,
  solutionMove,
  variant = "default",
}: FeaturedBoardProps) {
  const palette = boardPalettes[variant];
  const squareStyles = highlightedSquares.reduce<Record<string, CSSProperties>>(
    (styles, square) => {
      styles[square] = {
        boxShadow: `inset 0 0 0 4px ${palette.highlightRing}`,
        backgroundColor: palette.highlightBackground,
      };
      return styles;
    },
    {},
  );
  if (solutionMove) {
    squareStyles[solutionMove.to] = {
      ...squareStyles[solutionMove.to],
      background:
        `radial-gradient(circle at 68% 28%, ${palette.solutionFill} 0 34%, transparent 35%), ` +
        palette.solutionFill,
      boxShadow: [
        squareStyles[solutionMove.to]?.boxShadow,
        `inset 0 0 0 5px ${palette.solutionRing}`,
        "inset 0 0 24px rgba(255, 244, 177, 0.38)",
      ]
        .filter(Boolean)
        .join(", "),
    };
  }

  const squareRenderer = ({
    square,
    children,
  }: {
    square: string;
    children?: ReactNode;
  }) => (
    <div className="board-square-content" style={squareStyles[square]}>
      {children}
      {solutionMove?.to === square ? (
        <span className="board-square-solution-badge" aria-label="Best move">
          !
        </span>
      ) : null}
    </div>
  );

  return (
    <div
      className={
        variant === "critical"
          ? "board-frame board-frame-critical"
          : "board-frame"
      }
      role="img"
      aria-label={`Board position for ${eventName}`}
    >
      <Chessboard
        options={{
          id: boardId ?? `featured-position-${positionId}`,
          position: fen,
          allowDragging: false,
          allowDrawingArrows: false,
          arrows: solutionMove
            ? [
                {
                  startSquare: solutionMove.from,
                  endSquare: solutionMove.to,
                  color: palette.solutionArrow,
                },
              ]
            : [],
          arrowOptions: {
            color: palette.solutionArrow,
            secondaryColor: palette.solutionArrow,
            tertiaryColor: palette.solutionArrow,
            arrowLengthReducerDenominator: 6,
            sameTargetArrowLengthReducerDenominator: 4,
            arrowWidthDenominator: 7,
            activeArrowWidthMultiplier: 1,
            opacity: 0.88,
            activeOpacity: 0.88,
            arrowStartOffset: 0.18,
          },
          squareRenderer,
          showAnimations: false,
          squareStyles,
          darkSquareStyle: { backgroundColor: palette.darkSquare },
          lightSquareStyle: { backgroundColor: palette.lightSquare },
          darkSquareNotationStyle: { color: palette.notationOnDark },
          lightSquareNotationStyle: { color: palette.notationOnLight },
        }}
      />
    </div>
  );
}
