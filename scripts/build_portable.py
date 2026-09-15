from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "fecap-clipping-portable.zip"
SAFE_FILES = (
    ".gitignore",
    "README.md",
    "requirements-local.txt",
    "config/people.json",
    "docs/excel-homologation-contract.md",
    "src/clipping.py",
    "src/excel_homologation.py",
    "src/json_schema_probe.py",
    "src/knewin_api.py",
    "src/knewin_collector_plan.py",
    "src/knewin_discovery.py",
    "src/knewin_runtime_validation.py",
    "src/knewin_session_collector.py",
    "src/session_auth_probe.py",
    "scripts/analyze_knewin_inventory.py",
    "scripts/build_homologation_excel.py",
    "scripts/build_portable.py",
    "scripts/collect_knewin_publications.py",
    "scripts/local_doctor.py",
    "scripts/prepare_knewin_collector.py",
    "scripts/setup_local.py",
    "scripts/probe_knewin_session.py",
    "scripts/probe_knewin_session_auto.py",
    "scripts/probe_knewin_news.py",
    "scripts/probe_knewin_news_guided.py",
    "scripts/validate_knewin_publications_runtime.py",
    "scripts/e2e_live_knewin.py",
    "tests/e2e_public_news.py",
    "tests/test_excel_homologation.py",
    "tests/test_json_schema_probe.py",
    "tests/test_knewin_api.py",
    "tests/test_knewin_auto_probe.py",
    "tests/test_knewin_collector_plan.py",
    "tests/test_knewin_discovery.py",
    "tests/test_knewin_news_probe.py",
    "tests/test_knewin_guided_probe.py",
    "tests/test_knewin_runtime_validation.py",
    "tests/test_knewin_session_collector.py",
    "tests/test_session_auth_probe.py",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_portable(output: Path, root: Path = ROOT) -> dict:
    missing = [rel for rel in SAFE_FILES if not (root / rel).is_file()]
    if missing:
        raise FileNotFoundError("arquivos obrigatórios ausentes: " + ", ".join(missing))

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "files": []}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(SAFE_FILES):
            payload = (root / rel).read_bytes()
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
            manifest["files"].append(
                {"path": rel, "size": len(payload), "sha256": sha256_bytes(payload)}
            )
        manifest_payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        info = zipfile.ZipInfo("PORTABLE-MANIFEST.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_payload)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera pacote portátil seguro da automação FECAP")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ns = parser.parse_args()
    manifest = build_portable(ns.output)
    print(json.dumps({"status": "OK", "output": str(ns.output), "files": len(manifest["files"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
