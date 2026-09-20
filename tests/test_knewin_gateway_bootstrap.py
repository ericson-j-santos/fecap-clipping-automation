from pathlib import Path

from scripts.knewin_session_bootstrap import pip_install_command, venv_python_path


def main() -> int:
    base = Path("C:/tmp/fecap")
    assert venv_python_path(base, windows=True) == base / "venv" / "Scripts/python.exe"
    assert venv_python_path(base, windows=False) == base / "venv" / "bin/python"

    online = pip_install_command("python", offline=False, wheelhouse=None)
    assert "--disable-pip-version-check" in online
    assert "--no-index" not in online
    assert online[-2] == "-r"

    wheelhouse = Path("C:/wheelhouse")
    offline = pip_install_command("python", offline=True, wheelhouse=wheelhouse)
    assert "--no-index" in offline
    assert "--find-links" in offline
    assert str(wheelhouse) in offline
    assert "--disable-pip-version-check" not in offline

    try:
        pip_install_command("python", offline=True, wheelhouse=None)
    except ValueError:
        pass
    else:
        raise AssertionError("modo offline sem wheelhouse deveria bloquear")

    print("test_knewin_gateway_bootstrap: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
