"use client";

import { useCallback, useState } from "react";

import { StreamKeyManager } from "@/components/app/ingest-credentials";
import {
  PluginConnectStep,
  PluginDownloadStep,
  PluginInstallStep,
  PluginVerifyStep,
  StreamlabsConnectStep,
  type Creds,
} from "@/components/app/obs-rtmp-guide";
import { buttonClasses } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { cx } from "@/lib/format";
import type { StreamKey } from "@/types/api";

type Platform = "obs" | "streamlabs";
type ObsStep = "download" | "install" | "verify" | "connect";

const OBS_STEPS: { id: ObsStep; label: string }[] = [
  { id: "download", label: "Télécharger" },
  { id: "install", label: "Installer" },
  { id: "verify", label: "Vérifier" },
  { id: "connect", label: "Connecter" },
];

export function SetupTutorial({
  canManage,
  ingestOnline,
  rtmpUrl: _rtmpUrl,
  existingKey,
  timeZone,
  initialPlatform = "obs",
}: {
  canManage: boolean;
  ingestOnline: boolean;
  rtmpUrl: string | null;
  existingKey: StreamKey | null;
  timeZone: string;
  initialPlatform?: Platform;
}) {
  const [platform, setPlatform] = useState<Platform>(initialPlatform);
  const [obsStep, setObsStep] = useState<ObsStep>("download");
  const [creds, setCreds] = useState<Creds | null>(() => {
    if (existingKey?.stream_key && existingKey.rtmps_url) {
      return {
        server: existingKey.rtmps_url,
        streamKey: existingKey.stream_key,
      };
    }
    return null;
  });

  const onIssued = useCallback(
    (key: StreamKey) => {
      const server = key.rtmps_url;
      if (key.stream_key && server) {
        setCreds({ server, streamKey: key.stream_key });
      }
    },
    [],
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardTitle>Votre logiciel</CardTitle>
        <CardDescription className="mt-2">
          Choisissez OBS ou Streamlabs — le guide s’adapte. Votre live Twitch / YouTube / Kick ne
          change pas.
        </CardDescription>
        <div className="mt-5 flex flex-wrap gap-2">
          {(
            [
              { id: "obs" as const, label: "OBS Studio" },
              { id: "streamlabs" as const, label: "Streamlabs" },
            ] as const
          ).map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setPlatform(option.id)}
              className={cx(
                "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                platform === option.id
                  ? "bg-brand-500 text-white"
                  : "bg-ink-900 text-ink-300 hover:text-white",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <CardTitle>Votre clé STREAMCLIP</CardTitle>
        <CardDescription className="mt-2">
          Créez ou régénérez la clé ici. Après régénération, le secret remplace le bloc « Clé
          active » — copiez-le tout de suite.
        </CardDescription>
        <div className="mt-5">
          <StreamKeyManager
            canManage={canManage}
            ingestOnline={ingestOnline}
            rtmpUrl={_rtmpUrl}
            existingKey={existingKey}
            timeZone={timeZone}
            onIssued={onIssued}
          />
        </div>
      </Card>

      {platform === "obs" ? (
        <Card>
          <div className="flex flex-wrap gap-2 border-b border-white/10 pb-4">
            {OBS_STEPS.map((step, index) => {
              const active = step.id === obsStep;
              const done = OBS_STEPS.findIndex((s) => s.id === obsStep) > index;
              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={() => setObsStep(step.id)}
                  className={cx(
                    "rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-brand-500 text-white"
                      : done
                        ? "bg-brand-500/20 text-brand-200"
                        : "bg-ink-900 text-ink-400 hover:text-ink-200",
                  )}
                >
                  {String(index + 1).padStart(2, "0")} · {step.label}
                </button>
              );
            })}
          </div>
          <div className="mt-6">
            {obsStep === "download" ? <PluginDownloadStep /> : null}
            {obsStep === "install" ? <PluginInstallStep /> : null}
            {obsStep === "verify" ? <PluginVerifyStep /> : null}
            {obsStep === "connect" ? <PluginConnectStep creds={creds} /> : null}
          </div>
          <div className="mt-8 flex flex-wrap justify-between gap-3">
            <button
              type="button"
              className={buttonClasses({ variant: "secondary", size: "sm" })}
              disabled={obsStep === "download"}
              onClick={() => {
                const i = OBS_STEPS.findIndex((s) => s.id === obsStep);
                if (i > 0) setObsStep(OBS_STEPS[i - 1]!.id);
              }}
            >
              Précédent
            </button>
            {obsStep !== "connect" ? (
              <button
                type="button"
                className={buttonClasses({ size: "sm" })}
                onClick={() => {
                  const i = OBS_STEPS.findIndex((s) => s.id === obsStep);
                  if (i < OBS_STEPS.length - 1) setObsStep(OBS_STEPS[i + 1]!.id);
                }}
              >
                Suivant
              </button>
            ) : (
              <p className="text-sm text-ink-400">
                Lancez un live de test : STREAMCLIP détecte le flux tout seul.
              </p>
            )}
          </div>
        </Card>
      ) : (
        <Card>
          <StreamlabsConnectStep />
        </Card>
      )}
    </div>
  );
}
