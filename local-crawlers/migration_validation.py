"""Verify the copied deployment and repair its paths, preserving pre-migration evidence."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

source = Path(r"C:\Users\Jane\.codex\.chatgpt-projects\g-p-6ad9720f1cd48191b33b188cf4398a78\work\local-crawler-stack-20261027")
destination = Path(r"E:\CAICTBigData\coding\local-crawlers")
assert destination.parent == Path(r"E:\CAICTBigData\coding")
extended_source = Path("\\\\?\\" + str(source)) if os.name == "nt" else source
missing = []
mismatched = []
count = 0
size = 0
critical_hashes = {}
for original in extended_source.rglob("*"):
    relative = original.relative_to(extended_source)
    if relative.parts[0] == "tools" or not original.is_file() or original.suffix == ".pyc":
        continue
    copied = destination / relative
    count += 1
    size += original.stat().st_size
    if not copied.is_file():
        missing.append(str(relative))
    elif copied.stat().st_size != original.stat().st_size:
        mismatched.append(str(relative))
    elif len(relative.parts) == 1 and original.suffix in {".py", ".ps1", ".txt", ".example", ".json"} or str(relative) in {".env", "firecrawl\\compose.yaml", "firecrawl\\install-docker-wsl.sh"}:
        with original.open("rb") as handle:
            before = hashlib.file_digest(handle, "sha256").hexdigest()
        with copied.open("rb") as handle:
            after = hashlib.file_digest(handle, "sha256").hexdigest()
        if before != after:
            mismatched.append(str(relative))
        critical_hashes[str(relative)] = before
if missing or mismatched:
    raise RuntimeError(json.dumps({"missing": missing, "mismatched": mismatched}))
history = destination / "migration-history" / "20261027-before-move"
history.mkdir(parents=True, exist_ok=True)
for file in destination.glob("*.json"):
    shutil.copy2(file, history / file.name)

common = destination / "common.py"
text = common.read_text(encoding="utf-8")
start = text.index("    # A junction keeps Skyvern")
end = text.index("    return path", start)
common.write_text(text[:start] + text[end:], encoding="utf-8")
installer = destination / "Install.ps1"
text = installer.read_text(encoding="utf-8")
start = text.index("    if ($taskName -eq 'skyvern') {")
end = text.index("    $taskLog =", start)
text = text[:start] + text[end:]
text = text.replace("& (Join-Path $env:USERPROFILE '.codex\\lcrawl-20261027\\envs\\skyvern\\Scripts\\python.exe')", "& (Join-Path $PSScriptRoot 'envs\\skyvern\\Scripts\\python.exe')")
installer.write_text(text, encoding="utf-8")
readme = destination / "README.txt"
text = readme.read_text(encoding="utf-8")
text = text.replace("Skyvern 的短路径入口 C:\\Users\\Jane\\.codex\\lcrawl-20261027 是指向本部署目录的目录联接；文件仍然保存在此工作目录内。", "部署代码、独立环境与配置已迁到 E:\\CAICTBigData\\coding\\local-crawlers。旧 C 盘路径保留为兼容目录联接；Codex 的新配置直接使用 E 盘路径。")
readme.write_text(text, encoding="utf-8")
subprocess.run([sys.executable, str(destination / "migrate_runtime.py"), str(destination)], check=True)
report = {"migrated_at": datetime.now(timezone.utc).isoformat(), "source": str(source), "destination": str(destination), "excluded": ["*.pyc", "tools/ (unused initial uv bootstrap)"], "copied_files_excluding_pyc": count, "copied_bytes": size, "missing_files": missing, "size_or_hash_mismatches": mismatched, "critical_file_hashes_before_path_updates": critical_hashes, "old_reports_preserved": str(history), "path_updates": ["common.py", "Install.ps1", "README.txt"], "functional_checks": "pending"}
(destination / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copy2(__file__, destination / "migration_validation.py")
print(json.dumps({"copy_verified": True, "files": count, "bytes": size, "destination": str(destination)}))
