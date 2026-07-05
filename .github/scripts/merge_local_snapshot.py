import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import db

snapshot_path = ROOT / "data" / "local_snapshot.json"
if not snapshot_path.exists():
    print("local_snapshot.json がないためマージをスキップします。")
    sys.exit(0)

rows = json.loads(snapshot_path.read_text(encoding="utf-8"))
conn = db.connect()
for row in rows:
    db.upsert_snapshot(conn, row)
conn.commit()
conn.close()
print(f"ローカルスナップショット{len(rows)}件をマージしました。")
