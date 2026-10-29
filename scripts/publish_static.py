"""Copy the offline run's results, figures and report into public/ for the dashboard."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT, PUB = ROOT / "outputs", ROOT / "public"


def main():
    (PUB / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT / "data" / "results.json", PUB / "data" / "results.json")
    for name in ("g1_ranked.csv", "g2_ranked.csv"):
        if (OUT / "data" / name).exists():
            shutil.copy2(OUT / "data" / name, PUB / "data" / name)
    if (PUB / "figures").exists():
        shutil.rmtree(PUB / "figures")
    shutil.copytree(OUT / "figures", PUB / "figures")
    shutil.copy2(OUT / "REPORT.md", PUB / "report.md")
    size = sum(p.stat().st_size for p in PUB.rglob("*") if p.is_file())
    print(f"published static files to {PUB} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
