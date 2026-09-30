import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Brain, Database, Workflow, Wrench } from "lucide-react";
import { TitleBlock, useEntranceStyle } from "./ChapterVideo";

/**
 * Preuve de concept — UNE diapositive isolée du chapitre 1 ("L'architecture en quatre composants
 * clés") redessinée en vrai diagramme (boîtes + flèches + icônes + code couleur) plutôt qu'en
 * chips de texte. Contenu (titre, 4 composants, leurs relations) délibérément codé en dur : c'est
 * un test de style ponctuel, pas encore une diapositive générique paramétrable — le schéma de
 * données générique viendra une fois ce style validé, pour les autres types de diapositives
 * (timeline, mise en valeur de chiffres, etc.) décidés avec l'utilisateur.
 *
 * Contenu fidèle au lesson_script du chapitre 1 (non modifié) : "Le LLM raisonne... les outils
 * permettent à l'agent d'agir... l'orchestrateur enchaîne ces étapes... la mémoire...conserve le
 * contexte" — l'orchestrateur est donc le hub central, LLM/outils/mémoire les 3 satellites.
 */

const CANVAS_WIDTH = 1920;
const CANVAS_HEIGHT = 1080;

type NodeSpec = {
  id: string;
  label: string;
  icon: React.ComponentType<{ size?: number; color?: string }>;
  color: string;
  backgroundTint: string;
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  entranceFrame: number;
};

const HUB: NodeSpec = {
  id: "orchestrateur",
  label: "Orchestrateur",
  icon: Workflow,
  color: "#f97316",
  backgroundTint: "rgba(249, 115, 22, 0.14)",
  centerX: 960,
  centerY: 660,
  width: 320,
  height: 150,
  entranceFrame: 15,
};

const SATELLITES: NodeSpec[] = [
  {
    id: "llm",
    label: "LLM",
    icon: Brain,
    color: "#3b82f6",
    backgroundTint: "rgba(59, 130, 246, 0.14)",
    centerX: 960,
    centerY: 360,
    width: 260,
    height: 120,
    entranceFrame: 35,
  },
  {
    id: "outils",
    label: "Outils",
    icon: Wrench,
    color: "#22c55e",
    backgroundTint: "rgba(34, 197, 94, 0.14)",
    centerX: 1500,
    centerY: 660,
    width: 260,
    height: 120,
    entranceFrame: 55,
  },
  {
    id: "memoire",
    label: "Mémoire",
    icon: Database,
    color: "#a855f7",
    backgroundTint: "rgba(168, 85, 247, 0.14)",
    centerX: 420,
    centerY: 660,
    width: 260,
    height: 120,
    entranceFrame: 75,
  },
];

const NodeBox: React.FC<{ node: NodeSpec; isHub?: boolean }> = ({ node, isHub }) => {
  const Icon = node.icon;
  const style = useEntranceStyle(node.entranceFrame);
  return (
    <div
      style={{
        position: "absolute",
        left: node.centerX - node.width / 2,
        top: node.centerY - node.height / 2,
        width: node.width,
        height: node.height,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        borderRadius: 16,
        border: `2px solid ${node.color}`,
        backgroundColor: node.backgroundTint,
        boxShadow: isHub ? `0 0 40px ${node.color}33` : "none",
        ...style,
      }}
    >
      <Icon size={isHub ? 44 : 36} color={node.color} />
      <div style={{ fontSize: isHub ? 30 : 26, fontWeight: 700, color: "white" }}>{node.label}</div>
    </div>
  );
};

const Arrow: React.FC<{ from: NodeSpec; to: NodeSpec; entranceFrame: number }> = ({
  from,
  to,
  entranceFrame,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame - entranceFrame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Ligne droite entre les bords (pas les centres) des deux boîtes, verticale ou horizontale.
  const isVertical = from.centerX === to.centerX;
  const gap = 14;
  let x1: number, y1: number, x2: number, y2: number;
  if (isVertical) {
    const top = Math.min(from.centerY, to.centerY);
    const bottom = Math.max(from.centerY, to.centerY);
    const topNode = from.centerY < to.centerY ? from : to;
    const bottomNode = from.centerY < to.centerY ? to : from;
    x1 = x2 = from.centerX;
    y1 = top + topNode.height / 2 + gap;
    y2 = bottom - bottomNode.height / 2 - gap;
  } else {
    const left = Math.min(from.centerX, to.centerX);
    const right = Math.max(from.centerX, to.centerX);
    const leftNode = from.centerX < to.centerX ? from : to;
    const rightNode = from.centerX < to.centerX ? to : from;
    y1 = y2 = from.centerY;
    x1 = left + leftNode.width / 2 + gap;
    x2 = right - rightNode.width / 2 - gap;
  }

  const markerId = `arrowhead-${from.id}-${to.id}`;

  return (
    <svg
      style={{ position: "absolute", left: 0, top: 0, opacity }}
      width={CANVAS_WIDTH}
      height={CANVAS_HEIGHT}
    >
      <defs>
        <marker id={markerId} markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
          <path d="M0,0 L10,5 L0,10 Z" fill="#94a3b8" />
        </marker>
        <marker id={`${markerId}-start`} markerWidth="10" markerHeight="10" refX="2" refY="5" orient="auto">
          <path d="M10,0 L0,5 L10,10 Z" fill="#94a3b8" />
        </marker>
      </defs>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke="#94a3b8"
        strokeWidth={3}
        markerEnd={`url(#${markerId})`}
        markerStart={`url(#${markerId}-start)`}
      />
    </svg>
  );
};

export const ArchitectureDiagramPOC: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0f172a",
        color: "white",
        fontFamily: "Arial, sans-serif",
        padding: 80,
      }}
    >
      <div style={{ fontSize: 28, opacity: 0.7, color: "white" }}>
        Chapitre 1 — Pourquoi les agents IA échouent en production
      </div>
      <TitleBlock title="L'architecture en quatre composants clés" />

      {SATELLITES.map((sat) => (
        <Arrow key={sat.id} from={HUB} to={sat} entranceFrame={sat.entranceFrame} />
      ))}

      <NodeBox node={HUB} isHub />
      {SATELLITES.map((sat) => (
        <NodeBox key={sat.id} node={sat} />
      ))}
    </AbsoluteFill>
  );
};
