# Explainer video (about 2 minutes)

`explainer.mp4` (1920x1080, 30 fps, H.264 + AAC, about 2:06) explains Studies 1-3 in simple 2D animation with a
narrator and captions. The narration follows the approved script `explainer_script.md` word for word; every number on
screen comes from `report/submission/SUBMISSION.md`.

How it was made (offline, no paid services):
1. `narrate.py` turns each sentence of `scenes.json` into speech with the open Kokoro TTS model (voice `am_michael`,
   speed 1.06; model files from the kokoro-onnx GitHub release) and records the timing.
2. `render.py VIDEO_DIR OUT.mp4` draws every frame with Pillow (2x supersampled), mixes the narration with two soft
   synthesised sound effects, and encodes with ffmpeg; `--preview T1 T2 ...` writes single frames for checking.
3. The narration was loudness-normalised to -16 LUFS with ffmpeg `loudnorm`.
