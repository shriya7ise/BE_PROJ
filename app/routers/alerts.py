"""
Alerts API (mounted under /api by main.py)

  GET    /api/alerts                    list + filter   ?state=open|new|acknowledged|snoozed|resolved|all
                                                        &severity=critical,high &rule= &sector= &symbol= &q=
                                                        &watchlist=true &sort=severity|recent|score &page= &page_size=
  GET    /api/alerts/summary            counts for cards + sidebar badge
  GET    /api/alerts/{id}               alert + timeline + score history + context
  POST   /api/alerts/{id}/action        {action: ack|snooze|resolve|reopen|note, days?, note?, actor?}
  POST   /api/alerts/bulk               {ids: [...], action, days?}
  GET    /api/alerts/settings           rules, watchlist, notification settings
  PUT    /api/alerts/settings           partial update (re-evaluates immediately)
  POST   /api/alerts/refresh            {reload: true} re-read the data files, snapshot, re-evaluate
  POST   /api/alerts/notify/test        send a test message to the enabled channels
  GET    /api/alerts/export.csv         same filters as the list
  GET    /api/alerts/history/{symbol}   score history from stored snapshots
"""
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import alerts_engine as E

router = APIRouter(prefix="/alerts", tags=["alerts"])


class ActionBody(BaseModel):
    action: str
    days: int = 7
    note: Optional[str] = None
    actor: Optional[str] = None


class BulkBody(BaseModel):
    ids: list[int] = Field(default_factory=list)
    action: str
    days: int = 7
    actor: Optional[str] = None


class RefreshBody(BaseModel):
    reload: bool = True


def _filters(state, severity, rule, sector, symbol, q, watchlist, sort) -> dict:
    return {"state": state, "severity": severity, "rule": rule, "sector": sector, "symbol": symbol,
            "q": q, "watchlist": watchlist, "sort": sort}


@router.get("")
def list_alerts(
    state: str = "open", severity: Optional[str] = None, rule: Optional[str] = None,
    sector: Optional[str] = None, symbol: Optional[str] = None, q: Optional[str] = None,
    watchlist: bool = False, sort: str = "severity",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
):
    return E.list_alerts(_filters(state, severity, rule, sector, symbol, q, watchlist, sort), page, page_size)


@router.get("/summary")
def summary():
    return E.summary()


@router.get("/settings")
def get_settings():
    return {"settings": E.get_settings(), "rule_meta": E.RULE_META, "channels": E.channels_configured()}


@router.put("/settings")
def put_settings(patch: dict = Body(...)):
    st = E.save_settings(patch)
    E.reschedule()
    run = E.run_cycle(actor="settings")
    return {"settings": st, "rule_meta": E.RULE_META, "channels": E.channels_configured(), "run": run}


@router.post("/refresh")
def refresh(body: RefreshBody = RefreshBody()):
    run = E.run_cycle(force_snapshot=body.reload, reload_data=body.reload, actor="manual")
    if run.get("error"):
        raise HTTPException(500, run["error"])
    return {"run": run, "summary": E.summary()}


@router.post("/bulk")
def bulk(body: BulkBody):
    if not body.ids:
        raise HTTPException(400, "no alert ids given")
    done, failed = 0, []
    for i in body.ids:
        try:
            E.act(i, body.action, body.actor or "analyst", body.days)
            done += 1
        except (KeyError, ValueError) as e:
            failed.append({"id": i, "error": str(e)})
    return {"updated": done, "failed": failed, "summary": E.summary()}


@router.post("/notify/test")
def notify_test():
    return E.notify([], E.get_settings(), force_text="Test message from Vigilance alerts.")


@router.get("/export.csv")
def export_csv(
    state: str = "open", severity: Optional[str] = None, rule: Optional[str] = None,
    sector: Optional[str] = None, symbol: Optional[str] = None, q: Optional[str] = None,
    watchlist: bool = False, sort: str = "severity",
):
    data = E.export_csv(_filters(state, severity, rule, sector, symbol, q, watchlist, sort))
    return Response(data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="alerts.csv"', "Access-Control-Expose-Headers": "Content-Disposition"})


@router.get("/history/{symbol}")
def history(symbol: str):
    return {"symbol": symbol.upper(), "history": E.history(symbol)}


@router.get("/{alert_id:int}")
def get_alert(alert_id: int):
    out = E.get_alert(alert_id)
    if not out:
        raise HTTPException(404, f"Unknown alert {alert_id}")
    return out


@router.post("/{alert_id:int}/action")
def alert_action(alert_id: int, body: ActionBody):
    try:
        return E.act(alert_id, body.action, body.actor or "analyst", body.days, body.note)
    except KeyError:
        raise HTTPException(404, f"Unknown alert {alert_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))