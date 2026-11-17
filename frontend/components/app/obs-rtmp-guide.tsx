"use client";

import { useState, type ReactNode } from "react";

import { cx } from "@/lib/format";

const PLUGIN_RELEASES = "https://github.com/sorayuki/obs-multi-rtmp/releases";

function BigStep({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children?: ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-sm font-bold text-white">
        {n}
      </span>
      <div className="min-w-0 flex-1 pt-1">
        <p className="text-base font-semibold text-white">{title}</p>
        {children ? <div className="mt-1.5 text-sm leading-relaxed text-ink-300">{children}</div> : null}
      </div>
    </li>
  );
}

function HelpDetails({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="rounded-2xl border border-white/10 bg-ink-950/50 px-4 py-3">
      <summary className="cursor-pointer text-sm font-medium text-ink-200 hover:text-white">
        {summary}
      </summary>
      <div className="mt-3 space-y-2 text-sm leading-relaxed text-ink-400">{children}</div>
    </details>
  );
}

function OsHint() {
  const [os, setOs] = useState<"windows" | "mac" | "linux">("windows");
  const tabs = [
    { id: "windows" as const, label: "Windows" },
    { id: "mac" as const, label: "Mac" },
    { id: "linux" as const, label: "Linux" },
  ];
  const hint =
    os === "windows"
      ? "Téléchargez le fichier …-windows-x64-Installer.exe, fermez OBS, lancez l’installeur."
      : os === "mac"
        ? "Téléchargez le …-macos-universal.pkg, fermez OBS, ouvrez le fichier."
        : "Prenez le .deb (ou le zip plugins) adapté à votre install OBS, puis relancez OBS.";
  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setOs(tab.id)}
            className={cx(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              os === tab.id
                ? "bg-brand-500/25 text-brand-100"
                : "bg-ink-900 text-ink-400 hover:text-ink-200",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <p>{hint}</p>
    </div>
  );
}

function ObsSetup() {
  return (
    <div className="space-y-5">
      <ol className="space-y-5">
        <BigStep n={1} title="Installez le plugin Multiple RTMP">
          <p>
            OBS ne peut envoyer qu’un live à la fois. Ce plugin ajoute STREAMCLIP{" "}
            <strong className="text-ink-100">en plus</strong> de Twitch / YouTube.
          </p>
          <a
            href={PLUGIN_RELEASES}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-400"
          >
            Télécharger le plugin
          </a>
          <OsHint />
        </BigStep>
        <BigStep n={2} title="Ouvrez le panneau dans OBS">
          Relancez OBS → menu <strong className="text-ink-100">Affichage → Panneaux</strong> →
          cochez <strong className="text-ink-100">Multiple RTMP Output</strong>.
        </BigStep>
        <BigStep n={3} title="Ajoutez STREAMCLIP">
          Dans le panneau : <strong className="text-ink-100">Ajouter / Edit targets</strong> →
          Custom. Collez le <strong className="text-ink-100">serveur</strong> et la{" "}
          <strong className="text-ink-100">clé</strong> de l’étape précédente.
        </BigStep>
        <BigStep n={4} title="Gardez Twitch / YouTube comme d’habitude">
          Paramètres → Stream : ne changez rien. STREAMCLIP reste uniquement dans le plugin.
        </BigStep>
      </ol>

      <HelpDetails summary="Le panneau n’apparaît pas ?">
        <p>Vérifiez que la version du plugin correspond à votre OBS (Aide → À propos).</p>
        <p>Fermez complètement OBS avant d’installer, puis relancez.</p>
      </HelpDetails>
    </div>
  );
}

function StreamlabsSetup() {
  return (
    <div className="space-y-5">
      <ol className="space-y-5">
        <BigStep n={1} title="Ouvrez Settings → Stream">
          Cliquez sur l’engrenage en bas à gauche, puis l’onglet Stream.
        </BigStep>
        <BigStep n={2} title="Ajoutez une destination Custom">
          <strong className="text-ink-100">Add Destination</strong> → Custom RTMP (ou Custom
          Ingest).
        </BigStep>
        <BigStep n={3} title="Collez serveur + clé">
          Serveur = celui de l’étape précédente. Clé = votre clé STREAMCLIP. Nommez « STREAMCLIP »
          et enregistrez.
        </BigStep>
        <BigStep n={4} title="Cochez les deux au Go Live">
          Au démarrage : plateforme principale <em>et</em> STREAMCLIP, puis Confirmer.
        </BigStep>
      </ol>

      <HelpDetails summary="Je ne vois pas « Add Destination »">
        <p>
          Sans Multistream, Streamlabs peut remplacer Twitch au lieu d’ajouter une 2ᵉ sortie.
          Dans ce cas, utilisez OBS Studio + le plugin Multiple RTMP (plus simple pour un 2ᵉ
          flux).
        </p>
      </HelpDetails>
    </div>
  );
}

/** Short setup checklist for onboarding step 6 (after the key exists). */
export function ObsSetupGuide({ software }: { software: "obs" | "streamlabs" }) {
  return software === "streamlabs" ? <StreamlabsSetup /> : <ObsSetup />;
}

/** @deprecated Prefer ObsSetupGuide + StreamKeyManager split across steps. */
export function ObsRtmpGuide({
  software,
}: {
  software: "obs" | "streamlabs";
  existingKey?: unknown;
  canManage?: boolean;
  ingestOnline?: boolean;
  rtmpUrl?: string | null;
}) {
  return <ObsSetupGuide software={software} />;
}
