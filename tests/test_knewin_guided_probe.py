from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.probe_knewin_news_guided import interaction_ready, is_newsstream_observation


def main() -> int:
    good = {
        "host": "news.knewin.com",
        "route_template": "/newsstream/appService",
        "status": 200,
    }
    bad_host = {"host": "example.com", "route_template": "/newsstream/appService", "status": 200}
    bad_status = {"host": "news.knewin.com", "route_template": "/newsstream/appService", "status": 500}
    assert is_newsstream_observation(good) is True
    assert is_newsstream_observation(bad_host) is False
    assert is_newsstream_observation(bad_status) is False
    assert interaction_ready(0, [good]) is False
    assert interaction_ready(1, []) is False
    assert interaction_ready(1, [bad_host]) is False
    assert interaction_ready(1, [good]) is True
    print("knewin guided probe tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
