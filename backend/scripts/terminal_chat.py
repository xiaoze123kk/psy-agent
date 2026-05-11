from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.security import hash_password
from app.db.models import ConversationThread, User, UserProfile, UserSettings
from app.db.session import SessionLocal, init_db
from app.schemas.chat import SendMessageRequest
from app.schemas.common import AgeRange, InputType, ThreadMode, UserMode
from app.services.chat_service import list_messages_for_thread, list_threads_for_user, process_message_turn
from app.services.memory_job_service import process_pending_memory_jobs


DEFAULT_USERNAME = "terminal_user"
DEFAULT_THREAD_TITLE = "terminal-chat"
DEFAULT_NICKNAME = "Terminal"


@dataclass
class TerminalSession:
    user: User
    thread: ConversationThread


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _truncate(text: object, limit: int = 120) -> str:
    value = str(text or "").replace("\r\n", "\n").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)] + "…"


def ensure_terminal_user(
    db: Session,
    *,
    username: str = DEFAULT_USERNAME,
    nickname: str = DEFAULT_NICKNAME,
    age_range: AgeRange = AgeRange.age_18_plus,
    user_mode: UserMode = UserMode.adult,
    memory_mode: str = "summary_only",
    companion_style: str = "",
) -> User:
    normalized_username = _normalize_username(username)
    user = db.scalar(select(User).where(User.username == normalized_username))
    if user is None:
        user = User(
            username=normalized_username,
            password_hash=hash_password(f"terminal:{normalized_username}"),
            status="active",
        )
        db.add(user)
        db.flush()

    if user.deleted_at is not None:
        user.deleted_at = None
    user.status = "active"

    if user.profile is None:
        user.profile = UserProfile(
            nickname=nickname,
            age_range=age_range.value,
            user_mode=user_mode.value,
            usage_goals=[],
            onboarding_completed=True,
        )
    if user.settings is None:
        user.settings = UserSettings(
            memory_mode=memory_mode,
            companion_style=companion_style,
            voice_enabled=False,
            save_voice_audio=False,
            save_transcript=True,
            crisis_resource_region="CN",
        )

    db.commit()
    db.refresh(user)
    return user


def ensure_terminal_thread(
    db: Session,
    *,
    user: User,
    title: str = DEFAULT_THREAD_TITLE,
    mode: ThreadMode = ThreadMode.companion,
    create_new: bool = False,
) -> ConversationThread:
    normalized_title = title.strip() or DEFAULT_THREAD_TITLE
    if not create_new:
        thread = db.scalar(
            select(ConversationThread)
            .where(
                ConversationThread.user_id == user.id,
                ConversationThread.title == normalized_title,
                ConversationThread.archived_at.is_(None),
            )
            .order_by(desc(ConversationThread.updated_at))
            )
        if thread is not None:
            return thread

    thread_id = str(uuid4())
    thread = ConversationThread(
        id=thread_id,
        user_id=user.id,
        langgraph_thread_id=f"lg-{thread_id}",
        title=normalized_title,
        mode=mode.value,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def list_terminal_threads(db: Session, user: User) -> list[ConversationThread]:
    return list_threads_for_user(db, user.id)


def list_thread_messages(db: Session, thread: ConversationThread):
    return list_messages_for_thread(db, thread.id)


def print_thread_overview(db: Session, user: User, current_thread: ConversationThread) -> None:
    print(f"User: {user.username} ({getattr(user.profile, 'user_mode', 'adult')})")
    print(f"Thread: {current_thread.id} | {current_thread.title or 'new session'} | {current_thread.mode}")


def print_thread_list(db: Session, user: User) -> None:
    threads = list_terminal_threads(db, user)
    if not threads:
        print("No threads yet.")
        return

    for index, thread in enumerate(threads, start=1):
        summary = _truncate(thread.last_summary, 80) or "-"
        print(
            f"[{index}] {thread.id} | {thread.title or 'new session'} | "
            f"{thread.last_risk_level} | {thread.updated_at:%Y-%m-%d %H:%M} | {summary}"
        )


def print_thread_history(db: Session, thread: ConversationThread, *, limit: int | None = None) -> None:
    messages = list_thread_messages(db, thread)
    if limit is not None and limit > 0:
        messages = messages[-limit:]
    if not messages:
        print("No messages yet.")
        return

    for message in messages:
        role = "You" if message.role == "user" else "Assistant"
        content = message.content.strip()
        print(f"{message.created_at:%Y-%m-%d %H:%M:%S} {role}: {content}")


def print_turn_result(assistant_message, assistant_result: dict[str, object]) -> None:
    delivery_status = str(assistant_result.get("delivery_status", "generated"))
    risk_level = str(assistant_result.get("risk_level", "L0"))
    turn_id = str(assistant_result.get("turn_id") or "-")
    text = str(assistant_result.get("assistant_text") or "").strip()

    if assistant_message is None:
        failure_reason = str(assistant_result.get("failure_reason") or "no reply")
        print(f"[{turn_id}] Assistant [{delivery_status}/{risk_level}]: {failure_reason}")
    else:
        print(f"[{turn_id}] Assistant [{delivery_status}/{risk_level}]: {text or assistant_message.content.strip()}")

    suggested_actions = [str(item).strip() for item in assistant_result.get("suggested_actions", []) if str(item).strip()]
    if suggested_actions:
        print("Suggested: " + " / ".join(suggested_actions))

    memory_job_status = assistant_result.get("memory_job_status")
    memory_job_id = assistant_result.get("memory_job_id")
    if memory_job_id:
        print(f"Memory job: {memory_job_id} ({memory_job_status})")


async def send_turn(
    db: Session,
    *,
    user: User,
    thread: ConversationThread,
    content: str,
) -> tuple[object | None, dict[str, object]]:
    payload = SendMessageRequest(content=content, input_type=InputType.text)
    user_message, assistant_message, assistant_result = await process_message_turn(
        db,
        user=user,
        thread=thread,
        payload=payload,
    )
    try:
        await process_pending_memory_jobs(db)
    except Exception as exc:
        print(f"[memory] failed to process pending jobs: {exc}")
    db.refresh(user_message)
    db.refresh(thread)
    if assistant_message is not None:
        db.refresh(assistant_message)
        assistant_meta = assistant_message.meta if isinstance(assistant_message.meta, dict) else {}
        if assistant_meta:
            assistant_result["memory_job_id"] = assistant_meta.get("memory_job_id", assistant_result.get("memory_job_id"))
            assistant_result["memory_job_status"] = assistant_meta.get(
                "memory_job_status",
                assistant_result.get("memory_job_status"),
            )
    return assistant_message, assistant_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive terminal chat client for backend testing.")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Local test username to reuse or create.")
    parser.add_argument("--thread-title", default=DEFAULT_THREAD_TITLE, help="Thread title to reuse or create.")
    parser.add_argument("--new-thread", action="store_true", help="Always create a new thread for this run.")
    parser.add_argument(
        "--message",
        action="append",
        help="Send one or more messages and exit instead of entering interactive mode.",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=20,
        help="How many recent messages to show for the /history command.",
    )
    return parser


async def run_terminal_chat(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as db:
        user = ensure_terminal_user(db, username=args.username)
        thread = ensure_terminal_thread(
            db,
            user=user,
            title=args.thread_title,
            create_new=bool(args.new_thread),
        )
        session = TerminalSession(user=user, thread=thread)

        print("Terminal chat ready.")
        print_thread_overview(db, session.user, session.thread)
        print("Commands: /help /new [title] /use <thread_id> /threads /history [n] /exit")

        if args.message:
            for content in args.message:
                try:
                    assistant_message, assistant_result = await send_turn(
                        db,
                        user=session.user,
                        thread=session.thread,
                        content=content,
                    )
                except Exception as exc:
                    print(f"[error] {exc}")
                    continue
                print_turn_result(assistant_message, assistant_result)
            return

        while True:
            try:
                raw = input(f"{session.thread.title or 'chat'}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not raw:
                continue

            if raw.startswith("/"):
                command, _, remainder = raw[1:].partition(" ")
                command = command.lower().strip()
                remainder = remainder.strip()

                if command in {"exit", "quit"}:
                    break
                if command == "help":
                    print("Commands: /help /new [title] /use <thread_id> /threads /history [n] /exit")
                    continue
                if command == "threads":
                    print_thread_list(db, session.user)
                    continue
                if command == "history":
                    limit = args.history_limit
                    if remainder.isdigit():
                        limit = max(int(remainder), 1)
                    print_thread_history(db, session.thread, limit=limit)
                    continue
                if command == "new":
                    new_title = remainder or args.thread_title
                    session.thread = ensure_terminal_thread(
                        db,
                        user=session.user,
                        title=new_title,
                        create_new=True,
                    )
                    print_thread_overview(db, session.user, session.thread)
                    continue
                if command == "use":
                    if not remainder:
                        print("Usage: /use <thread_id>")
                        continue
                    target_thread = db.scalar(
                        select(ConversationThread).where(
                            ConversationThread.id == remainder,
                            ConversationThread.user_id == session.user.id,
                            ConversationThread.archived_at.is_(None),
                        )
                    )
                    if target_thread is None:
                        print("Thread not found.")
                        continue
                    session.thread = target_thread
                    print_thread_overview(db, session.user, session.thread)
                    continue
                print(f"Unknown command: /{command}")
                continue

            try:
                assistant_message, assistant_result = await send_turn(
                    db,
                    user=session.user,
                    thread=session.thread,
                    content=raw,
                )
            except Exception as exc:
                print(f"[error] {exc}")
                continue
            print_turn_result(assistant_message, assistant_result)


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    await run_terminal_chat(args)


if __name__ == "__main__":
    asyncio.run(main())
