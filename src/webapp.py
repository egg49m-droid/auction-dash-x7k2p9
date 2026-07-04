import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask
from src import dashboard, db

app = Flask(__name__)


@app.route("/")
def index():
    conn = db.connect()
    rows = db.get_all(conn)
    conn.close()
    return dashboard.render_html(rows)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8842)
