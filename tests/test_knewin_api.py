from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knewin_api import KnewinApiError, split_windows, to_news

start = datetime(2026, 8, 1, tzinfo=timezone.utc)
end = datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc)
windows = split_windows(start, end)

assert len(windows) == 3
assert all((window_end - window_start).days <= 14 for window_start, window_end in windows)
assert windows[0][0] == start
assert windows[-1][1] == end

sample = {
    "id": 123,
    "titulo": "FECAP comenta cenário econômico",
    "resumo": "Resumo",
    "texto": "Professor da FECAP comenta o tema.",
    "data_publicacao": "2026-08-31T12:00:00Z",
    "url_original": "https://example.org/noticia",
    "veiculo": {"nome": "Veículo Exemplo", "tier": "2"},
}
news = to_news(sample)
assert news.external_id == "123"
assert news.candidate.source == "Veículo Exemplo"
assert news.tier == 2

invalid = dict(sample)
invalid["url_original"] = ""
try:
    to_news(invalid)
except KnewinApiError:
    pass
else:
    raise AssertionError("notícia incompleta deveria falhar fechada")

print("knewin_api_contract=PASS")
