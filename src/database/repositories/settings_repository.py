from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Setting


def get_by_key(session: Session, key: str) -> Setting | None:
    return session.query(Setting).filter(Setting.key == key).first()


def set_by_key(
    session: Session,
    key: str,
    value: str,
    *,
    category: str,
    description: str | None,
) -> Setting:
    row = get_by_key(session, key)
    if row is None:
        row = Setting(
            key=key,
            value=value,
            category=category,
            description=description,
        )
        session.add(row)
    else:
        row.value = value
        row.category = category
        row.description = description or row.description

    session.flush()
    session.refresh(row)
    return row


def set_many(session: Session, items: dict[str, dict[str, str | None]]) -> None:
    for key, payload in items.items():
        set_by_key(
            session,
            key,
            str(payload["value"] or ""),
            category=str(payload["category"] or "general"),
            description=payload.get("description"),
        )


def load_runtime_values(session: Session) -> dict[str, str]:
    rows = session.query(Setting).all()
    return {row.key: row.value or "" for row in rows}
