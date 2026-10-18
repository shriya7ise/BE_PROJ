"""
Alert engine for the Vigilance dashboard.

Storage : SQLite (BE_PROJ/data/alerts.db), standard library only.
Sources : the same company table the dashboard uses (app.routers.dashboard._load).

Two kinds of alert
  condition : a standing condition ("escalated", "score >= 90", "penalties >= $500k").
              Opens when the condition becomes true, auto-resolves when it clears,
              reopens if it returns or gets worse after being acknowledged.
  change    : something that CHANGED between two data snapshots (tier worsened,
              score jumped, new violations ...). Stays open until a person handles it
              or it expires.

Snapshots are stored whenever the underlying data changes (and at least daily), which
builds the score history shown on the alert detail.

Alert lifecycle: new -> acknowledged | snoozed | resolved -> (reopened).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import smtplib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

log = logging.getLogger("alerts")

ROOT = Path(__file__).resolve().parents[1]  # BE_PROJ/
DB_PATH = Path(os.getenv("ALERTS_DB", ROOT / "data" / "alerts.db"))

SEV_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
TIER_RANK = {"Stable": 0, "Neutral": 1, "Watchlist": 2, "Critical": 3}
OPEN_STATES = ("new", "acknowledged")
_SEV_ORDER_SQL = "CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END"

_lock = threading.RLock()
_inited = False


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _parse(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, taken_at TEXT NOT NULL, data_hash TEXT NOT NULL,
  n INTEGER NOT NULL, reason TEXT);
CREATE TABLE IF NOT EXISTS company_scores(
  snapshot_id INTEGER NOT NULL, symbol TEXT NOT NULL, name TEXT, sector TEXT, score REAL,
  tier TEXT, status TEXT, corro INTEGER, n_viol REAL, penalty REAL,
  PRIMARY KEY(snapshot_id, symbol));
CREATE INDEX IF NOT EXISTS idx_cs_symbol ON company_scores(symbol, snapshot_id);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
  rule TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT, sector TEXT, severity TEXT NOT NULL,
  title TEXT NOT NULL, detail TEXT, from_value TEXT, to_value TEXT, score REAL, tier TEXT,
  state TEXT NOT NULL DEFAULT 'new', snooze_until TEXT, note TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_reason TEXT);
CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state, severity);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE TABLE IF NOT EXISTS alert_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER NOT NULL, ts TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT, actor TEXT);
CREATE INDEX IF NOT EXISTS idx_events_alert ON alert_events(alert_id);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ran_at TEXT, snapshot_taken INTEGER, new_alerts INTEGER,
  auto_resolved INTEGER, notified TEXT, error TEXT, actor TEXT);
"""


@contextmanager
def db():
    global _inited
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _inited:
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            con.executescript(SCHEMA)
            _inited = True
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _event(con, alert_id: int, action: str, detail: str | None = None, actor: str | None = "system"):
    con.execute(
        "INSERT INTO alert_events(alert_id, ts, action, detail, actor) VALUES (?,?,?,?,?)",
        (alert_id, _iso(_now()), action, detail, actor),
    )


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "rules": {
        "escalation": {"enabled": True, "min_corroboration": 3},
        "high_score": {"enabled": True, "threshold": 90.0},
        "penalty_exposure": {"enabled": True, "threshold": 500000.0},
        "tier_change": {"enabled": True},
        "status_escalated": {"enabled": True},
        "score_jump": {"enabled": True, "delta": 5.0},
        "new_violations": {"enabled": True, "min_increase": 1},
        "penalty_increase": {"enabled": True, "min_increase": 100000.0},
    },
    "watchlist": [],
    "watchlist_only": False,
    "auto_expire_days": 30,
    "snapshot_interval_hours": 6,
    "notify": {"slack": False, "email": False, "min_severity": "high"},
}

RULE_META = {
    "escalation": {
        "kind": "condition", "label": "Multi-signal escalation",
        "description": "Several independent signal types (OSHA records, news tone, market volatility, 10-K safety language) flag the same company.",
        "fields": [{"key": "min_corroboration", "label": "Minimum signals (1-4)", "type": "int", "min": 1, "max": 4}],
    },
    "high_score": {
        "kind": "condition", "label": "High risk score",
        "description": "Composite risk score is at or above the threshold.",
        "fields": [{"key": "threshold", "label": "Score threshold (0-100)", "type": "float", "min": 0, "max": 100}],
    },
    "penalty_exposure": {
        "kind": "condition", "label": "Large OSHA penalties",
        "description": "Current OSHA penalties are at or above the threshold.",
        "fields": [{"key": "threshold", "label": "Penalty threshold (USD)", "type": "float", "min": 0, "max": 1e10}],
    },
    "tier_change": {
        "kind": "change", "label": "Risk tier worsens",
        "description": "A company moves to a higher risk tier between data snapshots.", "fields": [],
    },
    "status_escalated": {
        "kind": "change", "label": "Status becomes Escalated",
        "description": "A company newly reaches Escalated status.", "fields": [],
    },
    "score_jump": {
        "kind": "change", "label": "Score jump",
        "description": "Composite score rises by at least this many points.",
        "fields": [{"key": "delta", "label": "Minimum rise (points)", "type": "float", "min": 0.1, "max": 100}],
    },
    "new_violations": {
        "kind": "change", "label": "New OSHA violations",
        "description": "The violation count increases.",
        "fields": [{"key": "min_increase", "label": "Minimum new violations", "type": "int", "min": 1, "max": 100000}],
    },
    "penalty_increase": {
        "kind": "change", "label": "Penalties increase",
        "description": "Current penalties rise by at least this amount.",
        "fields": [{"key": "min_increase", "label": "Minimum increase (USD)", "type": "float", "min": 1, "max": 1e10}],
    },
}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = json.loads(json.dumps(base))
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _sanitize(patch: dict) -> dict:
    out: dict[str, Any] = {}
    rules_in = patch.get("rules")
    if isinstance(rules_in, dict):
        rules = {}
        for name, cfg in rules_in.items():
            base = DEFAULT_SETTINGS["rules"].get(name)
            if base is None or not isinstance(cfg, dict):
                continue
            clean: dict[str, Any] = {}
            for k, v in cfg.items():
                if k not in base:
                    continue
                try:
                    if isinstance(base[k], bool):
                        clean[k] = bool(v)
                    elif isinstance(base[k], int):
                        clean[k] = max(0, int(float(v)))
                    else:
                        clean[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    continue
            rules[name] = clean
        out["rules"] = rules
    if isinstance(patch.get("watchlist"), list):
        seen, wl = set(), []
        for s in patch["watchlist"]:
            s = str(s).strip().upper()
            if s and s not in seen:
                seen.add(s)
                wl.append(s)
        out["watchlist"] = wl
    if "watchlist_only" in patch:
        out["watchlist_only"] = bool(patch["watchlist_only"])
    for key, lo, hi in (("auto_expire_days", 1, 365), ("snapshot_interval_hours", 1, 168)):
        if key in patch:
            try:
                out[key] = min(hi, max(lo, int(float(patch[key]))))
            except (TypeError, ValueError):
                pass
    nt = patch.get("notify")
    if isinstance(nt, dict):
        n: dict[str, Any] = {}
        for k in ("slack", "email"):
            if k in nt:
                n[k] = bool(nt[k])
        if nt.get("min_severity") in SEV_RANK:
            n["min_severity"] = nt["min_severity"]
        out["notify"] = n
    return out


def get_settings() -> dict:
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='main'").fetchone()
    stored = json.loads(row["value"]) if row else {}
    return _deep_merge(DEFAULT_SETTINGS, stored)


def save_settings(patch: dict) -> dict:
    with _lock:
        new = _deep_merge(get_settings(), _sanitize(patch or {}))
        with db() as con:
            con.execute(
                "INSERT INTO settings(key, value) VALUES('main', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(new),),
            )
    return new


def channels_configured() -> dict:
    email_vars = ("SMTP_HOST", "ALERT_EMAIL_TO")
    return {
        "slack": bool(os.getenv("ALERT_SLACK_WEBHOOK")),
        "email": all(os.getenv(v) for v in email_vars),
    }


# ---------------------------------------------------------------------------
# data source
# ---------------------------------------------------------------------------
def _fetch_rows() -> list[dict]:
    """Current company table (same data the dashboard shows)."""
    from app.routers.dashboard import _load

    df = _load()
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "symbol": str(r["symbol"]),
                "name": str(r["canonical_name"]),
                "sector": str(r["gics_sector"]),
                "score": float(r["composite_score"]),
                "tier": str(r["risk_tier"]),
                "status": str(r["status"]),
                "corro": int(r["corroboration_count"]),
                "n_viol": float(r["n_violations"] or 0),
                "penalty": float(r["total_current_penalty"] or 0),
                "n_insp": float(r.get("n_inspections", 0) or 0),
            }
        )
    return rows


def _reload_sources():
    try:
        from app.routers import dashboard

        dashboard._load.cache_clear()
    except Exception as e:  # pragma: no cover
        log.warning("could not clear dashboard cache: %r", e)


def _hash(rows: list[dict]) -> str:
    key = [
        [r["symbol"], round(r["score"], 1), r["tier"], r["status"], r["corro"], r["n_viol"], round(r["penalty"])]
        for r in sorted(rows, key=lambda r: r["symbol"])
    ]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()


# ---------------------------------------------------------------------------
# rule evaluation
# ---------------------------------------------------------------------------
def _money(v: float) -> str:
    return f"${v:,.0f}"


def _in_scope(sym: str, st: dict) -> bool:
    return (not st["watchlist_only"]) or sym in st["watchlist"]


def condition_specs(rows: list[dict], st: dict) -> dict[str, dict]:
    rules = st["rules"]
    out: dict[str, dict] = {}
    for r in rows:
        sym = r["symbol"]
        if not _in_scope(sym, st):
            continue
        base = {"symbol": sym, "name": r["name"], "sector": r["sector"], "score": r["score"],
                "tier": r["tier"], "kind": "condition"}

        rl = rules["escalation"]
        if rl["enabled"] and r["corro"] >= rl["min_corroboration"]:
            sev = "critical" if r["corro"] >= 4 else "high" if r["corro"] >= 3 else "medium"
            out[f"{sym}|escalation"] = {
                **base, "rule": "escalation", "severity": sev,
                "title": f"{r['name']}: {r['corro']} of 4 risk signals are flagging",
                "detail": (f"{r['corro']} independent signal types (OSHA records, negative news tone, market "
                           f"volatility, 10-K safety language) point at {r['name']}. Status: {r['status']}."),
                "from_value": None, "to_value": f"{r['corro']} signals",
            }

        rl = rules["high_score"]
        if rl["enabled"] and r["score"] >= rl["threshold"]:
            sev = "critical" if r["score"] >= 98 else "high" if r["score"] >= 95 else "medium"
            out[f"{sym}|high_score"] = {
                **base, "rule": "high_score", "severity": sev,
                "title": f"{r['name']}: risk score {r['score']:.1f} ({r['tier']})",
                "detail": (f"Composite score {r['score']:.1f} is at or above your threshold of "
                           f"{rl['threshold']:.0f}. This is a heuristic estimate built from OSHA penalties and violation counts."),
                "from_value": None, "to_value": f"{r['score']:.1f}",
            }

        rl = rules["penalty_exposure"]
        if rl["enabled"] and r["penalty"] >= rl["threshold"] > 0:
            ratio = r["penalty"] / rl["threshold"]
            sev = "critical" if ratio >= 5 else "high" if ratio >= 2 else "medium"
            out[f"{sym}|penalty_exposure"] = {
                **base, "rule": "penalty_exposure", "severity": sev,
                "title": f"{r['name']}: {_money(r['penalty'])} in current OSHA penalties",
                "detail": f"{r['n_viol']:.0f} violations across {r['n_insp']:.0f} inspections.",
                "from_value": None, "to_value": _money(r["penalty"]),
            }
    return out


def change_specs(rows: list[dict], prev: dict[str, dict], st: dict) -> list[dict]:
    rules = st["rules"]
    out: list[dict] = []
    for r in rows:
        sym = r["symbol"]
        p = prev.get(sym)
        if not p or not _in_scope(sym, st):
            continue
        base = {"symbol": sym, "name": r["name"], "sector": r["sector"], "score": r["score"],
                "tier": r["tier"], "kind": "change"}

        rl = rules["tier_change"]
        if rl["enabled"] and TIER_RANK.get(r["tier"], 0) > TIER_RANK.get(p["tier"], 0):
            gap = TIER_RANK[r["tier"]] - TIER_RANK[p["tier"]]
            sev = "critical" if (r["tier"] == "Critical" and gap >= 2) else "high" if r["tier"] == "Critical" else "medium" if r["tier"] == "Watchlist" else "low"
            out.append({**base, "rule": "tier_change", "severity": sev,
                        "title": f"{r['name']} moved {p['tier']} → {r['tier']}",
                        "detail": f"Score {p['score']:.1f} → {r['score']:.1f}.",
                        "from_value": p["tier"], "to_value": r["tier"]})

        rl = rules["status_escalated"]
        if rl["enabled"] and r["status"] == "Escalated" and p["status"] != "Escalated":
            out.append({**base, "rule": "status_escalated", "severity": "high",
                        "title": f"{r['name']} is newly Escalated",
                        "detail": f"Status changed {p['status']} → Escalated ({r['corro']} signals now agree).",
                        "from_value": p["status"], "to_value": "Escalated"})

        rl = rules["score_jump"]
        d = r["score"] - p["score"]
        if rl["enabled"] and d >= rl["delta"]:
            sev = "high" if d >= 20 else "medium" if d >= 10 else "low"
            out.append({**base, "rule": "score_jump", "severity": sev,
                        "title": f"{r['name']} score rose {d:.1f} points",
                        "detail": f"{p['score']:.1f} → {r['score']:.1f}.",
                        "from_value": f"{p['score']:.1f}", "to_value": f"{r['score']:.1f}"})

        rl = rules["new_violations"]
        dv = r["n_viol"] - p["n_viol"]
        if rl["enabled"] and dv >= max(1, rl["min_increase"]):
            sev = "high" if dv >= 10 else "medium" if dv >= 3 else "low"
            out.append({**base, "rule": "new_violations", "severity": sev,
                        "title": f"{r['name']}: {dv:.0f} new OSHA violation(s)",
                        "detail": f"Violations {p['n_viol']:.0f} → {r['n_viol']:.0f}.",
                        "from_value": f"{p['n_viol']:.0f}", "to_value": f"{r['n_viol']:.0f}"})

        rl = rules["penalty_increase"]
        dp = r["penalty"] - p["penalty"]
        if rl["enabled"] and dp >= max(1.0, rl["min_increase"]):
            sev = "high" if dp >= 1_000_000 else "medium"
            out.append({**base, "rule": "penalty_increase", "severity": sev,
                        "title": f"{r['name']}: penalties up {_money(dp)}",
                        "detail": f"{_money(p['penalty'])} → {_money(r['penalty'])}.",
                        "from_value": _money(p["penalty"]), "to_value": _money(r["penalty"])})
    return out


# ---------------------------------------------------------------------------
# reconcile specs with stored alerts (the lifecycle)
# ---------------------------------------------------------------------------
def _insert(con, key: str, s: dict, ts: str) -> int:
    cur = con.execute(
        """INSERT INTO alerts(key, kind, rule, symbol, name, sector, severity, title, detail, from_value,
           to_value, score, tier, state, first_seen, last_seen, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?,?,?)""",
        (key, s["kind"], s["rule"], s["symbol"], s["name"], s["sector"], s["severity"], s["title"],
         s["detail"], s["from_value"], s["to_value"], s["score"], s["tier"], ts, ts, ts),
    )
    _event(con, cur.lastrowid, "created", s["title"])
    return cur.lastrowid


def expire_snoozes(con, ts: str) -> int:
    rows = con.execute("SELECT id FROM alerts WHERE state='snoozed' AND snooze_until IS NOT NULL AND snooze_until <= ?", (ts,)).fetchall()
    for r in rows:
        con.execute("UPDATE alerts SET state='new', snooze_until=NULL, updated_at=? WHERE id=?", (ts, r["id"]))
        _event(con, r["id"], "snooze_ended", "Snooze period ended")
    return len(rows)


def _reconcile(con, cond: dict[str, dict], changes: list[dict], st: dict, ts: str) -> tuple[list[dict], int]:
    new_alerts: list[dict] = []
    auto_resolved = 0
    existing = {r["key"]: dict(r) for r in con.execute("SELECT * FROM alerts")}

    for key, s in cond.items():
        ex = existing.get(key)
        if not ex:
            aid = _insert(con, key, s, ts)
            new_alerts.append({**s, "id": aid, "key": key})
            continue
        reopen, why = False, None
        if ex["state"] == "resolved":
            reopen, why = True, "reopened"
        elif SEV_RANK[s["severity"]] > SEV_RANK[ex["severity"]] and ex["state"] in ("acknowledged", "snoozed"):
            reopen, why = True, "severity_increased"
        if reopen:
            con.execute(
                """UPDATE alerts SET severity=?, title=?, detail=?, to_value=?, score=?, tier=?, name=?, sector=?,
                   last_seen=?, updated_at=?, state='new', snooze_until=NULL, resolved_reason=NULL WHERE id=?""",
                (s["severity"], s["title"], s["detail"], s["to_value"], s["score"], s["tier"], s["name"], s["sector"], ts, ts, ex["id"]),
            )
            _event(con, ex["id"], why, s["title"])
            new_alerts.append({**s, "id": ex["id"], "key": key})
        else:
            con.execute(
                """UPDATE alerts SET severity=?, title=?, detail=?, to_value=?, score=?, tier=?, name=?, sector=?,
                   last_seen=? WHERE id=?""",
                (s["severity"], s["title"], s["detail"], s["to_value"], s["score"], s["tier"], s["name"], s["sector"], ts, ex["id"]),
            )

    for key, ex in existing.items():
        if ex["kind"] == "condition" and ex["state"] != "resolved" and key not in cond:
            con.execute(
                "UPDATE alerts SET state='resolved', resolved_reason='condition no longer met', snooze_until=NULL, updated_at=? WHERE id=?",
                (ts, ex["id"]),
            )
            _event(con, ex["id"], "auto_resolved", "Condition no longer met (or rule disabled / out of scope)")
            auto_resolved += 1

    for s in changes:
        key = f"{s['symbol']}|{s['rule']}"
        ex = existing.get(key)
        if not ex:
            aid = _insert(con, key, s, ts)
            existing[key] = {"id": aid}
            new_alerts.append({**s, "id": aid, "key": key})
        else:
            con.execute(
                """UPDATE alerts SET severity=?, title=?, detail=?, from_value=?, to_value=?, score=?, tier=?, name=?, sector=?,
                   last_seen=?, updated_at=?, state='new', snooze_until=NULL, resolved_reason=NULL WHERE id=?""",
                (s["severity"], s["title"], s["detail"], s["from_value"], s["to_value"], s["score"], s["tier"], s["name"], s["sector"], ts, ts, ex["id"]),
            )
            _event(con, ex["id"], "changed", s["title"])
            new_alerts.append({**s, "id": ex["id"], "key": key})

    if st["watchlist_only"]:
        watch = set(st["watchlist"])
        for ex in existing.values():
            if ex.get("state") and ex["state"] != "resolved" and ex.get("symbol") not in watch:
                con.execute(
                    "UPDATE alerts SET state='resolved', resolved_reason='outside watchlist', snooze_until=NULL, updated_at=? WHERE id=?",
                    (ts, ex["id"]),
                )
                _event(con, ex["id"], "auto_resolved", "Company is not on the watchlist (watchlist-only mode)")
                auto_resolved += 1

    cutoff = _iso(_parse(ts) - timedelta(days=st["auto_expire_days"]))
    for r in con.execute(
        "SELECT id FROM alerts WHERE kind='change' AND state IN ('new','acknowledged') AND last_seen < ?", (cutoff,)
    ).fetchall():
        con.execute("UPDATE alerts SET state='resolved', resolved_reason='expired', updated_at=? WHERE id=?", (ts, r["id"]))
        _event(con, r["id"], "expired", f"No new activity for {st['auto_expire_days']} days")
        auto_resolved += 1
    return new_alerts, auto_resolved


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------
_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}


def _format(items: list[dict]) -> tuple[str, str]:
    base = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
    subject = f"Vigilance: {len(items)} new alert(s)"
    lines = [subject, ""]
    for a in items[:15]:
        lines.append(f"{_ICON[a['severity']]} [{a['severity'].upper()}] {a['symbol']}: {a['title']}")
        lines.append(f"   {base}/alerts?alert={a['id']}")
    if len(items) > 15:
        lines.append(f"...and {len(items) - 15} more.")
    return subject, "\n".join(lines)


def _slack(text: str) -> str:
    url = os.getenv("ALERT_SLACK_WEBHOOK")
    if not url:
        return "not configured (set ALERT_SLACK_WEBHOOK)"
    try:
        import requests

        r = requests.post(url, json={"text": text}, timeout=10)
        return "sent" if r.ok else f"failed: HTTP {r.status_code}"
    except Exception as e:
        return f"failed: {e}"


def _email(subject: str, body: str) -> str:
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if not host or not to:
        return "not configured (set SMTP_HOST and ALERT_EMAIL_TO)"
    try:
        msg = EmailMessage()
        msg["Subject"], msg["To"] = subject, to
        msg["From"] = os.getenv("ALERT_EMAIL_FROM") or os.getenv("SMTP_USER") or "vigilance@localhost"
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
            try:
                s.starttls()
            except smtplib.SMTPException:
                pass
            if os.getenv("SMTP_USER"):
                s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return "sent"
    except Exception as e:
        return f"failed: {e}"


def notify(new_alerts: list[dict], st: dict, force_text: str | None = None) -> dict:
    cfg = st["notify"]
    min_rank = SEV_RANK[cfg["min_severity"]]
    items = sorted([a for a in new_alerts if SEV_RANK[a["severity"]] >= min_rank], key=lambda a: -SEV_RANK[a["severity"]])
    if not items and not force_text:
        return {"alerts": 0}
    subject, body = (("Vigilance test", force_text) if force_text else _format(items))
    res: dict[str, Any] = {"alerts": len(items)}
    if cfg["slack"] or force_text:
        res["slack"] = _slack(body)
    if cfg["email"] or force_text:
        res["email"] = _email(subject, body)
    return res


# ---------------------------------------------------------------------------
# the cycle
# ---------------------------------------------------------------------------
def run_cycle(force_snapshot: bool = False, reload_data: bool = False, actor: str = "scheduler") -> dict:
    with _lock:
        ts_dt = _now()
        ts = _iso(ts_dt)
        result: dict[str, Any] = {"ran_at": ts, "snapshot_taken": False, "new_alerts": 0, "auto_resolved": 0,
                                  "data_changed": False, "notified": {}, "error": None}
        new_alerts: list[dict] = []
        st = None
        try:
            if reload_data:
                _reload_sources()
            rows = _fetch_rows()
            if not rows:
                raise RuntimeError("company table is empty; refusing to change any alerts")
            st = get_settings()
            h = _hash(rows)
            with db() as con:
                last = con.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                changed = last is None or last["data_hash"] != h
                stale = last is not None and (ts_dt - _parse(last["taken_at"])) >= timedelta(hours=24)
                prev_map: dict[str, dict] = {}
                if last is not None and changed:
                    prev_map = {r["symbol"]: dict(r) for r in con.execute("SELECT * FROM company_scores WHERE snapshot_id=?", (last["id"],))}
                if last is None or changed or stale or force_snapshot:
                    reason = "baseline" if last is None else "data changed" if changed else "manual" if force_snapshot else "daily heartbeat"
                    sid = con.execute("INSERT INTO snapshots(taken_at, data_hash, n, reason) VALUES (?,?,?,?)", (ts, h, len(rows), reason)).lastrowid
                    con.executemany(
                        "INSERT INTO company_scores(snapshot_id, symbol, name, sector, score, tier, status, corro, n_viol, penalty) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(sid, r["symbol"], r["name"], r["sector"], r["score"], r["tier"], r["status"], r["corro"], r["n_viol"], r["penalty"]) for r in rows],
                    )
                    result["snapshot_taken"] = True
                result["data_changed"] = bool(last is not None and changed)

                expire_snoozes(con, ts)
                cond = condition_specs(rows, st)
                chg = change_specs(rows, prev_map, st) if prev_map else []
                new_alerts, auto_resolved = _reconcile(con, cond, chg, st, ts)
                result["new_alerts"], result["auto_resolved"] = len(new_alerts), auto_resolved
        except Exception as e:
            log.exception("alert cycle failed")
            result["error"] = str(e)

        if new_alerts and st:
            try:
                result["notified"] = notify(new_alerts, st)
            except Exception as e:  # never let notifications break the cycle
                result["notified"] = {"error": str(e)}

        try:
            with db() as con:
                con.execute(
                    "INSERT INTO runs(ran_at, snapshot_taken, new_alerts, auto_resolved, notified, error, actor) VALUES (?,?,?,?,?,?,?)",
                    (ts, int(result["snapshot_taken"]), result["new_alerts"], result["auto_resolved"], json.dumps(result["notified"]), result["error"], actor),
                )
        except Exception:
            pass
        return result


# ---------------------------------------------------------------------------
# queries used by the API
# ---------------------------------------------------------------------------
def _alert_dict(r: sqlite3.Row, watch: set[str]) -> dict:
    d = dict(r)
    d["watched"] = d["symbol"] in watch
    return d


def _where(f: dict, st: dict) -> tuple[str, list]:
    cl: list[str] = []
    pr: list[Any] = []
    s = f.get("state") or "open"
    if s == "open":
        cl.append("state IN ('new','acknowledged')")
    elif s != "all":
        cl.append("state=?")
        pr.append(s)
    sevs = [x for x in (f.get("severity") or "").split(",") if x in SEV_RANK]
    if sevs:
        cl.append(f"severity IN ({','.join('?' * len(sevs))})")
        pr += sevs
    for col in ("rule", "sector", "symbol"):
        if f.get(col):
            cl.append(f"{col}=?")
            pr.append(f[col].upper() if col == "symbol" else f[col])
    if f.get("q"):
        like = f"%{f['q'].strip()}%"
        cl.append("(symbol LIKE ? OR name LIKE ? OR title LIKE ?)")
        pr += [like, like, like]
    if f.get("watchlist"):
        wl = st["watchlist"]
        if wl:
            cl.append(f"symbol IN ({','.join('?' * len(wl))})")
            pr += wl
        else:
            cl.append("1=0")
    return (" WHERE " + " AND ".join(cl)) if cl else "", pr


def _order(sort: str | None) -> str:
    if sort == "recent":
        return "updated_at DESC, id DESC"
    if sort == "score":
        return "score DESC, id DESC"
    return f"{_SEV_ORDER_SQL} DESC, score DESC, last_seen DESC"


def list_alerts(f: dict, page: int = 1, page_size: int = 25) -> dict:
    st = get_settings()
    watch = set(st["watchlist"])
    with db() as con:
        expire_snoozes(con, _iso(_now()))
        where, pr = _where(f, st)
        total = con.execute(f"SELECT COUNT(*) c FROM alerts{where}", pr).fetchone()["c"]
        rows = con.execute(
            f"SELECT * FROM alerts{where} ORDER BY {_order(f.get('sort'))} LIMIT ? OFFSET ?",
            pr + [page_size, (page - 1) * page_size],
        ).fetchall()
        open_where = " WHERE state IN ('new','acknowledged')"
        facets = {
            "rules": [r[0] for r in con.execute(f"SELECT DISTINCT rule FROM alerts{open_where} ORDER BY rule")],
            "sectors": [r[0] for r in con.execute(f"SELECT DISTINCT sector FROM alerts{open_where} AND sector IS NOT NULL ORDER BY sector")],
        }
    return {"results": [_alert_dict(r, watch) for r in rows], "total": total, "page": page, "page_size": page_size, "facets": facets}


def export_csv(f: dict) -> str:
    st = get_settings()
    with db() as con:
        where, pr = _where(f, st)
        rows = con.execute(f"SELECT * FROM alerts{where} ORDER BY {_order(f.get('sort'))}", pr).fetchall()
    buf = io.StringIO()
    cols = ["id", "severity", "state", "symbol", "name", "sector", "rule", "kind", "title", "detail", "from_value", "to_value", "score", "tier", "first_seen", "last_seen", "snooze_until", "note"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()


def history(symbol: str) -> list[dict]:
    with db() as con:
        rows = con.execute(
            """SELECT s.taken_at AS t, c.score, c.tier, c.status, c.corro, c.n_viol, c.penalty
               FROM company_scores c JOIN snapshots s ON s.id = c.snapshot_id
               WHERE c.symbol=? ORDER BY s.id""",
            (symbol.upper(),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_alert(aid: int) -> dict | None:
    st = get_settings()
    with db() as con:
        r = con.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
        if not r:
            return None
        events = [dict(e) for e in con.execute("SELECT ts, action, detail, actor FROM alert_events WHERE alert_id=? ORDER BY id DESC", (aid,))]
        last = con.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        ctx = None
        if last:
            snap = [dict(x) for x in con.execute("SELECT * FROM company_scores WHERE snapshot_id=? ORDER BY score DESC, symbol", (last["id"],))]
            me = next((x for x in snap if x["symbol"] == r["symbol"]), None)
            if me:
                peers = [x["score"] for x in snap if x["sector"] == me["sector"]]
                ctx = {**me, "rank": [x["symbol"] for x in snap].index(me["symbol"]) + 1, "of": len(snap),
                       "sector_avg_score": round(sum(peers) / len(peers), 1) if peers else None, "sector_size": len(peers)}
    return {"alert": _alert_dict(r, set(st["watchlist"])), "events": events, "history": history(r["symbol"]), "context": ctx}


def act(aid: int, action: str, actor: str = "analyst", days: int = 7, note: str | None = None) -> dict:
    ts_dt = _now()
    ts = _iso(ts_dt)
    with _lock, db() as con:
        ex = con.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
        if not ex:
            raise KeyError(aid)
        note = (note or "").strip() or None
        if action == "ack":
            con.execute("UPDATE alerts SET state='acknowledged', snooze_until=NULL, updated_at=? WHERE id=?", (ts, aid))
            _event(con, aid, "acknowledged", note, actor)
        elif action == "snooze":
            days = max(1, min(int(days), 365))
            until = _iso(ts_dt + timedelta(days=days))
            con.execute("UPDATE alerts SET state='snoozed', snooze_until=?, updated_at=? WHERE id=?", (until, ts, aid))
            _event(con, aid, "snoozed", f"for {days} day(s)" + (f": {note}" if note else ""), actor)
        elif action == "resolve":
            con.execute("UPDATE alerts SET state='resolved', resolved_reason='manually resolved', snooze_until=NULL, updated_at=? WHERE id=?", (ts, aid))
            _event(con, aid, "resolved", note, actor)
        elif action == "reopen":
            con.execute("UPDATE alerts SET state='new', snooze_until=NULL, resolved_reason=NULL, updated_at=? WHERE id=?", (ts, aid))
            _event(con, aid, "reopened", note, actor)
        elif action == "note":
            if not note:
                raise ValueError("note text is required")
            con.execute("UPDATE alerts SET note=?, updated_at=? WHERE id=?", (note, ts, aid))
            _event(con, aid, "note", note, actor)
            note = None
        else:
            raise ValueError(f"unknown action {action!r}")
        if note and action != "note":
            con.execute("UPDATE alerts SET note=? WHERE id=?", (note, aid))
    return get_alert(aid)


def summary() -> dict:
    with db() as con:
        expire_snoozes(con, _iso(_now()))
        by_state = {r["state"]: r["c"] for r in con.execute("SELECT state, COUNT(*) c FROM alerts GROUP BY state")}
        by_sev = {r["severity"]: r["c"] for r in con.execute("SELECT severity, COUNT(*) c FROM alerts WHERE state IN ('new','acknowledged') GROUP BY severity")}
        snaps = con.execute("SELECT COUNT(*) c, MIN(taken_at) first, MAX(taken_at) last FROM snapshots").fetchone()
        run = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    new_n, ack_n = by_state.get("new", 0), by_state.get("acknowledged", 0)
    return {
        "open": new_n + ack_n, "new": new_n, "acknowledged": ack_n,
        "snoozed": by_state.get("snoozed", 0), "resolved": by_state.get("resolved", 0),
        "by_severity": {k: by_sev.get(k, 0) for k in ("critical", "high", "medium", "low")},
        "snapshots": snaps["c"], "first_snapshot_at": snaps["first"], "last_snapshot_at": snaps["last"],
        "baseline_only": snaps["c"] <= 1,
        "last_run": dict(run) if run else None,
        "channels": channels_configured(),
    }


def open_alerts_brief(limit: int = 10, symbol: str | None = None) -> dict | None:
    """Compact view of open alerts for the AI chat context."""
    try:
        with db() as con:
            if symbol:
                rows = con.execute(
                    f"SELECT * FROM alerts WHERE state IN ('new','acknowledged') AND symbol=? ORDER BY {_SEV_ORDER_SQL} DESC LIMIT ?",
                    (symbol.upper(), limit),
                ).fetchall()
            else:
                rows = con.execute(
                    f"SELECT * FROM alerts WHERE state IN ('new','acknowledged') ORDER BY {_SEV_ORDER_SQL} DESC, score DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            sev = {r["severity"]: r["c"] for r in con.execute("SELECT severity, COUNT(*) c FROM alerts WHERE state IN ('new','acknowledged') GROUP BY severity")}
        return {
            "open_alerts_by_severity": sev,
            "alerts": [{k: r[k] for k in ("id", "symbol", "name", "severity", "rule", "title", "detail", "state", "first_seen")} for r in rows],
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------
_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.warning("APScheduler not installed: alerts will only update when /api/alerts/refresh is called")
        return
    hours = get_settings()["snapshot_interval_hours"]
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_cycle, "interval", hours=hours, id="alerts_cycle", max_instances=1, coalesce=True,
        next_run_time=_now() + timedelta(seconds=5),
    )
    _scheduler.start()


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reschedule():
    if _scheduler is not None:
        _scheduler.reschedule_job("alerts_cycle", trigger="interval", hours=get_settings()["snapshot_interval_hours"])