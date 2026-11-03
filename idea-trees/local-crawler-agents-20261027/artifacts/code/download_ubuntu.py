"""Stage the Ubuntu WSL image on D:, checked against Microsoft's distribution manifest."""
import hashlib
import urllib.request
from pathlib import Path

from common import ROOT, configure_tls, now, write_json

configure_tls()
url = "https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl"
expected = "bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e"
path = Path("D:/CodexLocalCrawlers/installers/ubuntu-24.04.5-wsl-amd64.wsl")
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists() or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != expected:
    temporary = path.with_suffix(".download")
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
            digest.update(block)
            total += len(block)
            if total % (64 * 1024 * 1024) == 0:
                print(f"Ubuntu image: {total // 1024 // 1024} MiB downloaded", flush=True)
    if digest.hexdigest() != expected:
        raise RuntimeError("Ubuntu image digest does not match Microsoft's WSL distribution manifest")
    temporary.replace(path)
write_json(ROOT / "ubuntu-image.json", {"image": str(path), "source": url, "sha256": expected, "verified_at": now()})
print("Ubuntu image verified and staged on D:", flush=True)
