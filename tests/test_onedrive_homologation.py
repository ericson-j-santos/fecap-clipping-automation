from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.onedrive_homologation import OneDriveHomologationError, TARGET_FOLDER, publish_workbook


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        workbook = base / "input.xlsx"
        destination = base / "OneDrive" / "FECAP" / "2026"
        destination.mkdir(parents=True)
        workbook.write_bytes(b"fecap-workbook-v1")

        first = publish_workbook(workbook, destination)
        assert first["status"] == "PASS"
        assert first["action"] == "uploaded"
        assert first["scheduled"] is False
        assert first["production_enabled"] is False
        target = destination / TARGET_FOLDER / first["file_name"]
        assert target.read_bytes() == workbook.read_bytes()

        second = publish_workbook(workbook, destination)
        assert second["action"] == "already_present"
        assert second["workbook_sha256"] == first["workbook_sha256"]
        assert len(list((destination / TARGET_FOLDER).glob("*.xlsx"))) == 1

        target.write_bytes(b"different")
        try:
            publish_workbook(workbook, destination)
        except OneDriveHomologationError as exc:
            assert str(exc) == "hash_conflict"
        else:
            raise AssertionError("hash_conflict esperado")

    print("ONEDRIVE_HOMOLOGATION_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
