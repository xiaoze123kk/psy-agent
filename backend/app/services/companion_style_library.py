from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import CompanionStyle, User, utcnow
from app.schemas.companion_styles import (
    CompanionStyleItem,
    CompanionStyleListResponse,
    CompanionStyleReplaceRequest,
)
from app.services.companion_style import (
    MAX_COMPANION_STYLES,
    normalize_custom_companion_style,
    normalize_custom_companion_style_title,
)


DEFAULT_STYLE_ID = "default"
FALLBACK_STYLE_TITLE = "当前风格"


class CompanionStyleLibraryError(ValueError):
    pass


def _ordered_styles(db: Session, user_id: str) -> list[CompanionStyle]:
    return list(
        db.scalars(
            select(CompanionStyle)
            .where(CompanionStyle.user_id == user_id)
            .order_by(CompanionStyle.sort_order.asc(), CompanionStyle.updated_at.desc())
        )
    )


def _serialize(style: CompanionStyle) -> CompanionStyleItem:
    return CompanionStyleItem(
        style_id=style.id,
        title=style.title,
        definition=normalize_custom_companion_style(style.definition),
        is_default=bool(style.is_default),
        created_at=style.created_at,
        updated_at=style.updated_at,
    )


def _response(db: Session, user: User) -> CompanionStyleListResponse:
    styles = _ordered_styles(db, user.id)
    selected = next((style for style in styles if style.is_default), None)
    companion_style = normalize_custom_companion_style(user.settings.companion_style if user.settings else "")
    return CompanionStyleListResponse(
        items=[_serialize(style) for style in styles],
        selected_style_id=selected.id if selected else DEFAULT_STYLE_ID,
        companion_style=companion_style,
    )


def list_companion_styles(db: Session, user: User) -> CompanionStyleListResponse:
    return _response(db, user)


def _find_selected_style(
    styles: list[CompanionStyle],
    selected_style_id: str | None,
    client_id_map: dict[str, str],
) -> CompanionStyle | None:
    selected_key = (selected_style_id or DEFAULT_STYLE_ID).strip()
    if selected_key == DEFAULT_STYLE_ID:
        return None
    server_style_id = client_id_map.get(selected_key, selected_key)
    return next((style for style in styles if style.id == server_style_id), None)


def replace_companion_styles(
    db: Session,
    user: User,
    payload: CompanionStyleReplaceRequest,
) -> CompanionStyleListResponse:
    if user.settings is None:
        raise CompanionStyleLibraryError("User settings are incomplete.")
    if len(payload.items) > MAX_COMPANION_STYLES:
        raise CompanionStyleLibraryError(f"At most {MAX_COMPANION_STYLES} companion styles can be saved.")

    existing = {style.id: style for style in _ordered_styles(db, user.id)}
    seen_payload_ids: set[str] = set()
    seen_client_ids: set[str] = set()
    client_id_map: dict[str, str] = {}
    next_styles: list[CompanionStyle] = []
    now = utcnow()

    for index, item in enumerate(payload.items):
        title = normalize_custom_companion_style_title(item.title)
        definition = normalize_custom_companion_style(item.definition)
        if not title:
            raise CompanionStyleLibraryError("Companion style title is required.")
        if not definition:
            raise CompanionStyleLibraryError("Companion style definition is required.")

        style = existing.get(item.style_id or "")
        if style is not None and style.user_id == user.id:
            seen_payload_ids.add(style.id)
            style.title = title
            style.definition = definition
            style.sort_order = index
            style.updated_at = now
        else:
            style = CompanionStyle(
                user_id=user.id,
                title=title,
                definition=definition,
                sort_order=index,
                is_default=False,
            )
            db.add(style)
            db.flush()
            seen_payload_ids.add(style.id)

        style.is_default = False
        next_styles.append(style)

        if item.client_id and item.client_id not in seen_client_ids:
            client_id_map[item.client_id] = style.id
            seen_client_ids.add(item.client_id)
        if item.style_id:
            client_id_map[item.style_id] = style.id

    omitted_ids = set(existing) - seen_payload_ids
    if omitted_ids:
        db.execute(delete(CompanionStyle).where(CompanionStyle.user_id == user.id, CompanionStyle.id.in_(omitted_ids)))

    selected_style = _find_selected_style(next_styles, payload.selected_style_id, client_id_map)
    if selected_style is not None:
        selected_style.is_default = True
        user.settings.companion_style = normalize_custom_companion_style(selected_style.definition)
    else:
        user.settings.companion_style = ""
    user.settings.updated_at = now

    db.commit()
    db.refresh(user.settings)
    return _response(db, user)


def sync_companion_style_from_definition(
    db: Session,
    user: User,
    definition: str | None,
    *,
    title: str = FALLBACK_STYLE_TITLE,
    commit: bool = True,
) -> CompanionStyleListResponse:
    if user.settings is None:
        raise CompanionStyleLibraryError("User settings are incomplete.")

    normalized_definition = normalize_custom_companion_style(definition)
    now = utcnow()
    styles = _ordered_styles(db, user.id)
    for style in styles:
        style.is_default = False
        style.updated_at = now

    if not normalized_definition:
        user.settings.companion_style = ""
        user.settings.updated_at = now
        if commit:
            db.commit()
            db.refresh(user.settings)
        else:
            db.flush()
        return _response(db, user)

    selected = next(
        (style for style in styles if normalize_custom_companion_style(style.definition) == normalized_definition),
        None,
    )
    if selected is None:
        selected = CompanionStyle(
            user_id=user.id,
            title=normalize_custom_companion_style_title(title) or FALLBACK_STYLE_TITLE,
            definition=normalized_definition,
            is_default=True,
            sort_order=0,
        )
        db.add(selected)
        db.flush()
        for index, style in enumerate(styles, start=1):
            style.sort_order = index
    else:
        selected.is_default = True
        selected.updated_at = now

    user.settings.companion_style = normalized_definition
    user.settings.updated_at = now
    if commit:
        db.commit()
        db.refresh(user.settings)
    else:
        db.flush()
    return _response(db, user)
