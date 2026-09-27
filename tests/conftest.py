"""Test quarantine: NEVER touch live SerpApi/Gemini or real files.

The app loads .env on import; tests must run fully offline against fixtures.
Snapshots go to a temp dir, not the repo.
"""
import os

os.environ["SERPAPI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""

import tempfile

_tmp = tempfile.mkdtemp(prefix="fairstart-test-")
os.environ["SNAP_PATH"] = os.path.join(_tmp, "test.sqlite")
