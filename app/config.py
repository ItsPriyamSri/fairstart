"""Central config with free-tier-safe defaults. Secrets come from the environment
or a local .env file (gitignored, never committed)."""
import os


def _load_dotenv():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


_load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
SERPAPI_BASE = "https://serpapi.com/search.json"
# Credit math per search: 1 jobs + 2 per verified company (news + presence).
# Default 2 -> max 7 SerpApi credits/search (~35 searches in the free 250/mo).
MAX_VERIFY_COMPANIES = int(os.getenv("MAX_VERIFY_COMPANIES", "2"))
SERPAPI_TIMEOUT_S = float(os.getenv("SERPAPI_TIMEOUT_S", "15"))
CACHE_TTL_S = int(os.getenv("CACHE_TTL_S", "3600"))
CACHE_PATH = os.getenv("CACHE_PATH", ".cache.sqlite")
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
