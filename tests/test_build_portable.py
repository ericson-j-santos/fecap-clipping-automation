from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
            required_runtime = {
                "scripts/e2e_live_knewin.py",
                "scripts/knewin_live_workbook.py",
                "tests/test_knewin_live_workbook.py",
                "docs/knewin-live-workbook-gate.md",
            }
            assert required_runtime.issubset(names), "portable runtime dependency missing"
            assert not any("evidence/private" in name for name in names)
            assert not any("knewin-profile" in name for name in names)
            stored = json.loads(archive.read("PORTABLE-MANIFEST.json"))
            assert stored == manifest
            install_dir = Path(tmp) / "installed"
            for item in stored["files"]:
                payload = archive.read(item["path"])
                assert len(payload) == item["size"]
                assert sha256(payload).hexdigest() == item["sha256"]
                rel = Path(item["path"])
                assert not rel.is_absolute() and ".." not in rel.parts
                dest = install_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)

        # Import the packaged entrypoint from a clean install OUTSIDE the repo.
        # '-I' isolates host PYTHONPATH and user site-packages.
        snippet = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import scripts.e2e_live_knewin; import scripts.knewin_live_workbook"
        )

        def isolated_import():
            return subprocess.run(
                [sys.executable, "-I", "-c", snippet, str(install_dir)],
                cwd=tmp, capture_output=True, text=True, timeout=30, check=False,
            )

        positive = isolated_import()
        assert positive.returncode == 0, "portable entrypoint cannot import cleanly"
        module = install_dir / "scripts" / "knewin_live_workbook.py"
        saved = module.read_bytes()
        module.unlink()
        negative = isolated_import()
        assert negative.returncode != 0
        assert "knewin_live_workbook" in negative.stderr
        # Restore the test mutation and independently revalidate.
        module.write_bytes(saved)
        assert isolated_import().returncode == 0
    print("test_build_portable: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
