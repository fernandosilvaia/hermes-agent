"""
calendar_events.py — Criar, listar, editar e cancelar eventos no Google Calendar.

(Nome do arquivo é calendar_events.py e não calendar.py para não sombrear o
módulo `calendar` da biblioteca padrão do Python.)

Uso como biblioteca:
    from calendar_events import create_event, list_upcoming, edit_event, cancel_event

Uso como CLI:
    python calendar_events.py create --summary "Reunião cliente" \
        --start "2026-07-10T15:00:00" --end "2026-07-10T16:00:00" \
        --tz "America/Sao_Paulo" --attendees "a@x.com,b@y.com" --description "Pauta..."
    python calendar_events.py list --max 10
    python calendar_events.py edit --id <EVENT_ID> --summary "Novo título"
    python calendar_events.py cancel --id <EVENT_ID>

Datas: use ISO 8601. Para evento de dia inteiro, passe só a data (YYYY-MM-DD)
via --all-day.
"""

import argparse
import json
from datetime import datetime, timezone

import auth

DEFAULT_TZ = "America/Sao_Paulo"


def _time_field(value: str, all_day: bool, tz: str) -> dict:
    if all_day:
        return {"date": value}
    return {"dateTime": value, "timeZone": tz}


def create_event(summary: str, start: str, end: str, tz: str = DEFAULT_TZ,
                 description: str = None, location: str = None,
                 attendees: list = None, all_day: bool = False,
                 calendar_id: str = "primary") -> dict:
    body = {
        "summary": summary,
        "start": _time_field(start, all_day, tz),
        "end": _time_field(end, all_day, tz),
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e.strip()} for e in attendees if e.strip()]

    ev = auth.calendar().events().insert(
        calendarId=calendar_id, body=body, sendUpdates="all"
    ).execute()
    return {"id": ev["id"], "summary": ev.get("summary"), "htmlLink": ev.get("htmlLink")}


def list_upcoming(max_results: int = 10, calendar_id: str = "primary") -> list:
    now = datetime.now(timezone.utc).isoformat()
    resp = auth.calendar().events().list(
        calendarId=calendar_id, timeMin=now, maxResults=max_results,
        singleEvents=True, orderBy="startTime",
    ).execute()
    out = []
    for ev in resp.get("items", []):
        start = ev.get("start", {})
        out.append({
            "id": ev["id"],
            "summary": ev.get("summary"),
            "start": start.get("dateTime", start.get("date")),
            "location": ev.get("location"),
            "htmlLink": ev.get("htmlLink"),
        })
    return out


def edit_event(event_id: str, calendar_id: str = "primary", **fields) -> dict:
    """Edita campos de um evento. Aceita summary, description, location,
    e start/end como dicts já formatados (ou use create_event de novo)."""
    clean = {k: v for k, v in fields.items() if v is not None}
    ev = auth.calendar().events().patch(
        calendarId=calendar_id, eventId=event_id, body=clean, sendUpdates="all"
    ).execute()
    return {"id": ev["id"], "summary": ev.get("summary"), "updated": list(clean)}


def cancel_event(event_id: str, calendar_id: str = "primary") -> dict:
    """Cancela (deleta) um evento. Ação sensível — confirmar antes na conversa."""
    auth.calendar().events().delete(
        calendarId=calendar_id, eventId=event_id, sendUpdates="all"
    ).execute()
    return {"id": event_id, "cancelled": True}


def _cli():
    p = argparse.ArgumentParser(description="Google Calendar via Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--summary", required=True)
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--tz", default=DEFAULT_TZ)
    c.add_argument("--description")
    c.add_argument("--location")
    c.add_argument("--attendees", help="emails vírgula-separados")
    c.add_argument("--all-day", action="store_true")

    l = sub.add_parser("list")
    l.add_argument("--max", type=int, default=10)

    e = sub.add_parser("edit")
    e.add_argument("--id", required=True)
    e.add_argument("--summary")
    e.add_argument("--description")
    e.add_argument("--location")

    x = sub.add_parser("cancel")
    x.add_argument("--id", required=True)

    args = p.parse_args()
    if args.cmd == "create":
        attendees = args.attendees.split(",") if args.attendees else None
        out = create_event(
            args.summary, args.start, args.end, args.tz,
            args.description, args.location, attendees, args.all_day,
        )
    elif args.cmd == "list":
        out = list_upcoming(args.max)
    elif args.cmd == "edit":
        out = edit_event(
            args.id, summary=args.summary,
            description=args.description, location=args.location,
        )
    elif args.cmd == "cancel":
        out = cancel_event(args.id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
