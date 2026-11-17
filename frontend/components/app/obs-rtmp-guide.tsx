"use client";

import { useState, type ReactNode } from "react";

import { StreamKeyManager } from "@/components/app/ingest-credentials";
import { cx } from "@/lib/format";
import type { StreamKey } from "@/types/api";

const PLUGIN_RELEASES = "https://github.com/sorayuki/obs-multi-rtmp/releases";
const PLUGIN_FORUM =
  "https://obsproject.com/forum/resources/multiple-rtmp-outputs-plugin.142/";
const STREAMLABS_CUSTOM =
  "https://streamlabs.com/content-hub/post/how-to-stream-new-platform-custom-ingest";
const STREAMLABS_MULTI =
  "https://support.streamlabs.com/hc/en-us/articles/4401775698971-How-to-Multistream-The-Ultimate-Guide-to-Multistreaming";

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-sm font-semibold tracking-wide text-white uppercase">{children}</h3>
  );
}

function StepList({
  steps,
}: {
  steps: ReadonlyArray<{ title: string; body: ReactNode; tip?: string }>;
}) {
  return (
    <ol className="space-y-4">
      {steps.map((step, index) => (
        <li key={step.title} className="flex gap-3">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-200">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <p className="text-sm font-medium text-white">{step.title}</p>
            <div className="mt-1 text-sm leading-relaxed text-ink-300">{step.body}</div>
            {step.tip ? (
              <p className="mt-2 rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-xs leading-relaxed text-ink-400">
                {step.tip}
              </p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-brand-300 underline-offset-2 hover:text-brand-200 hover:underline"
    >
      {children}
    </a>
  );
}

function OsTabs({
  windows,
  mac,
  linux,
}: {
  windows: ReactNode;
  mac: ReactNode;
  linux: ReactNode;
}) {
  const [os, setOs] = useState<"windows" | "mac" | "linux">("windows");
  const tabs = [
    { id: "windows" as const, label: "Windows" },
    { id: "mac" as const, label: "macOS" },
    { id: "linux" as const, label: "Linux" },
  ];
  return (
    <div className="mt-3">
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
      <div className="mt-3 text-sm leading-relaxed text-ink-300">
        {os === "windows" ? windows : null}
        {os === "mac" ? mac : null}
        {os === "linux" ? linux : null}
      </div>
    </div>
  );
}

function ObsPluginGuide() {
  return (
    <div className="space-y-6 rounded-2xl border border-white/10 bg-ink-950/40 p-4 sm:p-5">
      <div>
        <SectionTitle>Installer le plugin Multiple RTMP Outputs</SectionTitle>
        <p className="mt-2 text-sm leading-relaxed text-ink-300">
          Ce plugin (obs-multi-rtmp) envoie une copie de votre live vers STREAMCLIP tout en
          gardant Twitch, YouTube ou Kick comme destination principale. Sans lui, OBS ne peut
          diffuser que vers un seul serveur à la fois.
        </p>
      </div>

      <StepList
        steps={[
          {
            title: "Vérifiez votre version d’OBS Studio",
            body: (
              <>
                Ouvrez OBS → <strong className="text-ink-100">Aide → À propos</strong>. Notez le
                numéro (ex. 31.x ou 32.x) : le plugin doit correspondre à cette version.
              </>
            ),
          },
          {
            title: "Téléchargez la bonne build",
            body: (
              <>
                Allez sur les{" "}
                <ExternalLink href={PLUGIN_RELEASES}>releases GitHub sorayuki/obs-multi-rtmp</ExternalLink>{" "}
                (miroir forum :{" "}
                <ExternalLink href={PLUGIN_FORUM}>obsproject.com</ExternalLink>). Choisissez la
                release indiquée pour votre version d’OBS, puis le fichier de votre système.
              </>
            ),
            tip: "Windows : préfèrez le fichier …-windows-x64-Installer.exe. macOS : …-macos-universal.pkg. Ne mélangez pas l’installeur .exe et le .zip (emplacements différents).",
          },
          {
            title: "Fermez OBS complètement",
            body: (
              <>
                Quittez OBS (pas seulement la fenêtre principale). Sur Windows, vérifiez dans le
                gestionnaire des tâches qu’aucun processus <code className="text-ink-100">obs64</code>{" "}
                ne tourne encore.
              </>
            ),
          },
          {
            title: "Installez selon votre OS",
            body: (
              <OsTabs
                windows={
                  <ul className="list-disc space-y-1.5 pl-4">
                    <li>
                      Double-cliquez sur <code className="text-ink-100">…-Installer.exe</code>.
                    </li>
                    <li>
                      Laissez le chemin d’installation par défaut (ne le changez pas).
                    </li>
                    <li>
                      Variante portable : dézippez le <code className="text-ink-100">.zip</code>{" "}
                      directement dans le dossier d’OBS (
                      <code className="text-ink-100">C:\Program Files\obs-studio</code>).
                    </li>
                  </ul>
                }
                mac={
                  <ul className="list-disc space-y-1.5 pl-4">
                    <li>
                      Ouvrez le <code className="text-ink-100">.pkg</code> et suivez l’assistant.
                    </li>
                    <li>
                      Si macOS bloque le fichier : Réglages système → Confidentialité et sécurité →
                      Autoriser quand même.
                    </li>
                    <li>Relancez OBS Studio après l’installation.</li>
                  </ul>
                }
                linux={
                  <ul className="list-disc space-y-1.5 pl-4">
                    <li>
                      Ubuntu / paquet OBS : installez le <code className="text-ink-100">.deb</code>{" "}
                      fourni dans la release adaptée.
                    </li>
                    <li>
                      Flatpak : placez le plugin dans{" "}
                      <code className="text-ink-100">
                        ~/.var/app/com.obsproject.Studio/config/obs-studio/plugins
                      </code>
                      .
                    </li>
                    <li>
                      Autre install : souvent{" "}
                      <code className="text-ink-100">~/.config/obs-studio/plugins</code>.
                    </li>
                  </ul>
                }
              />
            ),
          },
          {
            title: "Vérifiez que le dock apparaît",
            body: (
              <>
                Relancez OBS. Menu <strong className="text-ink-100">Affichage → Panneaux</strong>{" "}
                (ou <strong className="text-ink-100">Docks</strong>) → cochez{" "}
                <strong className="text-ink-100">Multiple RTMP Output</strong>. Un panneau doit
                s’afficher (souvent en bas ou sur le côté).
              </>
            ),
            tip: "Si le panneau n’apparaît pas : activez le Mode Studio une fois, ou vérifiez que la version du plugin correspond bien à votre OBS.",
          },
          {
            title: "Ajoutez la destination STREAMCLIP",
            body: (
              <>
                Dans le panneau Multiple RTMP :{" "}
                <strong className="text-ink-100">Edit targets</strong> (ou Ajouter) → créez une
                cible. Service / type : <strong className="text-ink-100">Custom</strong>. Collez le{" "}
                <strong className="text-ink-100">serveur RTMP</strong> renvoyé après « Démarrer mon
                instance » (<code className="text-ink-100">rtmp://IP:1935/live</code>) et votre{" "}
                <strong className="text-ink-100">clé de stream</strong> complète. Validez.
              </>
            ),
            tip: "N’utilisez pas l’URL https://…/rtmp comme serveur OBS : ce lien prépare seulement l’instance. OBS attend rtmp://…",
          },
          {
            title: "Gardez votre plateforme principale dans OBS",
            body: (
              <>
                Paramètres → Stream : laissez Twitch / YouTube / Kick comme d’habitude. STREAMCLIP
                vit uniquement dans le plugin Multiple RTMP — pas dans la destination principale.
              </>
            ),
          },
          {
            title: "Passez en live",
            body: (
              <>
                1) Cliquez « Démarrer mon instance » ici (ou ouvrez{" "}
                <code className="text-ink-100">/rtmp?key=…</code>) et copiez le serveur{" "}
                <code className="text-ink-100">rtmp://…</code>. 2) Dans OBS,{" "}
                <strong className="text-ink-100">Démarrer le stream</strong> (plateforme principale).
                3) Dans le panneau Multiple RTMP, démarrez la cible STREAMCLIP. Les deux flux partent
                en parallèle.
              </>
            ),
          },
        ]}
      />
    </div>
  );
}

function StreamlabsGuide() {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-white/10 bg-ink-950/40 p-4 sm:p-5">
        <SectionTitle>Option A — Destination Custom RTMP (recommandé)</SectionTitle>
        <p className="mt-2 text-sm leading-relaxed text-ink-300">
          Streamlabs Desktop gère les destinations RTMP natives. Pour diffuser{" "}
          <strong className="text-ink-100">en même temps</strong> vers Twitch/YouTube{" "}
          <em>et</em> STREAMCLIP, il faut ajouter une destination Custom (souvent inclus avec
          Multistream / Ultra). Guide officiel :{" "}
          <ExternalLink href={STREAMLABS_MULTI}>multistream Streamlabs</ExternalLink> ·{" "}
          <ExternalLink href={STREAMLABS_CUSTOM}>custom ingest</ExternalLink>.
        </p>

        <div className="mt-5">
          <StepList
            steps={[
              {
                title: "Préparez votre clé STREAMCLIP",
                body: (
                  <>
                    Créez la clé ci-dessus, copiez-la une fois, puis cliquez « Démarrer mon
                    instance » pour obtenir le serveur{" "}
                    <code className="text-ink-100">rtmp://IP:1935/live</code>.
                  </>
                ),
              },
              {
                title: "Ouvrez les paramètres Stream",
                body: (
                  <>
                    Dans Streamlabs Desktop, cliquez sur l’icône{" "}
                    <strong className="text-ink-100">Settings (engrenage)</strong> → onglet{" "}
                    <strong className="text-ink-100">Stream</strong>.
                  </>
                ),
              },
              {
                title: "Ajoutez une destination Custom RTMP",
                body: (
                  <>
                    Cliquez <strong className="text-ink-100">Add Destination</strong>. Choisissez
                    une destination de type{" "}
                    <strong className="text-ink-100">Custom / Custom RTMP / Custom Ingest</strong>{" "}
                    (libellé selon la version).
                  </>
                ),
                tip: "Sans Ultra, « Stream to Custom Ingest » peut remplacer votre plateforme principale au lieu d’ajouter une 2ᵉ sortie. Pour garder Twitch + STREAMCLIP, utilisez Add Destination (Multistream) ou passez par OBS Studio + le plugin (option B).",
              },
              {
                title: "Remplissez serveur + clé",
                body: (
                  <>
                    <strong className="text-ink-100">URL / Server</strong> = serveur RTMP STREAMCLIP
                    (<code className="text-ink-100">rtmp://…:1935/live</code>).{" "}
                    <strong className="text-ink-100">Stream Key</strong> = votre clé secrète
                    complète. Nommez la destination « STREAMCLIP », puis enregistrez (
                    <strong className="text-ink-100">Done</strong>).
                  </>
                ),
              },
              {
                title: "Activez la destination au Go Live",
                body: (
                  <>
                    Cliquez <strong className="text-ink-100">Go Live</strong>. Dans la fenêtre de
                    confirmation, cochez votre plateforme principale{" "}
                    <em>et</em> la destination STREAMCLIP, puis{" "}
                    <strong className="text-ink-100">Confirm & Go Live</strong>.
                  </>
                ),
              },
              {
                title: "Contrôlez le signal",
                body: (
                  <>
                    Revenez sur STREAMCLIP : la détection de live doit passer au vert. À la fin du
                    live, arrêtez la diffusion dans Streamlabs ; le spot s’éteint après ~5 minutes
                    sans signal RTMP.
                  </>
                ),
              },
            ]}
          />
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-ink-950/40 p-4 sm:p-5">
        <SectionTitle>Option B — Streamlabs + plugin OBS Multiple RTMP</SectionTitle>
        <p className="mt-2 text-sm leading-relaxed text-ink-300">
          Si vous ne pouvez pas ajouter une 2ᵉ destination dans Streamlabs Desktop, le plus fiable
          est d’utiliser <strong className="text-ink-100">OBS Studio</strong> avec le plugin Multiple
          RTMP Outputs (même scène, mêmes sources) : plateforme principale dans OBS + STREAMCLIP via
          le plugin.
        </p>
        <div className="mt-5">
          <ObsPluginGuide />
        </div>
      </div>

      <div className="rounded-2xl border border-dashed border-white/15 bg-ink-950/30 p-4 sm:p-5">
        <SectionTitle>Test rapide (Custom Ingest seul)</SectionTitle>
        <p className="mt-2 text-sm leading-relaxed text-ink-300">
          Pour valider uniquement STREAMCLIP sans multistream : Settings → Stream →{" "}
          <strong className="text-ink-100">Stream to Custom Ingest</strong> → Custom Streaming Server
          → collez serveur + clé → Go Live. Attention : dans ce mode, le live part{" "}
          <em>uniquement</em> vers STREAMCLIP (plus vers Twitch/YouTube tant que ce mode est actif).
        </p>
      </div>
    </div>
  );
}

export function ObsRtmpGuide({
  software,
  existingKey,
  canManage,
  ingestOnline,
  rtmpUrl,
}: {
  software: "obs" | "streamlabs";
  existingKey: StreamKey | null;
  canManage: boolean;
  ingestOnline: boolean;
  rtmpUrl: string | null;
}) {
  const isStreamlabs = software === "streamlabs";

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-brand-400/20 bg-brand-500/10 p-4 sm:p-5">
        <SectionTitle>Avant de configurer le logiciel</SectionTitle>
        <ol className="mt-3 space-y-2 text-sm leading-relaxed text-ink-200">
          <li>
            1. Créez votre clé STREAMCLIP ci-dessous et{" "}
            <strong className="text-white">copiez-la immédiatement</strong> (affichée une seule
            fois).
          </li>
          <li>
            2. Dans OBS / Streamlabs : Serveur ={" "}
            <code className="text-ink-100">{rtmpUrl ?? "rtmp://…:1935/live"}</code>, Clé = votre
            stream key. Au démarrage du live, votre instance EC2 dédiée s&apos;allume
            automatiquement.
          </li>
          <li>
            3. Suivez le guide {isStreamlabs ? "Streamlabs" : "OBS"} pour la sortie Multiple RTMP
            si vous streamez aussi vers Twitch / YouTube.
          </li>
        </ol>
      </div>

      <StreamKeyManager
        canManage={canManage}
        ingestOnline={ingestOnline}
        rtmpUrl={rtmpUrl}
        existingKey={existingKey}
        defaultLabel={isStreamlabs ? "Streamlabs" : "OBS"}
      />

      {isStreamlabs ? <StreamlabsGuide /> : <ObsPluginGuide />}
    </div>
  );
}
