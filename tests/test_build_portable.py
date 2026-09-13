from __future__ import annotations

import importlib.util
import json
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_portable", ROOT / "scripts" / "build_portable.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "fecap.zip"
        manifest = MODULE.build_portable(output, ROOT)
        assert output.is_file()
        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            assert "PORTABLE-MANIFEST.json" in names
            assert not any("evidence/private" in name for name in names)
            assert not any("knewin-profile" in name for name in names)
            stored = json.loads(archive.read("PORTABLE-MANIFEST.json"))
            assert stored == manifest
            for item in stored["files"]:
                payload = archive.read(item["path"])
                assert len(payload) == item["size"]
                assert sha256(payload).hexdigest() == item["sha256"]
    print("test_build_portable: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
