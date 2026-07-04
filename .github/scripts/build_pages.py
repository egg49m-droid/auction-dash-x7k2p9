import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import dashboard, db

conn = db.connect()
rows = db.get_all(conn)
conn.close()

html_out = dashboard.render_html(rows)
password = os.environ.get("PAGES_PASSWORD")
if password:
    html_out = dashboard.wrap_with_password_gate(html_out, password)

public_dir = ROOT / "public"
public_dir.mkdir(exist_ok=True)
(public_dir / "index.html").write_text(html_out, encoding="utf-8")
print(f"public/index.html generated ({len(rows)} rows)")
