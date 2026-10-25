"""Narrate each sentence of the approved script with Kokoro (voice am_michael); write one WAV per sentence and a
timing file. Usage: narrate.py MODELS_DIR SCENES_JSON OUT_DIR"""
import json, sys
import numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
models, scenes_path, out = sys.argv[1:4]
k = Kokoro(models + "/kokoro-v1.0.int8.onnx", models + "/voices-v1.0.bin")
scenes = json.load(open(scenes_path))
timing = []
for sc in scenes:
    for i, text in enumerate(sc["sentences"]):
        speak = text.replace("one-in-six", "one in six")
        samples, sr = k.create(speak, voice="am_michael", speed=1.06, lang="en-us")
        # trim leading/trailing near-silence
        idx = np.where(np.abs(samples) > 0.01)[0]
        samples = samples[max(idx[0] - int(0.03 * sr), 0): idx[-1] + int(0.08 * sr)]
        fn = f"{out}/s{sc['id']}_{i}.wav"
        sf.write(fn, samples, sr)
        timing.append({"scene": sc["id"], "i": i, "text": text, "file": fn, "dur": len(samples) / sr, "sr": sr})
        print(sc["id"], i, f"{len(samples)/sr:.2f}s", flush=True)
json.dump(timing, open(out + "/timing.json", "w"), indent=1)
print("total speech", round(sum(t["dur"] for t in timing), 1), "s")
