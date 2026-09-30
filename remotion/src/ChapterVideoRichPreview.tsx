import React from "react";
import { z } from "zod";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { TRANSITION_FRAMES, timedElementSchema } from "./ChapterVideo";
import { SlideVisualRich, DiagramSlideVisual, TimelineSlideVisual } from "./RichSlideVisuals";

/**
 * Pilote de style visuel riche : réutilise un audio déjà généré (payé, pas de nouvel appel
 * ElevenLabs) — même principe que ChapterVideoPreview (audio et visuel = deux timelines
 * indépendantes de même durée totale, timing visuel APPROXIMATIF, pas de synchro exacte parole/
 * visuel). Ce qui change ici : chaque diapositive reçoit un traitement visuel adapté à son
 * contenu réel (diagram/timeline/default enrichi), pas seulement le style "chips" de base.
 */

const audioSegmentSchema = z.object({
  file: z.string(),
  durationInFrames: z.number(),
});

const diagramNodeSchema = z.object({
  label: z.string(),
  icon: z.string(),
});

const timelineStepSchema = z.object({
  label: z.string(),
  icon: z.string(),
  number: z.string(),
});

const richVisualSlideSchema = z.object({
  slideNumber: z.number(),
  visualTitle: z.string(),
  visualType: z.enum(["default", "diagram", "timeline"]),
  durationInFrames: z.number(),
  keyTerms: z.array(timedElementSchema).optional(),
  keyNumbers: z.array(timedElementSchema).optional(),
  diagramHub: diagramNodeSchema.optional(),
  diagramSatellites: z.array(diagramNodeSchema).optional(),
  timelineSteps: z.array(timelineStepSchema).optional(),
});

export const chapterVideoRichPreviewSchema = z.object({
  chapterNumber: z.number(),
  chapterTitle: z.string(),
  audioSegments: z.array(audioSegmentSchema),
  visualSlides: z.array(richVisualSlideSchema),
});

type Props = z.infer<typeof chapterVideoRichPreviewSchema>;
type RichVisualSlide = z.infer<typeof richVisualSlideSchema>;

export const calculateRichPreviewMetadata: CalculateMetadataFunction<Props> = ({ props }) => {
  const total = props.audioSegments.reduce((sum, s) => sum + s.durationInFrames, 0);
  return { durationInFrames: Math.max(total, 1) };
};

const RichSlide: React.FC<{ slide: RichVisualSlide; chapterNumber: number; chapterTitle: string }> = ({
  slide,
  chapterNumber,
  chapterTitle,
}) => {
  if (slide.visualType === "diagram" && slide.diagramHub && slide.diagramSatellites) {
    return (
      <DiagramSlideVisual
        slideNumber={slide.slideNumber}
        visualTitle={slide.visualTitle}
        chapterNumber={chapterNumber}
        chapterTitle={chapterTitle}
        hub={slide.diagramHub}
        satellites={slide.diagramSatellites}
      />
    );
  }
  if (slide.visualType === "timeline" && slide.timelineSteps) {
    return (
      <TimelineSlideVisual
        slideNumber={slide.slideNumber}
        visualTitle={slide.visualTitle}
        chapterNumber={chapterNumber}
        chapterTitle={chapterTitle}
        steps={slide.timelineSteps}
      />
    );
  }
  return (
    <SlideVisualRich
      slideNumber={slide.slideNumber}
      visualTitle={slide.visualTitle}
      keyTerms={slide.keyTerms ?? []}
      keyNumbers={slide.keyNumbers ?? []}
      chapterNumber={chapterNumber}
      chapterTitle={chapterTitle}
    />
  );
};

export const ChapterVideoRichPreview: React.FC<Props> = ({
  chapterNumber,
  chapterTitle,
  audioSegments,
  visualSlides,
}) => {
  let audioStart = 0;
  return (
    <AbsoluteFill>
      {audioSegments.map((seg, i) => {
        const from = audioStart;
        audioStart += seg.durationInFrames;
        return (
          <Sequence key={i} from={from} durationInFrames={seg.durationInFrames}>
            <Audio src={staticFile(seg.file)} />
          </Sequence>
        );
      })}
      <TransitionSeries>
        {visualSlides.flatMap((slide, i) => {
          const items = [
            <TransitionSeries.Sequence key={`slide-${slide.slideNumber}`} durationInFrames={slide.durationInFrames}>
              <RichSlide slide={slide} chapterNumber={chapterNumber} chapterTitle={chapterTitle} />
            </TransitionSeries.Sequence>,
          ];
          if (i < visualSlides.length - 1) {
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
    </AbsoluteFill>
  );
};
