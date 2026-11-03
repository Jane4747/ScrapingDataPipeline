"""Repair copied Windows virtual environments without downloading or changing packages."""
from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path

from pip._vendor.distlib.scripts import ScriptMaker

root = Path(sys.argv[1]).resolve()
base_python = sys.executable
summary = {}
for name in ("gateway", "browser-use", "scrapegraphai", "skyvern"):
    environment = root / "envs" / name
    subprocess.run([base_python, "-m", "venv", "--without-pip", str(environment)], check=True)
    scripts = environment / "Scripts"
    maker = ScriptMaker(None, str(scripts))
    maker.executable = str(scripts / "python.exe")
    maker.clobber = True
    maker.variants = {""}
    count = 0
    for package in distributions(path=[str(environment / "Lib" / "site-packages")]):
        for entry in package.entry_points:
            if entry.group in {"console_scripts", "gui_scripts"}:
                maker.make(f"{entry.name} = {entry.value}", options={"gui": entry.group == "gui_scripts"})
                count += 1
    summary[name] = {"python": str(scripts / "python.exe"), "entry_points_rebuilt": count}
(root / "migration-runtime.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
