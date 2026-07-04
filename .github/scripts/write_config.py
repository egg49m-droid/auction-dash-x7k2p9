import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
CONFIG.mkdir(exist_ok=True)

(CONFIG / "accounts.json").write_text(os.environ["ACCOUNTS_JSON"], encoding="utf-8")
(CONFIG / "oauth_client.json").write_text(os.environ["OAUTH_CLIENT_JSON"], encoding="utf-8")
(CONFIG / "token.json").write_text(os.environ["TOKEN_JSON"], encoding="utf-8")

settings = json.loads((CONFIG / "settings.example.json").read_text(encoding="utf-8"))
settings["spreadsheet_id"] = os.environ["SPREADSHEET_ID"]
(CONFIG / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

print("config written from secrets")
