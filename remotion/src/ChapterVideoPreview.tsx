import React from "react";
import { z } from "zod";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import type { CalculateMetadataFunction } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { SlideVisual, timedElementSchema, TRANSITION_FRAMES } from "./ChapterVideo";

/**
 * Composition de PRÉVISUALISATION : réutilise de l'audio déjà généré (payé) lors d'un pilote
 * précédent, sans nouvel appel TTS. L'audio (segments réels, durées exactes) et le visuel
 * (nouveau découpage en diapositives, durées approximatives proportionnelles) sont deux timelines
 * indépendantes de même durée totale — ce n'est PAS une synchronisation exacte parole/visuel
 * (celle-ci nécessite l'alignement ElevenLabs `with-timestamps`, absent de cet audio réutilisé).
 */

const audioSegmentSchema = z.object({
  file: z.string(),
  durationInFrames: z.number(),
});

const visualSlideSchema = z.object({
  slideNumber: z.number(),
  visualTitle: z.string(),
  keyTerms: z.array(timedElementSchema),
  keyNumbers: z.array(timedElementSchema),
  durationInFrames: z.number(),
});

export const chapterVideoPreviewSchema = z.object({
  chapterNumber: z.number(),
  chapterTitle: z.string(),
  audioSegments: z.array(audioSegmentSchema),
  visualSlides: z.array(visualSlideSchema),
});

type Props = z.infer<typeof chapterVideoPreviewSchema>;

export const calculatePreviewMetadata: CalculateMetadataFunction<Props> = ({ props }) => {
  const total = props.audioSegments.reduce((sum, s) => sum + s.durationInFrames, 0);
  return { durationInFrames: Math.max(total, 1) };
};

export const ChapterVideoPreview: React.FC<Props> = ({
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
              <SlideVisual
                slideNumber={slide.slideNumber}
                visualTitle={slide.visualTitle}
                keyTerms={slide.keyTerms}
                keyNumbers={slide.keyNumbers}
                chapterNumber={chapterNumber}
                chapterTitle={chapterTitle}
              />
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
