"""Verify OpenRouter model IDs exist (public endpoint, no key) and print their prices."""
import json
import sys
import urllib.request


def main() -> int:
    wanted = [m.strip() for m in sys.argv[1].split(",") if m.strip()]
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as r:
        data = json.load(r)["data"]
    by_id = {m["id"]: m for m in data}
    missing = [m for m in wanted if m not in by_id]
    for m in wanted:
        if m in by_id:
            p = by_id[m].get("pricing", {})
            print(f"OK  {m}  prompt ${float(p.get('prompt', 0)) * 1e6:.3f}/M  completion ${float(p.get('completion', 0)) * 1e6:.3f}/M")
    for m in missing:
        close = [i for i in by_id if m.split("/")[-1].split("-")[0] in i][:8]
        print(f"MISSING {m}; similar IDs: {close}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
