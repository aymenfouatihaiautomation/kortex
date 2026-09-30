import React from "react";
import { Composition } from "remotion";
import { ChapterVideo, chapterVideoSchema, calculateChapterMetadata } from "./ChapterVideo";
import {
  ChapterVideoPreview,
  chapterVideoPreviewSchema,
  calculatePreviewMetadata,
} from "./ChapterVideoPreview";
import {
  ChapterVideoRichPreview,
  chapterVideoRichPreviewSchema,
  calculateRichPreviewMetadata,
} from "./ChapterVideoRichPreview";
import { ArchitectureDiagramPOC } from "./ArchitectureDiagram";
import { ArchitectureDiagramV2POC } from "./ArchitectureDiagramV2";
import { TimelineDiagramPOC } from "./TimelineDiagram";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ChapterVideo"
        component={ChapterVideo}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        schema={chapterVideoSchema}
        defaultProps={{
          chapterNumber: 1,
          chapterTitle: "Titre du chapitre",
          slides: [],
        }}
        calculateMetadata={calculateChapterMetadata}
      />
      <Composition
        id="ChapterVideoPreview"
        component={ChapterVideoPreview}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        schema={chapterVideoPreviewSchema}
        defaultProps={{
          chapterNumber: 1,
          chapterTitle: "Titre du chapitre",
          audioSegments: [],
          visualSlides: [],
        }}
        calculateMetadata={calculatePreviewMetadata}
      />
      <Composition
        id="ChapterVideoRichPreview"
        component={ChapterVideoRichPreview}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        schema={chapterVideoRichPreviewSchema}
        defaultProps={{
          chapterNumber: 1,
          chapterTitle: "Titre du chapitre",
          audioSegments: [],
          visualSlides: [],
        }}
        calculateMetadata={calculateRichPreviewMetadata}
      />
      <Composition
        id="ArchitectureDiagramPOC"
        component={ArchitectureDiagramPOC}
        durationInFrames={120}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="ArchitectureDiagramV2POC"
        component={ArchitectureDiagramV2POC}
        durationInFrames={120}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="TimelineDiagramPOC"
        component={TimelineDiagramPOC}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
