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
  /** Free accounts only — paid plans render without watermark. */
  showWatermark?: boolean;
};

const W = 1080;
const H = 1920;
const SOURCE_W = 1920;
const SOURCE_H = 1080;

/** TikTok-style captions: Komika Axis, 60px, 16px stroke. */
const CAPTION_FONT =
  '"Komika Axis", "KomikaAxis", "Komika Axis Regular", Impact, Haettenschweiler, sans-serif';
const CAPTION_SIZE = 60;
const CAPTION_STROKE = 16;

const WATERMARK_HOLD_SEC = 2.8;

type WatermarkSlot = "left" | "middle" | "right";

function activeWords(words: CaptionWord[], timeMs: number): CaptionWord[] {
  return words.filter((w) => w.start_ms <= timeMs && w.end_ms >= timeMs - 400);
}

function camTransform(camera: CameraFocus): CSSProperties {
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

/** Deterministic pseudo-random in [0, 1) from integer seed. */
function hash01(n: number): number {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

/**
 * Pick a watermark slot for each hold window — hard cuts only, no interpolation.
 * left (haut gauche) → middle → right, order shuffled per window.
 */
function watermarkSlot(frame: number, fps: number, seed: number): WatermarkSlot {
  const holdFrames = Math.max(1, Math.round(WATERMARK_HOLD_SEC * fps));
  const windowIndex = Math.floor(frame / holdFrames);
  const slots: WatermarkSlot[] = ["left", "middle", "right"];
  const a = Math.floor(hash01(seed + windowIndex * 17) * 3);
  const b = Math.floor(hash01(seed + windowIndex * 31 + 1) * 2);
  const order = [...slots];
  const t0 = order[a]!;
  order[a] = order[0]!;
  order[0] = t0;
  const t1 = order[1 + b]!;
  order[1 + b] = order[1]!;
  order[1] = t1;
  return order[0]!;
}

function watermarkStyle(slot: WatermarkSlot): CSSProperties {
  const base: CSSProperties = {
    position: "absolute",
    top: 56,
    zIndex: 20,
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 14px",
    borderRadius: 14,
    backgroundColor: "rgba(1, 0, 20, 0.55)",
    border: "1px solid rgba(255,255,255,0.14)",
    transition: "none",
  };
  if (slot === "left") {
    return { ...base, left: 40, right: "auto", transform: "none" };
  }
  if (slot === "right") {
    return { ...base, left: "auto", right: 40, transform: "none" };
  }
  return { ...base, left: "50%", right: "auto", transform: "translateX(-50%)" };
}

function StreamclipWatermark({ frame, fps, seed }: { frame: number; fps: number; seed: number }) {
  const slot = watermarkSlot(frame, fps, seed);
  return (
    <div style={watermarkStyle(slot)}>
      <svg width={28} height={28} viewBox="0 0 32 32" aria-hidden>
        <defs>
          <linearGradient id="sc-wm-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#0021f3" />
            <stop offset="1" stopColor="#0013de" />
          </linearGradient>
        </defs>
        <rect x="8" y="2" width="16" height="28" rx="5" fill="url(#sc-wm-grad)" />
        <path d="M14 11.5v9l7-4.5z" fill="#010014" />
      </svg>
      <span
        style={{
          color: "#fff",
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: "0.04em",
          fontFamily: "system-ui, sans-serif",
          textTransform: "uppercase",
        }}
      >
        streamclip
      </span>
    </div>
  );
}

export const ViralHighlight: FC<ViralHighlightProps> = ({
  src,
  relativeStartMs,
  relativeEndMs,
  words,
  camera,
  title,
  showWatermark = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = relativeStartMs + (frame / fps) * 1000;
  const captions = activeWords(words, timeMs);
  const dual = camera.detected;
  const durationFrames = Math.max(1, Math.round(((relativeEndMs - relativeStartMs) / 1000) * fps));
  const watermarkSeed = title.length * 97 + Math.round(relativeStartMs);

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

      {showWatermark ? <StreamclipWatermark frame={frame} fps={fps} seed={watermarkSeed} /> : null}

      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          padding: "48px 40px 80px",
          background:
            "linear-gradient(to top, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.2) 40%, transparent 70%)",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            fontSize: 28,
            fontWeight: 600,
            color: "rgba(255,255,255,0.85)",
            marginBottom: 16,
            fontFamily: "system-ui, sans-serif",
            textAlign: "center",
          }}
        >
          {title}
        </div>
        <div
          style={{
            minHeight: 88,
            fontSize: CAPTION_SIZE,
            fontWeight: 700,
            lineHeight: 1.15,
            color: "#fff",
            textAlign: "center",
            fontFamily: CAPTION_FONT,
            WebkitTextStroke: `${CAPTION_STROKE}px #000`,
            paintOrder: "stroke fill",
            letterSpacing: "0.01em",
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
