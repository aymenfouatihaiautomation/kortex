import React from "react";
import { AbsoluteFill } from "remotion";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  Brain,
  Bug,
  CheckCircle,
  Clock,
  Cloud,
  Cpu,
  Database,
  DollarSign,
  Eye,
  FileText,
  FlaskConical,
  Gauge,
  GitBranch,
  Layers,
  Lock,
  MessageSquare,
  RefreshCw,
  Server,
  Settings,
  Shield,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Workflow,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { TitleBlock, useEntranceStyle } from "./ChapterVideo";
import type { TimedElement } from "./ChapterVideo";
import { IconBadge, MarkerHighlight, ThickArrow } from "./DiagramPrimitives";

/**
 * Généralisation du style visuel "mix" (validé sur les POC architecture_diagram_v2 +
 * timeline_diagram) à un chapitre ENTIER : chaque diapositive reçoit un traitement adapté à son
 * contenu réel (diagram / timeline / default enrichi), piloté par des données produites par le LLM
 * (bloc3_video_production/slides.py::build_rich_slides), pas du contenu codé en dur comme les POC
 * initiaux. Voir DIAGRAM_ICONS (slides.py) — cette table doit rester synchronisée avec cette liste.
 */

export const ICONS: Record<string, LucideIcon> = {
  Brain, Wrench, Database, Workflow, Bug, AlertTriangle, CheckCircle, XCircle,
  Clock, DollarSign, TrendingUp, TrendingDown, Shield, Server, Cloud, Cpu,
  FlaskConical, Gauge, RefreshCw, Zap, MessageSquare, Users, FileText, Settings,
  Activity, Target, Layers, GitBranch, Lock, Eye,
};

const RICH_PALETTE = ["#60a5fa", "#4ade80", "#c084fc", "#fb923c", "#f87171", "#facc15"];

const resolveIcon = (name: string): LucideIcon => ICONS[name] ?? Activity;

export type DiagramNodeData = { label: string; icon: string };
export type TimelineStepData = { label: string; icon: string; number: string };

const ChapterHeader: React.FC<{ chapterNumber: number; chapterTitle: string }> = ({
  chapterNumber,
  chapterTitle,
}) => (
  <div style={{ fontSize: 28, opacity: 0.7 }}>
    Chapitre {chapterNumber} — {chapterTitle}
  </div>
);

const SlideFooter: React.FC<{ slideNumber: number }> = ({ slideNumber }) => (
  <div style={{ position: "absolute", bottom: 40, right: 60, fontSize: 22, opacity: 0.5 }}>
    Diapositive {slideNumber}
  </div>
);

/** Style "default" enrichi : termes en surlignage marqueur (au lieu de simples chips), chiffres
 * avec un badge d'icône + surlignage — même langage visuel que les diagrammes, pour que les
 * diapositives "normales" ne retombent pas en simple texte animé. */
export const SlideVisualRich: React.FC<{
  slideNumber: number;
  visualTitle: string;
  keyTerms: TimedElement[];
  keyNumbers: TimedElement[];
  chapterNumber: number;
  chapterTitle: string;
}> = ({ slideNumber, visualTitle, keyTerms, keyNumbers, chapterNumber, chapterTitle }) => (
  <AbsoluteFill style={{ backgroundColor: "#0f172a", color: "white", fontFamily: "Arial, sans-serif", padding: 80 }}>
    <ChapterHeader chapterNumber={chapterNumber} chapterTitle={chapterTitle} />
    <TitleBlock title={visualTitle} />
    <div style={{ display: "flex", flexWrap: "wrap", gap: 24 }}>
      {keyTerms.map((term, i) => (
        <MarkerHighlight
          key={i}
          text={term.text}
          color={RICH_PALETTE[i % RICH_PALETTE.length]}
          entranceFrame={term.startFrame}
        />
      ))}
    </div>
    {keyNumbers.length > 0 && (
      <div style={{ display: "flex", gap: 40, marginTop: 56, flexWrap: "wrap" }}>
        {keyNumbers.map((num, i) => {
          const color = RICH_PALETTE[(i + 2) % RICH_PALETTE.length];
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <IconBadge Icon={TrendingUp} color={color} size={64} entranceFrame={num.startFrame} />
              <MarkerHighlight text={num.text} color={color} fontSize={40} entranceFrame={num.startFrame + 5} />
            </div>
          );
        })}
      </div>
    )}
    <SlideFooter slideNumber={slideNumber} />
  </AbsoluteFill>
);

/** Diagramme hub-and-spoke générique (2 à 4 satellites disposés en cercle autour du hub) —
 * généralise ArchitectureDiagramV2 (qui avait 3 satellites codés en dur) à un contenu variable. */
export const DiagramSlideVisual: React.FC<{
  slideNumber: number;
  visualTitle: string;
  chapterNumber: number;
  chapterTitle: string;
  hub: DiagramNodeData;
  satellites: DiagramNodeData[];
}> = ({ slideNumber, visualTitle, chapterNumber, chapterTitle, hub, satellites }) => {
  const HUB_CENTER = { x: 960, y: 640 };
  // Disposition ELLIPTIQUE (pas un cercle parfait) : un rayon vertical circulaire (ex. 420)
  // place le satellite du haut à y=220, qui chevauche la zone du titre (le titre occupe environ
  // les 290 premiers pixels) — bug réel trouvé en vérifiant le rendu du premier chapitre entier.
  // Un rayon vertical réduit (220) borne l'excursion en Y à [420, 860] quel que soit l'angle,
  // ce qui reste toujours en dehors de la zone du titre ET de la marge basse, pour 2 à 4
  // satellites (contrairement à un rayon circulaire, dont le pire cas dépend fortement de N).
  // RADIUS_X élargi (560, pas 480) : le label du hub est maintenant affiché à sa droite (voir
  // plus bas) — un rayon trop court faisait chevaucher ce label avec le satellite de droite,
  // bug réel trouvé en vérifiant le rendu.
  const RADIUS_X = 560;
  const RADIUS_Y = 220;
  const HUB_BADGE = 130;
  const SAT_BADGE = 96;
  const ARROW_GAP = 24;

  const positioned = satellites.map((sat, i) => {
    const angleDeg = -90 + (360 / satellites.length) * i;
    const angleRad = (angleDeg * Math.PI) / 180;
    return {
      ...sat,
      centerX: HUB_CENTER.x + RADIUS_X * Math.cos(angleRad),
      centerY: HUB_CENTER.y + RADIUS_Y * Math.sin(angleRad),
      badgeSize: SAT_BADGE,
      entranceFrame: 35 + i * 22,
    };
  });

  const connectorPoints = (satX: number, satY: number) => {
    const dx = satX - HUB_CENTER.x;
    const dy = satY - HUB_CENTER.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const ux = dx / dist;
    const uy = dy / dist;
    return {
      x1: HUB_CENTER.x + ux * (HUB_BADGE / 2 + ARROW_GAP),
      y1: HUB_CENTER.y + uy * (HUB_BADGE / 2 + ARROW_GAP),
      x2: satX - ux * (SAT_BADGE / 2 + ARROW_GAP),
      y2: satY - uy * (SAT_BADGE / 2 + ARROW_GAP),
    };
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", color: "white", fontFamily: "Arial, sans-serif", padding: 80 }}>
      <ChapterHeader chapterNumber={chapterNumber} chapterTitle={chapterTitle} />
      <TitleBlock title={visualTitle} />

      {positioned.map((sat, i) => {
        const pts = connectorPoints(sat.centerX, sat.centerY);
        return (
          <ThickArrow
            key={`arrow-${i}`}
            id={`diagram-${slideNumber}-${i}`}
            x1={pts.x1}
            y1={pts.y1}
            x2={pts.x2}
            y2={pts.y2}
            bidirectional
            entranceFrame={sat.entranceFrame}
          />
        );
      })}

      {/* Label du hub placé À CÔTÉ du badge (pas en dessous) : avec des satellites tout autour
          (y compris en bas), un label sous le hub empiéterait sur le satellite du bas — bug réel
          trouvé en vérifiant le rendu (le badge "Précision" recouvrait le texte "Semaine en
          prod"). Le badge reste centré EXACTEMENT sur HUB_CENTER (les flèches sont calculées par
          rapport à ce point), seul le label est décalé. */}
      <div
        style={{
          position: "absolute",
          left: HUB_CENTER.x - HUB_BADGE / 2,
          top: HUB_CENTER.y - HUB_BADGE / 2,
        }}
      >
        <IconBadge Icon={resolveIcon(hub.icon)} color="#fb923c" size={HUB_BADGE} entranceFrame={15} />
      </div>
      <div
        style={{
          position: "absolute",
          left: HUB_CENTER.x + HUB_BADGE / 2 + 24,
          top: HUB_CENTER.y,
          transform: "translateY(-50%)",
        }}
      >
        <MarkerHighlight text={hub.label} color="#fb923c" entranceFrame={20} />
      </div>

      {positioned.map((sat, i) => (
        <div
          key={`node-${i}`}
          style={{
            position: "absolute",
            left: sat.centerX - 160,
            top: sat.centerY - sat.badgeSize / 2,
            width: 320,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 56,
          }}
        >
          <IconBadge
            Icon={resolveIcon(sat.icon)}
            color={RICH_PALETTE[i % RICH_PALETTE.length]}
            size={sat.badgeSize}
            entranceFrame={sat.entranceFrame}
          />
          <MarkerHighlight
            text={sat.label}
            color={RICH_PALETTE[i % RICH_PALETTE.length]}
            entranceFrame={sat.entranceFrame + 5}
          />
        </div>
      ))}

      <SlideFooter slideNumber={slideNumber} />
    </AbsoluteFill>
  );
};

/** Flux numéroté générique (3 à 5 étapes réparties horizontalement) — généralise TimelineDiagram
 * (4 étapes codées en dur) à un contenu variable. */
export const TimelineSlideVisual: React.FC<{
  slideNumber: number;
  visualTitle: string;
  chapterNumber: number;
  chapterTitle: string;
  steps: TimelineStepData[];
}> = ({ slideNumber, visualTitle, chapterNumber, chapterTitle, steps }) => {
  const CENTER_Y = 600;
  const BADGE_SIZE = 100;
  const MARGIN = 260;
  const ARROW_GAP = 24;
  const usableWidth = 1920 - 2 * MARGIN;

  const positioned = steps.map((step, i) => ({
    ...step,
    centerX: steps.length === 1 ? 960 : MARGIN + (usableWidth * i) / (steps.length - 1),
    entranceFrame: 20 + i * 26,
  }));

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", color: "white", fontFamily: "Arial, sans-serif", padding: 80 }}>
      <ChapterHeader chapterNumber={chapterNumber} chapterTitle={chapterTitle} />
      <TitleBlock title={visualTitle} />

      {positioned.slice(1).map((step, i) => {
        const prev = positioned[i];
        return (
          <ThickArrow
            key={`arrow-${i}`}
            id={`timeline-${slideNumber}-${i}`}
            x1={prev.centerX + BADGE_SIZE / 2 + ARROW_GAP}
            y1={CENTER_Y}
            x2={step.centerX - BADGE_SIZE / 2 - ARROW_GAP}
            y2={CENTER_Y}
            entranceFrame={step.entranceFrame}
          />
        );
      })}

      {positioned.map((step, i) => {
        const color = RICH_PALETTE[i % RICH_PALETTE.length];
        const numberEntrance = useEntranceStyle(step.entranceFrame);
        const labelEntrance = useEntranceStyle(step.entranceFrame + 12);
        return (
          <div
            key={`step-${i}`}
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
              <IconBadge Icon={resolveIcon(step.icon)} color={color} size={BADGE_SIZE} entranceFrame={step.entranceFrame} />
              <div
                style={{
                  position: "absolute",
                  top: -10,
                  right: -10,
                  width: 48,
                  height: 48,
                  borderRadius: "50%",
                  backgroundColor: "#0f172a",
                  border: `3px solid ${color}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 24,
                  fontWeight: 800,
                  color: "white",
                  ...numberEntrance,
                }}
              >
                {i + 1}
              </div>
            </div>
            {step.number && (
              <MarkerHighlight text={step.number} color={color} entranceFrame={step.entranceFrame + 8} fontSize={36} />
            )}
            <div style={{ fontSize: 24, opacity: 0.85, textAlign: "center", ...labelEntrance }}>{step.label}</div>
          </div>
        );
      })}

      <SlideFooter slideNumber={slideNumber} />
    </AbsoluteFill>
  );
};
