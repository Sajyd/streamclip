# Pipeline segments 5 min (per-org t4g.small)

Stack volontairement simple : **une instance spot par organisation**
`t4g.small` (`eu-north-1`) reçoit le live, enregistre, analyse, puis passe
au créneau suivant. Vercel ne fait **que** l’app web + persistance DB /
affichage dashboard — jamais FFmpeg, ASR ni Luna.

## Boucle (tout sur l’EC2)

1. OBS → RTMPS/SRT → edge → relay RTMP vers MediaMTX sur l’instance dédiée.
2. Toutes les **5 minutes**, FFmpeg enregistre un extrait HD (stream copy) :
   `tmp/lives/<session_id>/seg_XXXX.mp4` sur S3.
3. Le segment est passé à l’agent **:8080** (`POST /analyze`) qui :
   - extrait 1 frame / 5 s ;
   - transcrit les 5 minutes (ASR openai-compatible / Groq) ;
   - envoie frames + transcript à **Bedrock GPT-6 Luna** ;
   - reçoit des moments viraux 30–60 s (préférence 60), non chevauchants,
     avec timings mot à mot, score, titre, description+hashtags, et position
     cam streamer `(x,y)` sur un plan **1920×1080** si détectée.
4. L’agent POST le JSON vers `/ingest/hooks/segment-analysis` → DB :
   `media_segments` + `analysis_windows` + `highlight_candidates`.
5. Fin de live → la boucle s’arrête ; l’instance est terminée (spot / stop).

## Frontend (Vercel)

`/live` poll les highlights de la session ; `/highlights` : Player Remotion
9:16 sur l’URL présignée, sous-titres synchronisés. Si `camera.detected`,
un second viewport est centré sur `(x,y)`.

## Coûts (ordre de grandeur)

| Brique | Estimation |
| --- | --- |
| EC2 t4g.small spot | ≈ 0,003–0,008 USD/h |
| ASR Groq whisper turbo | ≈ 0,04 USD/h audio |
| Bedrock GPT-6 Luna (~60 images + texte / 5 min) | quelques centimes / h |
| S3 tmp (lifecycle short) | négligeable |

Reste largement sous la règle **infra+processing ≤ 10 % HT** des plans.
