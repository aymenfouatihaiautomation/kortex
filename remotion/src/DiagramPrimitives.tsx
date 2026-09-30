import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import type { LucideIcon } from "lucide-react";
import { useEntranceStyle } from "./ChapterVideo";

/**
 * Briques visuelles partagées pour la direction "mix" validée après 2 tours de retours :
 * icônes pleines et colorées (badge de couleur pleine, pas juste un contour fin), surlignage
 * façon marqueur derrière les termes/chiffres clés, connecteurs épais et visuellement présents.
 * Réutilisées par les diagrammes (architecture hub-and-spoke, flux numéroté) — pas encore
 * généralisées aux diapositives "normales" (chips/numbers de ChapterVideo), ce sera décidé une
 * fois ce style validé sur les POC.
 */

export const IconBadge: React.FC<{
  Icon: LucideIcon;
  color: string;
  size?: number;
  entranceFrame?: number;
}> = ({ Icon, color, size = 84, entranceFrame = 0 }) => {
  const entrance = useEntranceStyle(entranceFrame);
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        backgroundColor: color,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: `0 8px 24px ${color}66`,
        ...entrance,
      }}
    >
      <Icon size={size * 0.52} color="#0f172a" strokeWidth={2.5} />
    </div>
  );
};

export const MarkerHighlight: React.FC<{
  text: string;
  color: string;
  textColor?: string;
  fontSize?: number;
  rotate?: number;
  entranceFrame?: number;
}> = ({ text, color, textColor = "#0f172a", fontSize = 34, rotate = -1, entranceFrame = 0 }) => {
  const entrance = useEntranceStyle(entranceFrame);
  return (
    <div
      style={{
        display: "inline-block",
        backgroundColor: color,
        color: textColor,
        fontWeight: 800,
        fontSize,
        padding: "10px 24px",
        borderRadius: "6px 18px 6px 18px",
        transform: `rotate(${rotate}deg)`,
        ...entrance,
      }}
    >
      {text}
    </div>
  );
};

/** Flèche épaisse (relation réelle, pas décorative) entre deux points d'un canvas 1920x1080,
 * avec pointe(s) de flèche, fondu synchronisé sur `entranceFrame`. */
export const ThickArrow: React.FC<{
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color?: string;
  strokeWidth?: number;
  bidirectional?: boolean;
  entranceFrame: number;
}> = ({ id, x1, y1, x2, y2, color = "#cbd5e1", strokeWidth = 10, bidirectional = false, entranceFrame }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame - entranceFrame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const markerId = `arrow-${id}`;

  return (
    <svg style={{ position: "absolute", left: 0, top: 0, opacity }} width={1920} height={1080}>
      <defs>
        {/* markerUnits="userSpaceOnUse" : sans ça, la taille du marqueur se multiplie par
            strokeWidth (comportement par défaut de SVG), ce qui le rend démesuré pour un trait
            épais — bug réel rencontré au premier rendu de ce composant. */}
        <marker id={markerId} markerUnits="userSpaceOnUse" markerWidth="32" markerHeight="32" refX="24" refY="16" orient="auto">
          <path d="M0,0 L32,16 L0,32 Z" fill={color} />
        </marker>
        {bidirectional && (
          <marker id={`${markerId}-start`} markerUnits="userSpaceOnUse" markerWidth="32" markerHeight="32" refX="8" refY="16" orient="auto">
            <path d="M32,0 L0,16 L32,32 Z" fill={color} />
          </marker>
        )}
      </defs>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        markerEnd={`url(#${markerId})`}
        markerStart={bidirectional ? `url(#${markerId}-start)` : undefined}
      />
    </svg>
  );
};
