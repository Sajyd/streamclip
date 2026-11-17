# Pipeline segments 5 min (t4g.small)

Stack volontairement simple : **une seule instance** `t4g.small` (spot,
`eu-north-1`) reçoit le live, enregistre, analyse, puis passe au créneau
suivant. Pas de flotte GPU, pas de c7g.large.

## Boucle

1. OBS → RTMPS/SRT → MediaMTX sur l’instance.
2. Toutes les **5 minutes**, FFmpeg enregistre un extrait HD (stream copy) :
   `tmp/lives/<session_id>/seg_XXXX.mp4` sur S3.
3. Sur le même créneau de 5 minutes, l’instance :
   - extrait 1 frame / 5 s en **480p** ;
   - transcrit les 5 minutes (ASR openai-compatible / Groq) ;
   - envoie frames + transcript à **Bedrock Nova Lite** (`amazon.nova-lite-v1:0`,
     alias produit « Luna ») ;
   - reçoit des moments viraux 30–60 s (préférence 60), non chevauchants,
     avec timings mot à mot, score, titre, description+hashtags, et position
     cam streamer `(x,y)` sur un plan **1920×1080** si détectée.
4. Persistance DB : `media_segments` + `analysis_windows` +
   `highlight_candidates` (JSON moments dans `score_breakdown` /
   `verification`).
5. Fin de live → la boucle s’arrête ; l’instance est terminée (spot / stop).

CLI sur l’instance :

```bash
python -m app.cli live-loop \
  --session-id <uuid> \
  --input-url rtmp://127.0.0.1/live/<public_id>
```

## Frontend

`/highlights` : Player Remotion 9:16 sur l’URL présignée de l’extrait 1080p,
un highlight par élément du tableau, sous-titres synchronisés. Si
`camera.detected`, un second viewport de la même vidéo est centré sur `(x,y)`.

## Coûts (ordre de grandeur)

| Brique | Estimation |
| --- | --- |
| EC2 t4g.small spot | ≈ 0,003–0,008 USD/h |
| ASR Groq whisper turbo | ≈ 0,04 USD/h audio |
| Bedrock Nova Lite (≈60 images + texte / 5 min) | quelques centimes / h |
| S3 tmp (lifecycle short) | négligeable |

Reste largement sous la règle **infra+processing ≤ 10 % HT** des plans.
