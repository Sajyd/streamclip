"use client";

import { useState, type ReactNode } from "react";

import { CopyField } from "@/components/app/ingest-credentials";
import { buttonClasses } from "@/components/ui/button";
import { cx } from "@/lib/format";

/** Pinned Multi RTMP build (OBS 32.x). Direct asset URLs — no GitHub hunting. */
const PLUGIN_VERSION = "0.7.4.5";
const PLUGIN_OBS_TARGET = "OBS 32.x";
const PLUGIN_DOWNLOADS = {
  windows: {
    label: "Windows",
    file: `obs-multi-rtmp-${PLUGIN_VERSION}-windows-x64-Installer.exe`,
    url: `https://github.com/sorayuki/obs-multi-rtmp/releases/download/${PLUGIN_VERSION}/obs-multi-rtmp-${PLUGIN_VERSION}-windows-x64-Installer.exe`,
    hint: "Installeur .exe · 64 bits",
  },
  mac: {
    label: "Mac",
    file: `obs-multi-rtmp-${PLUGIN_VERSION}-macos-universal.pkg`,
    url: `https://github.com/sorayuki/obs-multi-rtmp/releases/download/${PLUGIN_VERSION}/obs-multi-rtmp-${PLUGIN_VERSION}-macos-universal.pkg`,
    hint: "Package .pkg · Apple Silicon & Intel",
  },
  linux: {
    label: "Linux",
    file: `obs-multi-rtmp-${PLUGIN_VERSION}-x86_64-linux-gnu-ubuntu-24.04.deb`,
    url: `https://github.com/sorayuki/obs-multi-rtmp/releases/download/${PLUGIN_VERSION}/obs-multi-rtmp-${PLUGIN_VERSION}-x86_64-linux-gnu-ubuntu-24.04.deb`,
    hint: "Paquet .deb · Ubuntu 24.04 / dérivés",
  },
} as const;

type PluginOs = keyof typeof PLUGIN_DOWNLOADS;

export type Creds = { server: string; streamKey: string };

function CredsCard({
  creds,
  emptyHint = "Créez ou régénérez votre clé STREAMCLIP pour afficher le serveur et la clé à coller.",
}: {
  creds: Creds | null;
  emptyHint?: string;
}) {
  if (!creds) {
    return (
      <p className="rounded-2xl border border-danger-500/30 bg-danger-500/10 px-4 py-3 text-sm text-danger-400">
        {emptyHint}
      </p>
    );
  }
  return (
    <div className="space-y-3 rounded-2xl border border-warn-400/35 bg-warn-400/10 p-4">
      <p className="text-xs font-semibold tracking-wide text-warn-400 uppercase">
        À coller dans votre logiciel de diffusion
      </p>
      <CopyField label="Serveur" value={creds.server} />
      <CopyField label="Clé secrète" value={creds.streamKey} />
    </div>
  );
}

function ActionTitle({ n, title }: { n?: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      {n != null ? (
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-sm font-bold text-white">
          {n}
        </span>
      ) : null}
      <h3 className="text-lg font-semibold text-white">{title}</h3>
    </div>
  );
}

function OsPick({
  value,
  onChange,
}: {
  value: PluginOs;
  onChange: (v: PluginOs) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {(Object.keys(PLUGIN_DOWNLOADS) as PluginOs[]).map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cx(
            "rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
            value === id
              ? "bg-brand-500 text-white"
              : "bg-ink-900 text-ink-400 hover:text-ink-200",
          )}
        >
          {PLUGIN_DOWNLOADS[id].label}
        </button>
      ))}
    </div>
  );
}

/** Step: download the plugin — one direct link per OS. */
export function PluginDownloadStep() {
  return (
    <div className="space-y-5">
      <ActionTitle n={1} title="Téléchargez Multiple RTMP" />
      <p className="text-sm text-ink-300">
        Version {PLUGIN_VERSION} pour {PLUGIN_OBS_TARGET}. Un clic = le bon fichier, rien à
        chercher.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {(Object.keys(PLUGIN_DOWNLOADS) as PluginOs[]).map((id) => {
          const item = PLUGIN_DOWNLOADS[id];
          return (
            <a
              key={id}
              href={item.url}
              download={item.file}
              target="_blank"
              rel="noreferrer"
              className="flex flex-col rounded-2xl border border-white/10 bg-ink-950/60 p-4 transition-colors hover:border-brand-400/50 hover:bg-brand-500/10"
            >
              <span className="text-base font-semibold text-white">{item.label}</span>
              <span className="mt-1 text-xs text-ink-400">{item.hint}</span>
              <span className="mt-3 text-sm font-medium text-brand-300">Télécharger →</span>
            </a>
          );
        })}
      </div>
      <p className="text-xs text-ink-500">
        OBS plus ancien ? Prenez une release adaptée sur le dépôt officiel du plugin.
      </p>
    </div>
  );
}

/** Step: install the plugin. */
export function PluginInstallStep() {
  const [os, setOs] = useState<PluginOs>("windows");
  const file = PLUGIN_DOWNLOADS[os].file;
  const lines: Record<PluginOs, string[]> = {
    windows: [
      "Fermez OBS complètement (vérifiez la barre des tâches).",
      `Double-cliquez sur « ${file} ».`,
      "Laissez le chemin par défaut, validez.",
    ],
    mac: [
      "Quittez OBS.",
      `Ouvrez « ${file} » et suivez l’assistant.`,
      "Si macOS bloque : Réglages → Confidentialité → Autoriser.",
    ],
    linux: [
      "Quittez OBS.",
      `Installez « ${file} » (double-clic ou sudo apt install ./fichier.deb).`,
      "Relancez OBS.",
    ],
  };
  return (
    <div className="space-y-5">
      <ActionTitle n={2} title="Installez le plugin" />
      <OsPick value={os} onChange={setOs} />
      <p className="text-sm text-ink-400">
        Fichier : <code className="break-all text-ink-200">{file}</code>
      </p>
      <a
        href={PLUGIN_DOWNLOADS[os].url}
        download={file}
        target="_blank"
        rel="noreferrer"
        className={buttonClasses({ variant: "secondary", size: "sm" })}
      >
        Retélécharger pour {PLUGIN_DOWNLOADS[os].label}
      </a>
      <ol className="space-y-3">
        {lines[os].map((line, i) => (
          <li key={line} className="flex gap-3 text-sm text-ink-200">
            <span className="font-semibold text-brand-300">{i + 1}.</span>
            <span>{line}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Step: verify the dock appears. */
export function PluginVerifyStep() {
  return (
    <div className="space-y-5">
      <ActionTitle n={3} title="Vérifiez le panneau" />
      <ol className="space-y-3 text-sm text-ink-200">
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">1.</span>
          <span>Relancez OBS Studio.</span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">2.</span>
          <span>
            Menu <strong className="text-white">Affichage → Panneaux</strong> (ou Docks).
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">3.</span>
          <span>
            Cochez <strong className="text-white">Multiple RTMP Output</strong>.
          </span>
        </li>
      </ol>
      <p className="rounded-2xl border border-white/10 bg-ink-950/60 px-4 py-3 text-sm text-ink-400">
        Un panneau apparaît en bas ou sur le côté. Sinon : version du plugin ≠ version d’OBS
        (Aide → À propos).
      </p>
    </div>
  );
}

/** Step: paste STREAMCLIP server + key into the plugin. */
export function PluginConnectStep({ creds }: { creds: Creds | null }) {
  return (
    <div className="space-y-5">
      <ActionTitle n={4} title="Ajoutez STREAMCLIP" />
      <CredsCard creds={creds} />
      <ol className="space-y-3 text-sm text-ink-200">
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">1.</span>
          <span>
            Dans Multiple RTMP : <strong className="text-white">Ajouter / Edit targets</strong>.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">2.</span>
          <span>
            Type = <strong className="text-white">Custom</strong>.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">3.</span>
          <span>Collez le serveur, puis la clé secrète (ci-dessus).</span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">4.</span>
          <span>
            Cochez{" "}
            <strong className="text-white">Synchroniser le démarrage avec OBS</strong> (Sync
            start with OBS).
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">5.</span>
          <span>
            Paramètres → Stream : laissez Twitch / YouTube inchangés. STREAMCLIP reste dans le
            plugin.
          </span>
        </li>
      </ol>
      <p className="rounded-2xl border border-white/10 bg-ink-950/60 px-4 py-3 text-sm text-ink-300">
        Débit vidéo : <strong className="text-white">4 500 Kbps</strong> (6 000 maximum), contrôle{" "}
        <strong className="text-white">CBR</strong>, intervalle d’images clés{" "}
        <strong className="text-white">2 secondes</strong>. Dans OBS : Réglages → Avancé → Réseau,
        activez « Ajuster dynamiquement le débit en cas de congestion ». Au-dessus de ce que
        l’upload tient, OBS jette les images vidéo et garde le son : le segment fige.
      </p>
    </div>
  );
}

/** Short Streamlabs path (no Multi RTMP plugin). Creds live in StreamKeyManager above. */
export function StreamlabsConnectStep(_props?: { creds?: Creds | null }) {
  return (
    <div className="space-y-5">
      <ActionTitle title="Ajoutez STREAMCLIP dans Streamlabs" />
      <p className="rounded-2xl border border-white/10 bg-ink-950/60 px-4 py-3 text-sm text-ink-300">
        Utilisez le <strong className="text-white">serveur</strong> et la{" "}
        <strong className="text-white">clé secrète</strong> affichés dans la section « Votre clé
        STREAMCLIP » ci-dessus (après création ou régénération).
      </p>
      <ol className="space-y-3 text-sm text-ink-200">
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">1.</span>
          <span>
            Engrenage → <strong className="text-white">Stream</strong>.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">2.</span>
          <span>
            <strong className="text-white">Add Destination</strong> → Custom RTMP.
          </span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">3.</span>
          <span>Collez serveur + clé depuis la section clé, nommez « STREAMCLIP ».</span>
        </li>
        <li className="flex gap-3">
          <span className="font-semibold text-brand-300">4.</span>
          <span>Au Go Live : cochez votre plateforme + STREAMCLIP.</span>
        </li>
      </ol>
      <p className="rounded-2xl border border-white/10 bg-ink-950/60 px-4 py-3 text-sm text-ink-300">
        Débit vidéo : <strong className="text-white">4 500 Kbps</strong> (6 000 maximum), CBR,
        image clé toutes les <strong className="text-white">2 secondes</strong>. Si le compteur
        d’images perdues monte, baissez le débit : sinon la vidéo se fige et le son continue.
      </p>
    </div>
  );
}

/** @deprecated kept for any leftover imports */
export function ObsSetupGuide({
  software,
  creds,
}: {
  software: "obs" | "streamlabs";
  creds?: Creds | null;
  children?: ReactNode;
}) {
  return software === "streamlabs" ? (
    <StreamlabsConnectStep creds={creds ?? null} />
  ) : (
    <PluginConnectStep creds={creds ?? null} />
  );
}

export function ObsRtmpGuide(props: {
  software: "obs" | "streamlabs";
  existingKey?: unknown;
  canManage?: boolean;
  ingestOnline?: boolean;
  rtmpUrl?: string | null;
}) {
  return <ObsSetupGuide software={props.software} />;
}
