#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 Smart Chat Automation Userbot  (Pyrogram + StringSession + Render/Docker)
==============================================================================
"""
from __future__ import annotations

import asyncio
import base64
import collections
import contextlib
import html
import ipaddress
import json
import logging
import math
import os
import platform
import re
import signal
import sys
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

from pyrogram import Client, enums, filters  # noqa: E402
from pyrogram import __version__ as PYROGRAM_VERSION  # noqa: E402
from pyrogram import errors as pyro_errors  # noqa: E402
from pyrogram.handlers import MessageHandler, RawUpdateHandler  # noqa: E402
from pyrogram.raw import types as raw_types  # noqa: E402


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


class Config:
    API_ID: int = _env_int("API_ID", 0)
    API_HASH: str = _env_str("API_HASH")
    STRING_SESSION: str = _env_str("STRING_SESSION")

    PORT: int = _env_int("PORT", 7860)
    DEFAULT_MODE: str = _env_str("DEFAULT_MODE", "selected").lower()

    FAKE_PHOTO_SECONDS: float = _env_float("FAKE_PHOTO_SECONDS", 3.0)
    FAKE_DOC_SECONDS: float = _env_float("FAKE_DOC_SECONDS", 5.0)
    FAKE_TYPING_SECONDS: float = _env_float("FAKE_TYPING_SECONDS", 9.0)
    FAKE_COOLDOWN: float = _env_float("FAKE_COOLDOWN", 30.0)
    MAX_PHASE_SECONDS: float = 120.0
    MAX_COOLDOWN: float = 3600.0
    ALL_INCLUDE_CONTACTS: bool = _env_bool("ALL_INCLUDE_CONTACTS", False)
    ACTION_REFRESH: float = 2.5

    OWNER_ACTIVE_WINDOW: float = _env_float("OWNER_ACTIVE_WINDOW", 900.0)
    READ_ACTIVE_WINDOW: float = _env_float("READ_ACTIVE_WINDOW", 120.0)
    BURST_GRACE: float = _env_float("BURST_GRACE", 8.0)
    MAX_MESSAGE_AGE: float = _env_float("MAX_MESSAGE_AGE", 3600.0)
    HISTORY_CHECK_LIMIT: int = _env_int("HISTORY_CHECK_LIMIT", 8)

    QUARANTINE_THRESHOLD: int = _env_int("QUARANTINE_THRESHOLD", 2)
    NOTICE_THROTTLE: float = 600.0

    STATE_FILE: str = _env_str("STATE_FILE", "data/state.json")
    CLOUD_STATE: bool = _env_bool("CLOUD_STATE", True)
    CLOUD_SCAN_LIMIT: int = _env_int("CLOUD_SCAN_LIMIT", 600)
    AUTOSAVE_INTERVAL: float = _env_float("AUTOSAVE_INTERVAL", 10.0)

    STARTUP_NOTICE: bool = _env_bool("STARTUP_NOTICE", True)
    WATCHDOG_INTERVAL: float = _env_float("WATCHDOG_INTERVAL", 300.0)
    SLEEP_THRESHOLD: int = _env_int("SLEEP_THRESHOLD", 60)

    SELF_PING: bool = _env_bool("SELF_PING", True)
    SELF_PING_INTERVAL: float = _env_float("SELF_PING_INTERVAL", 600.0)

    LOG_LEVEL: str = _env_str("LOG_LEVEL", "INFO").upper()


logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("userbot")

START_TS = time.time()
RUNTIME: Dict[str, Any] = {"connected": False, "last_ok": 0.0}

FIRST_REPLY = (
    "Salom, men Elbekning avtomatlashgan botiman! 🤖 Hozir band edilar, "
    "xabaringizni yozib qoldirishingiz mumkin. Imkon topilishi bilan o'zlari "
    "javob beradilar.\n\n"
    "Ungacha foydali yordamchimizdan foydalanib turing: https://t.me/EduMindUz_bot"
)

SECOND_REPLY = (
    "Xabaringiz uchun tashakkur! Elbek imkon topilishi bilan o'zlari javob "
    "yozadilar. 🙏\n\n"
    "Shu orada EduMind yordamchisidan foydalanib turishingiz mumkin: "
    "https://t.me/EduMindUz_bot"
)

BOT_TEXTS: Set[str] = {FIRST_REPLY.strip(), SECOND_REPLY.strip()}

HELP_TEXT = (
    "🤖 <b>Smart Chat Automation Userbot</b>\n\n"
    "<b>Mantiq:</b> Fake status istalgan odamga ishlaydi. Auto-reply esa rejimga ko'ra.\n\n"
    "• <code>/on</code> · <code>/off</code> — master o'chirgich\n"
    "• <code>/status</code> · <code>/panel</code> · <code>/list</code>\n"
    "• <code>/fake on|off</code> · <code>/fake set 3 5 9</code>\n"
    "• <code>/reply on|off</code>\n"
    "• <code>/add @username</code> (yoki forward+reply / raqamli ID)\n"
    "• <code>/remove @username|ID|all</code>\n"
    "• <code>/quarantine</code> · <code>/release ID</code>"
)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days} kun")
    if hours:
        parts.append(f"{hours} soat")
    if minutes:
        parts.append(f"{minutes} daq")
    if not parts:
        parts.append(f"{secs} son")
    return " ".join(parts)


def clamp_seconds(value: Any, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(min(max(number, 0.0), maximum), 1)


def fmt_secs(value: float) -> str:
    return f"{value:g}s"


def display_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    return f"ID {getattr(user, 'id', '?')}"


def mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{esc(name)}</a>'


def utf16_slice(text: str, offset: int, length: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def defang(text: str) -> str:
    return text.replace("http", "hxxp").replace(".", "[.]")


def split_text(text: str, limit: int = 3800) -> List[str]:
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def _perr(name: str) -> type:
    obj = getattr(pyro_errors, name, None)
    if obj is None:
        return type(name, (Exception,), {})
    return obj


RPCError = pyro_errors.RPCError
FloodWait = pyro_errors.FloodWait
AuthKeyDuplicated = _perr("AuthKeyDuplicated")
FATAL_AUTH_ERRORS = tuple(
    _perr(n)
    for n in (
        "AuthKeyUnregistered",
        "SessionRevoked",
        "SessionExpired",
        "UserDeactivated",
        "UserDeactivatedBan",
    )
)
MessageNotModified = _perr("MessageNotModified")


def flood_seconds(exc: Exception, default: float = 5.0) -> float:
    value = getattr(exc, "value", None)
    if value is None:
        value = getattr(exc, "x", default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


DANGEROUS_EXTENSIONS = {"apk", "apks", "xapk", "exe", "bat", "cmd", "scr", "pif", "msi", "jar", "vbs", "js", "sh"}


@dataclass
class ScanResult:
    score: int
    reasons: List[str]

    @property
    def flagged(self) -> bool:
        return self.score >= Config.QUARANTINE_THRESHOLD and bool(self.reasons)


class Scanner:
    def scan(self, message: Any) -> ScanResult:
        reasons = []
        score = 0
        doc = getattr(message, "document", None)
        if doc and getattr(doc, "file_name", ""):
            ext = doc.file_name.split(".")[-1].lower()
            if ext in DANGEROUS_EXTENSIONS:
                score += 3
                reasons.append(f"Xavfli fayl kengaytmasi: .{ext}")
        return ScanResult(score, reasons)


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.enabled: bool = True
        self.fake_enabled: bool = True
        self.reply_enabled: bool = True
        self.fake_photo: float = 3.0
        self.fake_doc: float = 5.0
        self.fake_typing: float = 9.0
        self.fake_cooldown: float = 30.0
        self.include_contacts: bool = Config.ALL_INCLUDE_CONTACTS
        self.mode: str = Config.DEFAULT_MODE if Config.DEFAULT_MODE in {"selected", "all"} else "selected"
        self.selected: Dict[str, Dict[str, Any]] = {}
        self.quarantine: Dict[str, Dict[str, Any]] = {}
        self.chats: Dict[str, Dict[str, Any]] = {}
        self.stats: Dict[str, int] = {"replies_sent": 0, "aborted": 0, "quarantined": 0, "fake_runs": 0}
        self.updated_at: float = 0.0
        self.dirty: bool = False
        self._cloud_msg_id: Optional[int] = None

    def touch(self) -> None:
        self.updated_at = time.time()
        self.dirty = True

    def to_dict(self, include_chats: bool = True) -> Dict[str, Any]:
        data = {
            "v": 1,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
            "fake_enabled": self.fake_enabled,
            "reply_enabled": self.reply_enabled,
            "fake_photo": self.fake_photo,
            "fake_doc": self.fake_doc,
            "fake_typing": self.fake_typing,
            "fake_cooldown": self.fake_cooldown,
            "include_contacts": self.include_contacts,
            "mode": self.mode,
            "selected": self.selected,
            "quarantine": self.quarantine,
            "stats": self.stats,
        }
        if include_chats:
            data["chats"] = self.chats
        return data

    def apply_dict(self, data: Dict[str, Any]) -> None:
        self.enabled = bool(data.get("enabled", True))
        self.fake_enabled = bool(data.get("fake_enabled", True))
        self.reply_enabled = bool(data.get("reply_enabled", True))
        self.fake_photo = clamp_seconds(data.get("fake_photo", 3.0), Config.MAX_PHASE_SECONDS)
        self.fake_doc = clamp_seconds(data.get("fake_doc", 5.0), Config.MAX_PHASE_SECONDS)
        self.fake_typing = clamp_seconds(data.get("fake_typing", 9.0), Config.MAX_PHASE_SECONDS)
        self.fake_cooldown = clamp_seconds(data.get("fake_cooldown", 30.0), Config.MAX_COOLDOWN)
        self.include_contacts = bool(data.get("include_contacts", self.include_contacts))
        mode = str(data.get("mode", self.mode)).lower()
        self.mode = mode if mode in {"selected", "all"} else "selected"
        self.selected = {str(k): dict(v) for k, v in data.get("selected", {}).items()}
        self.quarantine = {str(k): dict(v) for k, v in data.get("quarantine", {}).items()}
        self.chats = {str(k): dict(v) for k, v in data.get("chats", {}).items()}

    def fake_total(self) -> float:
        return self.fake_photo + self.fake_doc + self.fake_typing

    def fake_active(self) -> bool:
        return self.fake_enabled and self.fake_total() > 0

    def fake_phases(self) -> List[Tuple[str, Any, float]]:
        specs = (
            ("rasm yuklayapti", enums.ChatAction.UPLOAD_PHOTO, self.fake_photo),
            ("fayl yuklayapti", enums.ChatAction.UPLOAD_DOCUMENT, self.fake_doc),
            ("yozyapti", enums.ChatAction.TYPING, self.fake_typing),
        )
        return [(label, action, secs) for label, action, secs in specs if secs > 0]

    def reset_fake_durations(self) -> None:
        self.fake_photo = 3.0
        self.fake_doc = 5.0
        self.fake_typing = 9.0
        self.fake_cooldown = 30.0

    def chat(self, chat_id: int) -> Dict[str, Any]:
        key = str(chat_id)
        return self.chats.setdefault(key, {"stage": 0, "last_reply_at": 0.0})

    def reset_chat(self, chat_id: int) -> bool:
        key = str(chat_id)
        if key in self.chats:
            del self.chats[key]
            self.touch()
            return True
        return False

    def load_file(self) -> bool:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self.apply_dict(json.load(fh))
            return True
        except Exception:
            return False

    def save_file(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    async def cloud_load(self, client: Client, me_id: int) -> bool:
        if not Config.CLOUD_STATE:
            return False
        try:
            async for msg in client.get_chat_history(me_id, limit=Config.CLOUD_SCAN_LIMIT):
                text = msg.text or ""
                if text.startswith("🗄 USERBOT_STATE_V1"):
                    payload = text.split("\n", 1)[1].strip()
                    data = json.loads(zlib.decompress(base64.b64decode(payload)).decode("utf-8"))
                    self.apply_dict(data)
                    return True
        except Exception:
            pass
        return False

    async def cloud_save(self, client: Client, me_id: int) -> None:
        if not Config.CLOUD_STATE:
            return
        raw = json.dumps(self.to_dict(True), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        text = "🗄 USERBOT_STATE_V1\n" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
        try:
            if self._cloud_msg_id:
                await client.edit_message_text(me_id, self._cloud_msg_id, text, parse_mode=enums.ParseMode.DISABLED)
            else:
                sent = await client.send_message(me_id, text, parse_mode=enums.ParseMode.DISABLED)
                self._cloud_msg_id = sent.id
        except Exception:
            pass

    async def flush(self, client: Optional[Client], me_id: Optional[int]) -> None:
        self.dirty = False
        self.save_file()
        if client and me_id and RUNTIME.get("connected"):
            await self.cloud_save(client, me_id)


def start_keepalive_server() -> None:
    port = Config.PORT
    def run_flask():
        from flask import Flask, jsonify
        flask_app = Flask("keepalive")
        @flask_app.route("/")
        def index(): return "Running ✅", 200
        @flask_app.route("/health")
        def health(): return jsonify(status="ok", uptime=int(time.time() - START_TS)), 200
        flask_app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
    threading.Thread(target=run_flask, daemon=True).start()


def start_self_ping() -> None:
    base = _env_str("SELF_PING_URL") or _env_str("RENDER_EXTERNAL_URL")
    if not Config.SELF_PING or not base:
        return
    target = base.rstrip("/") + "/health"
    def runner():
        import urllib.request
        while True:
            time.sleep(300)
            with contextlib.suppress(Exception):
                urllib.request.urlopen(target, timeout=10).read(16)
    threading.Thread(target=runner, daemon=True).start()


@dataclass
class Target:
    uid: int
    name: str
    username: Optional[str]
    resolved: bool = True


def parse_user_ref(token: str) -> Tuple[Optional[str], Any]:
    t = token.strip().strip(",;")
    if not t:
        return None, None
    if re.fullmatch(r"\d{3,15}", t):
        return "id", int(t)
    t = t.split("?")[0].split("/")[0].lstrip("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", t):
        return "username", t
    return None, None


class Engine:
    def __init__(self, app: "UserbotApp") -> None:
        self.app = app
        self.store = app.store
        self.scanner = Scanner()
        self.tasks: Dict[int, asyncio.Task] = {}
        self.locks: Dict[int, asyncio.Lock] = collections.defaultdict(asyncio.Lock)
        self.owner_out: Dict[int, float] = {}
        self.owner_read: Dict[int, float] = {}
        self.last_bot_send: Dict[int, float] = {}

    def is_running(self, chat_id: int) -> bool:
        task = self.tasks.get(chat_id)
        return task is not None and not task.done()

    def cancel_sequence(self, chat_id: int, reason: str) -> None:
        task = self.tasks.get(chat_id)
        if task and not task.done():
            task.cancel()

    def cancel_all(self, reason: str) -> None:
        for chat_id in list(self.tasks):
            self.cancel_sequence(chat_id, reason)

    def owner_activity_reason(self, chat_id: int) -> Optional[str]:
        now = time.time()
        if now - self.owner_out.get(chat_id, 0.0) < Config.OWNER_ACTIVE_WINDOW:
            return "egasi yaqinda yozgan"
        if now - self.owner_read.get(chat_id, 0.0) < Config.READ_ACTIVE_WINDOW:
            return "egasi o'qigan"
        return None

    async def on_raw_update(self, client: Client, update: Any, users: Any, chats: Any) -> None:
        if isinstance(update, raw_types.UpdateReadHistoryInbox):
            peer = update.peer
            if isinstance(peer, raw_types.PeerUser):
                uid = int(peer.user_id)
                if uid != self.app.me_id:
                    self.owner_read[uid] = time.time()
                    self.cancel_sequence(uid, "o'qildi")

    async def on_owner_outgoing(self, client: Client, message: Any) -> None:
        chat_id = message.chat.id
        if chat_id == self.app.me_id or getattr(message, "service", None):
            return
        self.owner_out[chat_id] = time.time()
        self.cancel_sequence(chat_id, "egasi yozdi")
        self.store.reset_chat(chat_id)

    async def on_incoming(self, client: Client, message: Any) -> None:
        try:
            await self._handle_incoming(client, message)
        except Exception:
            log.exception("Kiruvchi xabarni qayta ishlashda xatolik")

    async def _handle_incoming(self, client: Client, message: Any) -> None:
        user = message.from_user
        if user is None or user.is_self or user.is_bot or getattr(user, "is_deleted", False):
            return

        scan = self.scanner.scan(message)
        if scan.flagged:
            return

        uid_key = str(user.id)
        if uid_key in self.store.quarantine:
            return

        if not self.store.enabled:
            return

        do_fake = self.store.fake_active()
        do_reply = self.store.reply_enabled
        if not do_fake and not do_reply:
            return

        # QAYSI ODAMLARGA ISHLASHI:
        # 1. /add qilinganlar (selected) har doim ishlaydi.
        # 2. Rejim "all" bo'lsa -> Notanishlarga ishlaydi (kontaktlarda yo'q). Agar include_contacts=True bo'lsa, kontaktlarga ham.
        is_contact = bool(getattr(user, "is_contact", False))
        is_selected = uid_key in self.store.selected

        if self.store.mode == "selected":
            if not is_selected:
                return
        else: # all mode
            if not is_selected and is_contact and not self.store.include_contacts:
                return

        chat_id = message.chat.id
        async with self.locks[chat_id]:
            if self.is_running(chat_id):
                return
            if self.owner_activity_reason(chat_id):
                return

            if do_reply:
                state = self.store.chat(chat_id)
                if int(state.get("stage", 0)) >= 2:
                    return

            phases = self.store.fake_phases() if do_fake else []
            task = asyncio.create_task(self._sequence(client, chat_id, user.id, phases, do_reply))
            self.tasks[chat_id] = task

    async def _sequence(self, client: Client, chat_id: int, uid: int, phases: List[Any], do_reply: bool) -> None:
        started = time.time()
        replied = False
        try:
            for label, action, seconds in phases:
                await client.send_chat_action(chat_id, action)
                await asyncio.sleep(seconds)

            if not do_reply:
                return

            state = self.store.chat(chat_id)
            stage = int(state.get("stage", 0))
            text = FIRST_REPLY if stage == 0 else SECOND_REPLY
            sent = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.DISABLED)
            state["stage"] = stage + 1
            state["last_reply_at"] = time.time()
            self.store.stats["replies_sent"] += 1
            self.store.touch()
            replied = True
        except Exception:
            pass
        finally:
            if not replied and phases:
                with contextlib.suppress(Exception):
                    await client.send_chat_action(chat_id, enums.ChatAction.CANCEL)


class UserbotApp:
    def __init__(self) -> None:
        self.store = Store(Config.STATE_FILE)
        self.client: Optional[Client] = None
        self.me_id: Optional[int] = None
        self.stop_event = asyncio.Event()
        self.engine = Engine(self)

    async def say(self, text: str) -> None:
        if self.client:
            for chunk in split_text(text):
                with contextlib.suppress(Exception):
                    await self.client.send_message("me", chunk, parse_mode=enums.ParseMode.HTML)

    async def on_saved_message(self, client: Client, message: Any) -> None:
        text = (message.text or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd = parts[0][1:].lower()
        args = parts[1:]

        if cmd in ("help", "start"):
            await self.say(HELP_TEXT)
        elif cmd == "on":
            self.store.enabled = True
            self.store.touch()
            await self.say("✅ Bot yoqildi.")
        elif cmd == "off":
            self.store.enabled = False
            self.store.touch()
            await self.say("⛔ Bot o'chirildi.")
        elif cmd == "status":
            await self.say("📊 <b>Holat</b>\n" + self.engine._status_block())
        elif cmd == "add":
            if not args:
                await self.say("❌ Format: /add <id yoki username>")
                return
            for arg in args:
                clean = arg.lstrip("@")
                try:
                    u = await client.get_users(int(clean) if clean.isdigit() else clean)
                    self.store.selected[str(u.id)] = {"name": display_name(u), "username": u.username}
                    self.store.touch()
                    await self.say(f"✅ Qo'shildi: {display_name(u)} (`{u.id}`)")
                except Exception as e:
                    await self.say(f"❌ Xato: {arg} ({e})")
        elif cmd == "remove":
            if not args:
                await self.say("❌ Format: /remove <id>")
                return
            for arg in args:
                removed = self.store.selected.pop(arg, None)
                self.store.touch()
                await self.say(f"❌ O'chirildi: {arg}" if removed else f"⚠️ Topilmadi: {arg}")
        elif cmd == "list":
            sel = self.store.selected
            if not sel:
                await self.say("📋 Tanlanganlar ro'yxati bo'sh.")
                return
            await self.say("📋 <b>Tanlanganlar:</b>\n" + "\n".join(f"• {rec['name']} (`{uid}`)" for uid, rec in sel.items()))
        elif cmd == "fake":
            if args and args[0].lower() == "off":
                self.store.fake_enabled = False
                await self.say("⛔ Fake status o'chirildi.")
            else:
                self.store.fake_enabled = True
                await self.say("✅ Fake status yoqildi.")
            self.store.touch()
        elif cmd == "reply":
            if args and args[0].lower() == "off":
                self.store.reply_enabled = False
                await self.say("⛔ Auto-reply o'chirildi.")
            else:
                self.store.reply_enabled = True
                await self.say("✅ Auto-reply yoqildi.")
            self.store.touch()

    async def run(self) -> int:
        self.store.load_file()
        self.client = Client(
            "smart_userbot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.STRING_SESSION,
            in_memory=True,
        )
        self.client.add_handler(RawUpdateHandler(self.engine.on_raw_update), group=-1)
        self.client.add_handler(MessageHandler(self.on_saved_message, filters.private & filters.incoming & filters.user("me")), group=0)
        self.client.add_handler(MessageHandler(self.engine.on_owner_outgoing, filters.private & filters.outgoing), group=0)
        self.client.add_handler(MessageHandler(self.engine.on_incoming, filters.private & filters.incoming), group=1)

        await self.client.start()
        me = await self.client.get_me()
        self.me_id = me.id
        RUNTIME["connected"] = True
        log.info("Userbot ishga tushdi: %s (ID %s)", display_name(me), me.id)

        await self.store.cloud_load(self.client, self.me_id)
        await idle()
        await self.client.stop()
        return 0


def main() -> None:
    start_keepalive_server()
    start_self_ping()
    app = UserbotApp()
    LOOP.run_until_complete(app.run())


if __name__ == "__main__":
    main()
