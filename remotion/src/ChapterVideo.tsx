import React from "react";
import { z } from "zod";
import { AbsoluteFill, Audio, interpolate, staticFile, useCurrentFrame } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";

// Durée (en frames) de la transition en fondu entre deux diapositives, et de l'animation
// d'entrée de chaque élément visuel — sobre et courte, kinetic typography discrète.
// Exportées pour être réutilisées par d'autres compositions (ex. ChapterVideoPreview).
export const TRANSITION_FRAMES = 15;
export const ENTRANCE_FRAMES = 15;

export const timedElementSchema = z.object({
  text: z.string(),
  startFrame: z.number(),
});

export const slideSchema = z.object({
  slideNumber: z.number(),
  visualTitle: z.string(),
  keyTerms: z.array(timedElementSchema),
  keyNumbers: z.array(timedElementSchema),
  audioFile: z.string(),
  durationInFrames: z.number(),
});

export const chapterVideoSchema = z.object({
  chapterNumber: z.number(),
  chapterTitle: z.string(),
  slides: z.array(slideSchema),
});

type Props = z.infer<typeof chapterVideoSchema>;
type Slide = z.infer<typeof slideSchema>;
export type TimedElement = z.infer<typeof timedElementSchema>;

export const calculateChapterMetadata: CalculateMetadataFunction<Props> = ({
  props,
}) => {
  const sumSlides = props.slides.reduce((sum, s) => sum + s.durationInFrames, 0);
  const numTransitions = Math.max(props.slides.length - 1, 0);
  const total = sumSlides - numTransitions * TRANSITION_FRAMES;
  return { durationInFrames: Math.max(total, 1) };
};

/** Fondu + léger glissement vers le haut, démarrant à `startFrame` (frame locale de la
 * diapositive). Avant `startFrame`, l'élément est invisible (clamp) ; l'entrée dure
 * `ENTRANCE_FRAMES`, puis l'élément reste stable jusqu'à la fin de la diapositive. */
export const useEntranceStyle = (startFrame: number): React.CSSProperties => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame - startFrame, [0, ENTRANCE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(progress, [0, 1], [18, 0]);
  return { opacity: progress, transform: `translateY(${translateY}px)` };
};

export const TitleBlock: React.FC<{ title: string }> = ({ title }) => (
  <div
    style={{
      fontSize: 60,
      fontWeight: 700,
      marginTop: 40,
      marginBottom: 60,
      lineHeight: 1.2,
      ...useEntranceStyle(0),
    }}
  >
    {title}
  </div>
);

export const TermChip: React.FC<{ term: TimedElement }> = ({ term }) => (
  <div
    style={{
      fontSize: 34,
      backgroundColor: "#1e293b",
      padding: "16px 28px",
      borderRadius: 12,
      border: "2px solid #38bdf8",
      ...useEntranceStyle(term.startFrame),
    }}
  >
    {term.text}
  </div>
);

export const NumberBlock: React.FC<{ number: TimedElement }> = ({ number }) => (
  <div style={{ fontSize: 46, fontWeight: 700, color: "#facc15", ...useEntranceStyle(number.startFrame) }}>
    {number.text}
  </div>
);

/** Contenu visuel d'une diapositive (titre, chips de termes, chiffres) SANS l'audio — réutilisé
 * tel quel par ChapterVideoPreview, qui gère son propre timeline audio séparément. */
export const SlideVisual: React.FC<{
  slideNumber: number;
  visualTitle: string;
  keyTerms: TimedElement[];
  keyNumbers: TimedElement[];
  chapterNumber: number;
  chapterTitle: string;
}> = ({ slideNumber, visualTitle, keyTerms, keyNumbers, chapterNumber, chapterTitle }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0f172a",
        color: "white",
        fontFamily: "Arial, sans-serif",
        padding: 80,
      }}
    >
      <div style={{ fontSize: 28, opacity: 0.7 }}>
        Chapitre {chapterNumber} — {chapterTitle}
      </div>
      <TitleBlock title={visualTitle} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        {keyTerms.map((term, i) => (
          <TermChip key={i} term={term} />
        ))}
      </div>
      {keyNumbers.length > 0 && (
        <div style={{ display: "flex", gap: 24, marginTop: 50, flexWrap: "wrap" }}>
          {keyNumbers.map((num, i) => (
            <NumberBlock key={i} number={num} />
          ))}
        </div>
      )}
      <div style={{ position: "absolute", bottom: 40, right: 60, fontSize: 22, opacity: 0.5 }}>
        Diapositive {slideNumber}
      </div>
    </AbsoluteFill>
  );
};

const Slide: React.FC<{
  slide: Slide;
  chapterNumber: number;
  chapterTitle: string;
}> = ({ slide, chapterNumber, chapterTitle }) => {
  return (
    <>
      <Audio src={staticFile(slide.audioFile)} />
      <SlideVisual
        slideNumber={slide.slideNumber}
        visualTitle={slide.visualTitle}
        keyTerms={slide.keyTerms}
        keyNumbers={slide.keyNumbers}
        chapterNumber={chapterNumber}
        chapterTitle={chapterTitle}
      />
    </>
  );
};

export const ChapterVideo: React.FC<Props> = ({ chapterNumber, chapterTitle, slides }) => {
  return (
    <TransitionSeries>
      {slides.flatMap((slide, i) => {
        const items = [
          <TransitionSeries.Sequence key={`slide-${slide.slideNumber}`} durationInFrames={slide.durationInFrames}>
            <Slide slide={slide} chapterNumber={chapterNumber} chapterTitle={chapterTitle} />
          </TransitionSeries.Sequence>,
        ];
        if (i < slides.length - 1) {
          items.push(
            <TransitionSeries.Transition
              key={`transition-${slide.slideNumber}`}
              presentation={fade()}
              timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
            />
          );
        }
        return items;
      })}
    </TransitionSeries>
  );
};
