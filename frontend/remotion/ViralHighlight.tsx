"use client";

import type { CSSProperties, FC } from "react";
import { AbsoluteFill, Sequence, Video, useCurrentFrame, useVideoConfig } from "remotion";

export type CaptionWord = {
  text: string;
  start_ms: number;
  end_ms: number;
};

export type CameraFocus = {
  detected: boolean;
  x: number;
  y: number;
};

export type ViralHighlightProps = {
  src: string;
  relativeStartMs: number;
  relativeEndMs: number;
  words: CaptionWord[];
  camera: CameraFocus;
  title: string;
};

const W = 1080;
const H = 1920;
const SOURCE_W = 1920;
const SOURCE_H = 1080;

function activeWords(words: CaptionWord[], timeMs: number): CaptionWord[] {
  return words.filter((w) => w.start_ms <= timeMs && w.end_ms >= timeMs - 400);
}

function camTransform(camera: CameraFocus): CSSProperties {
  // Crop a 9:16 viewport centered on streamer cam (x,y on 1920×1080).
  const focusX = camera.x / SOURCE_W;
  const focusY = camera.y / SOURCE_H;
  const scale = Math.max(H / SOURCE_H, W / (SOURCE_W * 0.45));
  const tx = 50 - focusX * 100;
  const ty = 50 - focusY * 100;
  return {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    objectPosition: `${50 + tx * 0.35}% ${50 + ty * 0.35}%`,
    transform: `scale(${Math.min(scale, 2.2)})`,
    transformOrigin: `${focusX * 100}% ${focusY * 100}%`,
  };
}

export const ViralHighlight: FC<ViralHighlightProps> = ({
  src,
  relativeStartMs,
  relativeEndMs,
  words,
  camera,
  title,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = relativeStartMs + (frame / fps) * 1000;
  const captions = activeWords(words, timeMs);
  const dual = camera.detected;
  const durationFrames = Math.max(1, Math.round(((relativeEndMs - relativeStartMs) / 1000) * fps));

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0b" }}>
      <Sequence from={0} durationInFrames={durationFrames}>
        <AbsoluteFill
          style={{
            display: "flex",
            flexDirection: "column",
            gap: dual ? 8 : 0,
            padding: dual ? 8 : 0,
          }}
        >
          <div
            style={{
              flex: dual ? 1.15 : 1,
              position: "relative",
              overflow: "hidden",
              borderRadius: dual ? 16 : 0,
            }}
          >
            <Video
              src={src}
              startFrom={Math.round((relativeStartMs / 1000) * fps)}
              endAt={Math.round((relativeEndMs / 1000) * fps)}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>
          {dual ? (
            <div
              style={{
                flex: 0.85,
                position: "relative",
                overflow: "hidden",
                borderRadius: 16,
                border: "1px solid rgba(255,255,255,0.12)",
              }}
            >
              <Video
                src={src}
                startFrom={Math.round((relativeStartMs / 1000) * fps)}
                endAt={Math.round((relativeEndMs / 1000) * fps)}
                style={camTransform(camera)}
              />
              <div
                style={{
                  position: "absolute",
                  left: 12,
                  top: 12,
                  fontSize: 22,
                  color: "rgba(255,255,255,0.7)",
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                Cam streamer
              </div>
            </div>
          ) : null}
        </AbsoluteFill>
      </Sequence>

      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          padding: "48px 40px 80px",
          background:
            "linear-gradient(to top, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.2) 40%, transparent 70%)",
        }}
      >
        <div
          style={{
            fontSize: 28,
            fontWeight: 600,
            color: "rgba(255,255,255,0.85)",
            marginBottom: 16,
            fontFamily: "system-ui, sans-serif",
          }}
        >
          {title}
        </div>
        <div
          style={{
            minHeight: 72,
            fontSize: 42,
            fontWeight: 700,
            lineHeight: 1.25,
            color: "#fff",
            textAlign: "center",
            textShadow: "0 2px 12px rgba(0,0,0,0.8)",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          {captions.map((w) => w.text).join(" ")}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const COMPOSITION = {
  id: "ViralHighlight",
  width: W,
  height: H,
  fps: 30,
};
