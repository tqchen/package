"""Restore a retained native SDK artifact and record the exact consumer."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

artifact = Path("artifact")
sdk = Path(subprocess.check_output([sys.executable, "-m", "mlc_llvm_static.config", "--prefix"], text=True).strip())
with zipfile.ZipFile(artifact / "patched-sdk.zip") as archive:
    archive.extractall(sdk)
evidence = json.loads((artifact / "native-evidence.json").read_text())
actual = hashlib.sha256((sdk / "lib/LLVMJITLink.lib").read_bytes()).hexdigest()
assert actual == evidence["patched_jitlink_sha256"]
evidence["validated_consumer_head"] = subprocess.check_output(["git", "-C", "consumer", "rev-parse", "HEAD"], text=True).strip()
evidence["validation_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
Path("retained-evidence.json").write_text(json.dumps(evidence, indent=2))
print(json.dumps(evidence, indent=2))
