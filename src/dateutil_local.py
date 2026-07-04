import re

_DATE_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


def normalize_date(value) -> str:
    """'2026/7/2' や '2026/07/02' などの表記ゆれを 'YYYY/MM/DD' に統一する。"""
    if value is None:
        return None
    s = str(value).strip()
    m = _DATE_RE.match(s)
    if not m:
        return s
    y, mo, d = m.groups()
    return f"{y}/{int(mo):02d}/{int(d):02d}"
