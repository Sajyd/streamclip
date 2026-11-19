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

export type GameplayFit = "height" | "width";

export type ViralHighlightProps = {
  src: string;
  relativeStartMs: number;
  relativeEndMs: number;
  words: CaptionWord[];
  camera: CameraFocus;
  title: string;
  /** How the gameplay pane is scaled. Height keeps the frame from cropping top and bottom. */
  gameplayFit?: GameplayFit;
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

/** Inner size of each pane inside the 1080×1920 frame (padding 8, gap 8). */
function paneBox(dual: boolean, which: "game" | "cam"): { w: number; h: number } {
  if (!dual) return { w: W, h: H };
  const innerH = H - 16 - 8;
  const innerW = W - 16;
  const h = innerH * (which === "game" ? 1.15 : 0.85) / 2;
  return { w: innerW, h };
}

/** Crop around the detected facecam so that window fills the lower pane. */
const CAM_CROP_W = 480;

function cameraFrame(camera: CameraFocus): CSSProperties {
  const pane = paneBox(true, "cam");
  const aspect = pane.w / pane.h;
  let cropW = CAM_CROP_W;
  let cropH = cropW / aspect;
  if (cropH > SOURCE_H) {
    cropH = SOURCE_H;
    cropW = cropH * aspect;
  }
  const left = Math.max(0, Math.min(SOURCE_W - cropW, camera.x - cropW / 2));
  const top = Math.max(0, Math.min(SOURCE_H - cropH, camera.y - cropH / 2));
  return {
    position: "absolute",
    width: `${(SOURCE_W / cropW) * 100}%`,
    height: `${(SOURCE_H / cropH) * 100}%`,
    left: `${-(left / cropW) * 100}%`,
    top: `${-(top / cropH) * 100}%`,
    objectFit: "fill",
    maxWidth: "none",
    maxHeight: "none",
  };
}

function gameplayStyle(fit: GameplayFit, dual: boolean): CSSProperties {
  const pane = paneBox(dual, "game");
  const scale = fit === "height" ? pane.h / SOURCE_H : pane.w / SOURCE_W;
  return {
    position: "absolute",
    left: "50%",
    top: "50%",
    width: SOURCE_W * scale,
    height: SOURCE_H * scale,
    transform: "translate(-50%, -50%)",
    objectFit: "contain",
    maxWidth: "none",
    maxHeight: "none",
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
  gameplayFit = "height",
  showWatermark = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = relativeStartMs + (frame / fps) * 1000;
  const captions = activeWords(words, timeMs);
  const dual = camera.detected;
  const durationFrames = Math.max(1, Math.round(((relativeEndMs - relativeStartMs) / 1000) * fps));
  const watermarkSeed = title.length * 97 + Math.round(relativeStartMs);
  const startFrom = Math.round((relativeStartMs / 1000) * fps);
  const endAt = Math.round((relativeEndMs / 1000) * fps);
  const caption = captions.map((word) => word.text).join(" ");

  return (
    <AbsoluteFill style={{ backgroundColor: "#010014", overflow: "hidden" }}>
      <Video
        src={src}
        startFrom={startFrom}
        endAt={endAt}
        muted
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: "blur(48px)",
          transform: "scale(1.15)",
        }}
      />
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
              minHeight: 0,
              overflow: "hidden",
              borderRadius: dual ? 16 : 0,
            }}
          >
            <Video
              src={src}
              startFrom={startFrom}
              endAt={endAt}
              style={gameplayStyle(gameplayFit, dual)}
            />
          </div>
          {dual ? (
            <div
              style={{
                flex: 0.85,
                position: "relative",
                minHeight: 0,
                overflow: "hidden",
                borderRadius: 16,
              }}
            >
              <Video
                src={src}
                startFrom={startFrom}
                endAt={endAt}
                muted
                style={cameraFrame(camera)}
              />
            </div>
          ) : null}
        </AbsoluteFill>
      </Sequence>

      {showWatermark ? <StreamclipWatermark frame={frame} fps={fps} seed={watermarkSeed} /> : null}

      {caption ? (
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            padding: "0 48px",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              maxWidth: "100%",
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
            {caption}
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

export const COMPOSITION = {
  id: "ViralHighlight",
  width: W,
  height: H,
  fps: 30,
};
