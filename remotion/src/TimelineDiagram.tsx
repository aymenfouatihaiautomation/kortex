import React from "react";
import { AbsoluteFill } from "remotion";
import { DollarSign, FlaskConical, TrendingDown, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { TitleBlock, useEntranceStyle } from "./ChapterVideo";
import { IconBadge, MarkerHighlight, ThickArrow } from "./DiagramPrimitives";

/**
 * POC 2 — diapositive "Une semaine en production : la chute" en flux numéroté (1→2→3→4), même
 * traitement visuel "mix" que ArchitectureDiagramV2 (icônes pleines colorées, surlignage façon
 * marqueur, connecteurs épais), PAS le style croquis en traits noirs. Chiffres et faits repris
 * verbatim du lesson_script validé du chapitre 1 (paragraphe "Prenons un exemple illustratif
 * typique...") : 10 requêtes en démo -> ~4 000 tickets/jour -> 82% de précision -> facture x5.
 * Contenu codé en dur, test de style ponctuel comme le POC 1.
 */

type Step = {
  number: number;
  label: string;
  stat: string;
  icon: LucideIcon;
  color: string;
  centerX: number;
  entranceFrame: number;
};

const CENTER_Y = 600;
const BADGE_SIZE = 100;
const ARROW_GAP = 24;

const STEPS: Step[] = [
  { number: 1, label: "Test en démo", stat: "10 requêtes", icon: FlaskConical, color: "#60a5fa", centerX: 260, entranceFrame: 20 },
  { number: 2, label: "Mise en production", stat: "~4 000 / jour", icon: TrendingUp, color: "#fb923c", centerX: 740, entranceFrame: 50 },
  { number: 3, label: "Précision en chute", stat: "82 %", icon: TrendingDown, color: "#f87171", centerX: 1220, entranceFrame: 80 },
  { number: 4, label: "Dérive des coûts", stat: "× 5", icon: DollarSign, color: "#c084fc", centerX: 1700, entranceFrame: 110 },
];

const StepNode: React.FC<{ step: Step }> = ({ step }) => {
  const numberEntrance = useEntranceStyle(step.entranceFrame);
  const labelEntrance = useEntranceStyle(step.entranceFrame + 12);

  return (
    <div
      style={{
        position: "absolute",
        left: step.centerX - 170,
        top: CENTER_Y - BADGE_SIZE / 2,
        width: 340,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 18,
      }}
    >
      <div style={{ position: "relative" }}>
        <IconBadge Icon={step.icon} color={step.color} size={BADGE_SIZE} entranceFrame={step.entranceFrame} />
        <div
          style={{
            position: "absolute",
            top: -10,
            right: -10,
            width: 48,
            height: 48,
            borderRadius: "50%",
            backgroundColor: "#0f172a",
            border: `3px solid ${step.color}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 24,
            fontWeight: 800,
            color: "white",
            ...numberEntrance,
          }}
        >
          {step.number}
        </div>
      </div>
      <MarkerHighlight text={step.stat} color={step.color} entranceFrame={step.entranceFrame + 8} fontSize={36} />
      <div style={{ fontSize: 24, opacity: 0.85, textAlign: "center", ...labelEntrance }}>{step.label}</div>
    </div>
  );
};

export const TimelineDiagramPOC: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", color: "white", fontFamily: "Arial, sans-serif", padding: 80 }}>
      <div style={{ fontSize: 28, opacity: 0.7 }}>Chapitre 1 — Pourquoi les agents IA échouent en production</div>
      <TitleBlock title="Une semaine en production : la chute" />

      {STEPS.slice(1).map((step, i) => {
        const prev = STEPS[i];
        return (
          <ThickArrow
            key={step.number}
            id={`step-${step.number}`}
            x1={prev.centerX + BADGE_SIZE / 2 + ARROW_GAP}
            y1={CENTER_Y}
            x2={step.centerX - BADGE_SIZE / 2 - ARROW_GAP}
            y2={CENTER_Y}
            entranceFrame={step.entranceFrame}
          />
        );
      })}

      {STEPS.map((step) => (
        <StepNode key={step.number} step={step} />
      ))}
    </AbsoluteFill>
  );
};
