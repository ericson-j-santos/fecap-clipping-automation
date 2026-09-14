from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.probe_knewin_session_auto import (
    is_safe_text_fallback,
    normalize_label,
    score_navigation_label,
    score_search_attrs,
)


def main() -> int:
    assert normalize_label("  Clipping   Geral ") == "clipping geral"
    assert score_navigation_label("Busca") > score_navigation_label("Clipping") > score_navigation_label("Monitoramento") > 0
    assert score_navigation_label("Pesquisar") > score_navigation_label("Clipping")
    assert score_navigation_label("Configurações") == 0

    assert score_search_attrs({"type": "search"}) == 60
    assert score_search_attrs({"type": "text", "placeholder": "Buscar notícias"}) == 40
    assert score_search_attrs({"type": "text", "aria-label": "Pesquisar"}) == 40
    assert score_search_attrs({"type": "password", "placeholder": "Buscar"}) == 0
    assert score_search_attrs({"type": "email", "aria-label": "Pesquisar"}) == 0

    assert is_safe_text_fallback({"type": "text"}, "input") is True
    assert is_safe_text_fallback({"type": ""}, "input") is True
    assert is_safe_text_fallback({"type": "text"}, "textarea") is True
    assert is_safe_text_fallback({"type": "password"}, "input") is False
    assert is_safe_text_fallback({"type": "email"}, "input") is False
    assert is_safe_text_fallback({"type": "date"}, "input") is False

    print("knewin auto probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
