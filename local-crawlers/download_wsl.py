"""Download the Microsoft-published WSL MSI and verify its GitHub release digest."""
import hashlib
import urllib.request

from common import ROOT, configure_tls

configure_tls()
url = "https://github.com/microsoft/WSL/releases/download/3.0.3/wsl.3.0.3.0.x64.msi"
expected = "ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211"
path = ROOT / "installers" / "wsl.3.0.3.0.x64.msi"
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists() and hashlib.file_digest(path.open("rb"), "sha256").hexdigest() == expected:
    print("WSL installer already verified", flush=True)
else:
    temporary = path.with_suffix(".download")
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while block := response.read(1024 * 1024):
            digest.update(block)
            output.write(block)
            total += len(block)
            if total % (64 * 1024 * 1024) == 0:
                print(f"Downloaded {total // 1024 // 1024} MiB", flush=True)
    if digest.hexdigest() != expected:
        raise RuntimeError("The WSL installer digest does not match Microsoft's release metadata")
    temporary.replace(path)
    print("WSL installer verified: " + str(path), flush=True)
