import React from "react";
import { AbsoluteFill } from "remotion";
import { Brain, Database, Workflow, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { TitleBlock } from "./ChapterVideo";
import { IconBadge, MarkerHighlight, ThickArrow } from "./DiagramPrimitives";

/**
 * POC 1 (v2) — même logique hub-and-spoke que ArchitectureDiagram.tsx (validée), mais avec le
 * traitement visuel "mix" tranché après retours : icônes pleines dans un badge de couleur pleine
 * (pas un simple contour), labels en surlignage façon marqueur (pas du texte coloré sur fond uni),
 * connecteurs nettement plus épais. Contenu toujours fidèle au lesson_script (LLM/outils/mémoire
 * coordonnés par l'orchestrateur), toujours codé en dur pour ce test de style ponctuel.
 */

type Node = {
  id: string;
  label: string;
  icon: LucideIcon;
  color: string;
  centerX: number;
  centerY: number;
  badgeSize: number;
  entranceFrame: number;
};

const HUB: Node = {
  id: "orchestrateur",
  label: "Orchestrateur",
  icon: Workflow,
  color: "#fb923c",
  centerX: 960,
  centerY: 640,
  badgeSize: 130,
  entranceFrame: 15,
};

const SATELLITES: Node[] = [
  { id: "llm", label: "LLM", icon: Brain, color: "#60a5fa", centerX: 960, centerY: 230, badgeSize: 96, entranceFrame: 35 },
  { id: "outils", label: "Outils", icon: Wrench, color: "#4ade80", centerX: 1540, centerY: 640, badgeSize: 96, entranceFrame: 55 },
  { id: "memoire", label: "Mémoire", icon: Database, color: "#c084fc", centerX: 380, centerY: 640, badgeSize: 96, entranceFrame: 75 },
];

const ARROW_GAP = 24;

const DiagramNode: React.FC<{ node: Node }> = ({ node }) => (
  <div
    style={{
      position: "absolute",
      left: node.centerX - 160,
      top: node.centerY - node.badgeSize / 2,
      width: 320,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      // Écart généreux entre le badge et le label : laisse la place à la flèche (et sa pointe)
      // de se terminer avant que le label ne commence — sinon le label (peint après, donc
      // par-dessus) masque la pointe de flèche côté LLM. Bug réel trouvé en vérifiant le rendu.
      gap: 56,
    }}
  >
    <IconBadge Icon={node.icon} color={node.color} size={node.badgeSize} entranceFrame={node.entranceFrame} />
    <MarkerHighlight text={node.label} color={node.color} entranceFrame={node.entranceFrame + 5} />
  </div>
);

const connectorPoints = (from: Node, to: Node) => {
  const isVertical = from.centerX === to.centerX;
  if (isVertical) {
    const top = Math.min(from.centerY, to.centerY);
    const bottom = Math.max(from.centerY, to.centerY);
    const topNode = from.centerY < to.centerY ? from : to;
    const bottomNode = from.centerY < to.centerY ? to : from;
    return {
      x1: from.centerX,
      y1: top + topNode.badgeSize / 2 + ARROW_GAP,
      x2: from.centerX,
      y2: bottom - bottomNode.badgeSize / 2 - ARROW_GAP,
    };
  }
  const left = Math.min(from.centerX, to.centerX);
  const right = Math.max(from.centerX, to.centerX);
  const leftNode = from.centerX < to.centerX ? from : to;
  const rightNode = from.centerX < to.centerX ? to : from;
  return {
    x1: left + leftNode.badgeSize / 2 + ARROW_GAP,
    y1: from.centerY,
    x2: right - rightNode.badgeSize / 2 - ARROW_GAP,
    y2: from.centerY,
  };
};

export const ArchitectureDiagramV2POC: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", color: "white", fontFamily: "Arial, sans-serif", padding: 80 }}>
      <div style={{ fontSize: 28, opacity: 0.7 }}>Chapitre 1 — Pourquoi les agents IA échouent en production</div>
      <TitleBlock title="L'architecture en quatre composants clés" />

      {SATELLITES.map((sat) => {
        const pts = connectorPoints(HUB, sat);
        return (
          <ThickArrow
            key={sat.id}
            id={sat.id}
            x1={pts.x1}
            y1={pts.y1}
            x2={pts.x2}
            y2={pts.y2}
            bidirectional
            entranceFrame={sat.entranceFrame}
          />
        );
      })}

      <DiagramNode node={HUB} />
      {SATELLITES.map((sat) => (
        <DiagramNode key={sat.id} node={sat} />
      ))}
    </AbsoluteFill>
  );
};
