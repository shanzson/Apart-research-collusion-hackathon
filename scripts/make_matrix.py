"""Emit a GitHub Actions matrix: one job per (subject model, shard of seeds)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sting.run import parse_seeds, slug  # noqa: E402


def main() -> None:
    subjects = [m.strip() for m in os.environ["SUBJECTS"].split(",") if m.strip()]
    seeds = parse_seeds(os.environ["SEEDS"])
    per = max(1, int(os.environ.get("PER_JOB", "4")))
    include = []
    for model in subjects:
        for i in range(0, len(seeds), per):
            chunk = seeds[i:i + per]
            include.append({"model": model, "slug": slug(model), "shard": i // per,
                            "seeds": ",".join(str(s) for s in chunk)})
    if len(include) > 256:
        raise SystemExit("matrix too large; raise seeds_per_job")
    print("matrix=" + json.dumps(include))


if __name__ == "__main__":
    main()
