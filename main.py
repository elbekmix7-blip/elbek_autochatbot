#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║   SMART CHAT AUTOMATION & MANAGEMENT SYSTEM                          ║
║   Userbot (24/7 avto-javob) + Shaxsiy Assistant Bot (Inline panel)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import getpass
import html
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

if sys.version_info < (3, 10):
    sys.exit("❌ Python 3.10 yoki yuqori versiya talab qilinadi.")

try:
    import uvloop  # type: ignore
    uvloop.install()
except Exception:
    pass

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

try:
    import pyrogram.errors as perr
    from pyrogram import Client, filters, idle
    from pyrogram.enums import ChatAction, ParseMode
    from pyrogram.errors import FloodWait, MessageNotModified, RPCError
    from pyrogram.handlers import CallbackQueryHandler, MessageHandler, RawUpdateHandler
    from pyrogram.raw import types as raw_types
    from pyrogram.types import (
        CallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Message,
    )
except ImportError:
    sys.exit("❌ Pyrogram o'rnatilmagan. Buyruq: pip install -U pyrogram tgcrypto")

try:
    from flask import Flask, jsonify
except ImportError:
    sys.exit("❌ Flask o'rnatilmagan. Buyruq: pip install -U flask")

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = Path(os.getenv("STATE_PATH") or (BASE_DIR / "state.json"))
LOG_FILE = BASE_DIR / "smartchat.log"
LOCK_FILE = BASE_DIR / ".smartchat.pid"

WEB_PORT = int(os.getenv("PORT") or 7860)
STARTED_AT = time.time()

FIRST_REPLY = (
    "Salom, men Elbekning avtomatlashgan botiman! 🤖 Hozir band edilar, "
    "xabaringizni yozib qoldirishingiz mumkin. Imkon topilishi bilan o‘zlari "
    "javob beradilar.\n\n"
    "Ungacha foydali yordamchimizdan foydalanib turing: https://t.me/EduMindUz_bot"
)
SECOND_REPLY = (
    "Xabaringiz uchun rahmat! 🙏 Elbek imkon topilishi bilan o‘zlari javob "
    "beradilar.\n\n"
    "Shu orada EduMind yordamchisidan foydalanib turishingiz mumkin: "
    "https://t.me/EduMindUz_bot"
)

SYSTEM_USER_IDS = {777000, 42777, 1087968824}

MODES: dict[str, tuple[str, str, str]] = {
    "selective": ("🎯", "TANLANGANLAR", "faqat /add bilan qo‘shilgan odamlarga javob beradi"),
    "all": ("🌍", "HAMMASI", "yozgan har bir kishiga javob beradi"),
    "unknown": ("👤", "NOTANISHLAR", "kontaktda yo‘q odamlarga javob beradi"),
    "contacts": ("📇", "KONTAKTLAR", "faqat kontaktlaringizga javob beradi"),
}

_ACTION_SPEC = [
    ("typing", "TYPING", "⌨️ YOZYAPTI"),
    ("upload_photo", "UPLOAD_PHOTO", "📷 RASM YUKLAYAPTI"),
    ("upload_document", "UPLOAD_DOCUMENT", "📎 FAYL YUKLAYAPTI"),
    ("record_audio", "RECORD_AUDIO", "🎙 OVOZ YOZYAPTI"),
    ("record_video", "RECORD_VIDEO", "🎥 VIDEO YOZYAPTI"),
    ("upload_video", "UPLOAD_VIDEO", "📹 VIDEO YUKLAYAPTI"),
    ("choose_sticker", "CHOOSE_STICKER", "🎭 STIKER TANLAYAPTI"),
    ("playing", "PLAYING", "🎮 O‘YNAYAPTI"),
]
ACTIONS: dict[str, tuple[Any, str]] = {
    key: (getattr(ChatAction, attr), label)
    for key, attr, label in _ACTION_SPEC
    if getattr(ChatAction, attr, None) is not None
}
ACTION_KEYS = list(ACTIONS)

DEFAULT_STEPS = [
    {"action": "upload_photo", "seconds": 3},
    {"action": "upload_document", "seconds": 3},
    {"action": "typing", "seconds": 3},
]

DANGEROUS_EXTS = {
    ".apk", ".xapk", ".apks", ".exe", ".bat", ".cmd", ".scr", ".com", ".pif",
    ".msi", ".msp", ".jar", ".vbs", ".vbe", ".jse", ".wsf", ".ps1", ".lnk",
    ".dll", ".reg", ".hta", ".cpl", ".sh", ".bin", ".apkm",
}
DANGEROUS_MIMES = {
    "application/vnd.android.package-archive",
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-dosexec",
    "application/x-bat",
    "application/x-msi",
    "application/java-archive",
    "application/x-sh",
}
SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rebrand.ly", "shorturl.at", "tiny.cc", "rb.gy", "v.gd",
    "s.id", "clck.ru", "vk.cc", "lnkd.in", "bl.ink", "soo.gd", "u.to",
}
BAD_TLDS = {
    "xyz", "top", "click", "tk", "ml", "ga", "cf", "gq", "zip", "mov", "icu",
    "buzz", "work", "country", "kim", "loan", "men", "racing", "party",
    "download", "stream", "gdn", "review", "science", "bid",
}
PHISH_KEYWORDS = (
    "free-nitro", "airdrop", "giftcard", "claim-reward", "wallet-connect",
    "seed-phrase", "verify-account", "account-verify", "login-secure",
    "freegift", "free-premium", "crypto-giveaway",
)
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"'«»]+")
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
DOMAINISH_RE = re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b")

DEFAULT_STATE: dict[str, Any] = {
    "credentials": {"api_id": 0, "api_hash": "", "bot_token": ""},
    "owner_id": 6841567673,
    "enabled": True,
    "mode": "selective",
    "away": False,
    "away_until": 0,
    "cooldown": 20,
    "protect_seconds": 600,
    "statuses": {"enabled": True, "steps": copy.deepcopy(DEFAULT_STEPS)},
    "selected": {},
    "users": {},
    "quarantine": {},
    "security": {
        "ext_filter": True,
        "link_filter": True,
        "flood_filter": True,
        "flood_limit": 7,
        "flood_window": 10,
        "bad_domains": [],
        "trusted_domains": [
            "t.me", "telegram.me", "telegram.org", "telegra.ph", "youtube.com",
            "youtu.be", "google.com", "github.com", "wikipedia.org",
            "instagram.com", "facebook.com", "linkedin.com", "x.com",
            "twitter.com",
        ],
    },
    "stats": {"replies_total": 0, "first_replies": 0, "second_replies": 0,
              "quarantined_total": 0, "started_at": 0},
}

COOLDOWN_PRESETS = [10, 20, 30, 60, 120, 300, 900, 1800, 3600, 21600]
PROTECT_PRESETS = [120, 300, 600, 1800, 3600, 10800]
MAX_STEPS = 6

log = logging.getLogger("smartchat")


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.handlers.clear()
    log.addHandler(console)
    try:
        fileh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fileh.setFormatter(fmt)
        log.addHandler(fileh)
    except OSError as exc:
        print(f"⚠️ Log fayli ochilmadi ({exc}); faqat konsolga yoziladi.")
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)


web_app = Flask(__name__)


@web_app.route("/")
def web_index():
    up = int(time.time() - STARTED_AT)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Smart Chat Automation</title></head>"
        "<body style='font-family:system-ui,sans-serif;text-align:center;margin-top:12vh'>"
        "<h1>🤖 Smart Chat Automation</h1>"
        "<p>✅ Tizim ishlayapti.</p>"
        f"<p>⏳ Ish vaqti: {up // 3600} soat {up % 3600 // 60} daqiqa</p>"
        "</body></html>"
    )


@web_app.route("/health")
@web_app.route("/ping")
def web_health():
    return jsonify(ok=True, uptime=int(time.time() - STARTED_AT))


def _run_web() -> None:
    try:
        web_app.run(host="0.0.0.0", port=WEB_PORT, threaded=True, use_reloader=False)
    except Exception as exc:
        print(f"❌ Veb-server xatosi: {exc!r}")


def _self_ping() -> None:
    host = (os.getenv("SPACE_HOST") or "").strip()
    url = f"https://{host}/health" if host else f"http://127.0.0.1:{WEB_PORT}/health"
    while True:
        time.sleep(240)
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                resp.read(64)
        except Exception:
            pass


def keep_alive() -> None:
    threading.Thread(target=_run_web, name="web-server", daemon=True).start()
    threading.Thread(target=_self_ping, name="self-ping", daemon=True).start()
    print(f"🌐 Veb-server 0.0.0.0:{WEB_PORT} da ishga tushdi (keep_alive).")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def fill_defaults(target: dict, default: dict) -> None:
    for key, value in default.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            fill_defaults(target[key], value)


def fmt_dur(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} soniya"
    if seconds < 3600:
        return f"{seconds // 60} daqiqa"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} soat"
    return f"{seconds // 60} daqiqa"


def short_dur(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def parse_duration(text: str) -> Optional[int]:
    m = re.fullmatch(r"\s*(\d+)\s*([smhSMH]?)\s*", text or "")
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2).lower()
    return value * {"": 1, "s": 1, "m": 60, "h": 3600}[unit]


def display_name(user: Any) -> str:
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    username = getattr(user, "username", None)
    return f"@{username}" if username else f"ID {getattr(user, 'id', '?')}"


def utf16_slice(text: str, offset: int, length: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le", "ignore")


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows]
    )


def ts_fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "—"


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> None:
        if os.name != "nt" and self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
                if pid != os.getpid():
                    os.kill(pid, 0)
                    sys.exit(f"❌ Tizim allaqachon ishlayapti (PID {pid}).")
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                pass
        with contextlib.suppress(OSError):
            self.path.write_text(str(os.getpid()))

    def release(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.d: dict[str, Any] = {}
        self.dirty = False
        self._wlock: Optional[asyncio.Lock] = None

    def load(self) -> None:
        loaded: dict[str, Any] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text("utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("state.json ildizi obyekt emas")
            except Exception as exc:
                backup = self.path.with_name(f"state.json.corrupt-{int(time.time())}")
                with contextlib.suppress(OSError):
                    self.path.rename(backup)
                log.error("state.json buzilgan (%s). Nusxa: %s", exc, backup.name)
                loaded = {}
        fill_defaults(loaded, DEFAULT_STATE)
        self.d = loaded
        self._sanitize()

    def _sanitize(self) -> None:
        d = self.d
        if d["mode"] not in MODES:
            d["mode"] = "selective"
        d["cooldown"] = max(0, min(int(d.get("cooldown", 20) or 0), 7 * 86400))
        d["protect_seconds"] = max(30, min(int(d.get("protect_seconds", 600) or 600), 86400))
        steps = []
        for step in d["statuses"].get("steps", []):
            if isinstance(step, dict) and step.get("action") in ACTIONS:
                secs = max(1, min(int(step.get("seconds", 3) or 3), 60))
                steps.append({"action": step["action"], "seconds": secs})
        d["statuses"]["steps"] = steps[:MAX_STEPS] or copy.deepcopy(DEFAULT_STEPS)
        sec = d["security"]
        sec["flood_limit"] = max(3, min(int(sec.get("flood_limit", 7)), 30))
        sec["flood_window"] = max(3, min(int(sec.get("flood_window", 10)), 120))
        if not d["stats"].get("started_at"):
            d["stats"]["started_at"] = time.time()

    def touch(self) -> None:
        self.dirty = True

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def save_sync(self) -> None:
        self._atomic_write(self.path, json.dumps(self.d, ensure_ascii=False, indent=2))
        self.dirty = False

    async def flush(self) -> None:
        if self._wlock is None:
            self._wlock = asyncio.Lock()
        async with self._wlock:
            if not self.dirty:
                return
            payload = json.dumps(self.d, ensure_ascii=False, indent=2)
            self.dirty = False
            try:
                await asyncio.to_thread(self._atomic_write, self.path, payload)
            except Exception as exc:
                self.dirty = True
                log.error("state.json yozilmadi: %s", exc)

    async def autosave_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            await self.flush()

    def user_rec(self, uid: int) -> dict[str, Any]:
        rec = self.d["users"].setdefault(str(uid), {})
        rec.setdefault("stage", 0)
        rec.setdefault("last_reply", 0.0)
        rec.setdefault("owner_ts", 0.0)
        rec.setdefault("first_seen", time.time())
        return rec


def ensure_credentials(store: StateStore) -> dict[str, Any]:
    creds = store.d["credentials"]
    env_api_id = (os.getenv("TG_API_ID") or "").strip()
    env_api_hash = (os.getenv("TG_API_HASH") or "").strip()
    env_token = (os.getenv("TG_BOT_TOKEN") or "").strip()
    session_string = (os.getenv("STRING_SESSION") or "").strip()

    api_id = env_api_id or creds.get("api_id") or 0
    api_hash = env_api_hash or creds.get("api_hash") or ""
    token = env_token or creds.get("bot_token") or ""

    if api_id and not str(api_id).isdigit():
        sys.exit("❌ TG_API_ID faqat raqamlardan iborat bo'lishi kerak.")

    missing = [
        name for name, val in (
            ("TG_API_ID", api_id), ("TG_API_HASH", api_hash), ("TG_BOT_TOKEN", token),
        ) if not val
    ]
    interactive = sys.stdin is not None and sys.stdin.isatty()

    if missing and not interactive:
        sys.exit(
            "❌ Quyidagi muhit o'zgaruvchilari topilmadi: "
            + ", ".join(missing)
        )

    changed = False
    if missing:
        print("\n🔐 Birinchi sozlash\n")
    while not api_id:
        raw = input("API_ID: ").strip()
        if raw.isdigit():
            api_id, changed = int(raw), True
    while not api_hash:
        api_hash, changed = getpass.getpass("API_HASH: ").strip(), True
    while not re.fullmatch(r"\d{5,}:[\w-]{20,}", token or ""):
        if not interactive:
            sys.exit("❌ TG_BOT_TOKEN formati noto'g'ri.")
        token, changed = getpass.getpass("BOT_TOKEN: ").strip(), True

    if not session_string:
        sys.exit("❌ STRING_SESSION topilmadi.")

    result = {
        "api_id": int(api_id),
        "api_hash": str(api_hash),
        "bot_token": str(token),
    }
    if changed and not (env_api_id and env_api_hash and env_token):
        store.d["credentials"] = result
        store.save_sync()
    result["session_string"] = session_string
    return result


HELP_TEXT = (
    "📖 <b>BUYRUQLAR</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "/panel — boshqaruv paneli\n"
    "/on · /off — botni yoqish / o‘chirish\n"
    "/away [daqiqa|off] — band rejimi\n"
    "/mode [selective|all|unknown|contacts]\n"
    "/cooldown &lt;10 | 30s | 5m | 1h&gt;\n"
    "/add &lt;id yoki @username&gt; — tanlanganlarga qo‘shish\n"
    "/remove &lt;id yoki @username&gt;\n"
    "/list — tanlanganlar ro‘yxati\n"
    "/quarantine — karantin ro‘yxati\n"
    "/release &lt;id|all&gt; — karantindan chiqarish\n"
    "/domain add|del &lt;domen&gt; — qora ro‘yxat\n"
    "/status — holat\n"
    "/cancel — kutilayotgan amalni bekor qilish"
)


class SmartChatSystem:
    def __init__(self, store: StateStore, creds: dict[str, Any]) -> None:
        self.store = store
        self.creds = creds
        self.userbot: Client = None  # type: ignore[assignment]
        self.bot: Client = None  # type: ignore[assignment]
        self.me = None
        self.bot_me = None
        self.owner_id = 6841567673  # Ziyodullayev Elbek ID raqami oldindan belgilanadi
        self.started = time.time()

        self.tasks: set[asyncio.Task] = set()
        self.locks: dict[int, asyncio.Lock] = {}
        self.flood: dict[int, deque] = {}
        self.last_group: dict[int, Any] = {}
        self.owner_activity: dict[int, float] = {}
        self.inflight: dict[int, int] = {}
        self.own_ids: deque = deque(maxlen=1000)
        self.pending: Optional[str] = None
        self.fatal_event = asyncio.Event()

        self.owner_filter = filters.create(self._owner_check, "OwnerOnly")
        self.commands = {
            "start": self.cmd_panel, "panel": self.cmd_panel,
            "on": self.cmd_on, "off": self.cmd_off,
            "away": self.cmd_away, "mode": self.cmd_mode,
            "cooldown": self.cmd_cooldown,
            "add": self.cmd_add, "remove": self.cmd_remove, "rm": self.cmd_remove,
            "list": self.cmd_list,
            "quarantine": self.cmd_quarantine, "karantin": self.cmd_quarantine,
            "release": self.cmd_release,
            "domain": self.cmd_domain,
            "status": self.cmd_status, "help": self.cmd_help,
            "cancel": self.cmd_cancel,
        }

    @property
    def d(self) -> dict[str, Any]:
        return self.store.d

    def touch(self) -> None:
        self.store.touch()

    def spawn(self, coro, name: str = "task") -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.error("Fon vazifasi xatosi [%s]: %r", task.get_name(), exc, exc_info=exc)

    async def tg(self, func, *args, retries: int = 3, **kwargs):
        for _ in range(retries):
            try:
                return await func(*args, **kwargs)
            except FloodWait as exc:
                wait = int(getattr(exc, "value", None) or getattr(exc, "x", None) or 5)
                log.warning("FloodWait: %s soniya kutamiz", wait)
                await asyncio.sleep(wait + 1)
        raise RuntimeError("FloodWait: urinishlar tugadi")

    async def run(self) -> None:
        self.userbot = Client(
            "userbot",
            api_id=self.creds["api_id"],
            api_hash=self.creds["api_hash"],
            session_string=self.creds["session_string"],
            in_memory=True,
            sleep_threshold=60,
        )
        self.bot = Client(
            "assistant",
            api_id=self.creds["api_id"],
            api_hash=self.creds["api_hash"],
            bot_token=self.creds["bot_token"],
            in_memory=True,
            sleep_threshold=60,
        )
        self._register_handlers()
        try:
            await self.userbot.start()
            self.me = await self.userbot.get_me()
            self.owner_id = self.me.id
            self.d["owner_id"] = self.owner_id
            self.touch()
            await self.bot.start()
            self.bot_me = await self.bot.get_me()
        except Exception:
            log.exception("Ishga tushirishda xatolik")
            await self._shutdown()
            raise

        for key, rec in self.d["users"].items():
            ts = float(rec.get("owner_ts") or 0)
            if ts:
                self.owner_activity[int(key)] = ts

        log.info("✅ Userbot: %s (id=%s)", display_name(self.me), self.me.id)
        log.info("✅ Assistant bot: @%s", self.bot_me.username)

        self.spawn(self.store.autosave_loop(), "autosave")
        self.spawn(self.housekeeping_loop(), "housekeeping")
        self.spawn(self.watchdog_loop(), "watchdog")
        self.spawn(self._hello_owner(), "hello")

        idle_task = asyncio.create_task(idle())
        fatal_task = asyncio.create_task(self.fatal_event.wait())
        try:
            await asyncio.wait({idle_task, fatal_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (idle_task, fatal_task):
                t.cancel()
            await self._shutdown()

    async def _shutdown(self) -> None:
        log.info("To‘xtatilmoqda…")
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await self.store.flush()
            self.store.dirty = True
            await self.store.flush()
        except Exception:
            log.exception("State saqlashda xatolik")
        for client in (self.bot, self.userbot):
            if client is not None:
                with contextlib.suppress(Exception):
                    if client.is_connected:
                        await client.stop()
        log.info("👋 Tizim to‘xtadi.")

    async def _hello_owner(self) -> None:
        text, markup = self.view_home()
        try:
            await self.bot.send_message(
                self.owner_id, "✅ <b>Tizim ishga tushdi.</b>\n\n" + text,
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            log.warning("Egasiga salom yuborilmadi: %s", exc)

    def _register_handlers(self) -> None:
        ub, bt = self.userbot, self.bot
        ub.add_handler(RawUpdateHandler(self.on_raw), group=-10)
        ub.add_handler(
            MessageHandler(self.on_incoming, filters.private & filters.incoming & ~filters.service),
            group=0,
        )
        ub.add_handler(
            MessageHandler(self.on_outgoing, filters.private & filters.outgoing & ~filters.service),
            group=1,
        )
        bt.add_handler(
            MessageHandler(
                self.on_command,
                filters.private & self.owner_filter & filters.command(list(self.commands)),
            ),
            group=0,
        )
        bt.add_handler(
            MessageHandler(
                self.on_text,
                filters.private & self.owner_filter & ~filters.regex(r"^/"),
            ),
            group=1,
        )
        bt.add_handler(CallbackQueryHandler(self.on_callback, self.owner_filter), group=0)
        bt.add_handler(
            MessageHandler(self.on_stranger, filters.private & ~self.owner_filter), group=5
        )

    async def _owner_check(self, _flt, _client, update) -> bool:
        user = getattr(update, "from_user", None)
        if not user:
            return False
        # Elbekning aniq ID raqami (6841567673) yoki owner_id tekshiriladi
        return user.id == 6841567673 or (self.owner_id and user.id == self.owner_id)

    async def on_stranger(self, _client, message: Message) -> None:
        user = message.from_user
        log.info("Begona foydalanuvchi assistant botga yozdi: %s", getattr(user, "id", "?"))

    async def housekeeping_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                self.prune()
            except Exception:
                log.exception("prune xatosi")

    def prune(self) -> None:
        now, mono = time.time(), time.monotonic()
        for k, v in list(self.owner_activity.items()):
            if now - v > 86400:
                del self.owner_activity[k]
        for uid, dq in list(self.flood.items()):
            if not dq or mono - dq[-1] > 300:
                del self.flood[uid]
        for uid, lock in list(self.locks.items()):
            if not lock.locked():
                del self.locks[uid]
        for uid in list(self.last_group):
            if uid not in self.flood:
                del self.last_group[uid]
        selected = self.d["selected"]
        for key, rec in list(self.d["users"].items()):
            latest = max(rec.get("last_reply", 0), rec.get("owner_ts", 0), rec.get("first_seen", 0))
            if rec.get("stage", 0) == 0 and key not in selected and now - latest > 60 * 86400:
                del self.d["users"][key]
                self.touch()
        self.away_active()

    async def watchdog_loop(self) -> None:
        fatal = tuple(
            getattr(perr, n) for n in
            ("AuthKeyUnregistered", "SessionRevoked", "UserDeactivated", "UserDeactivatedBan")
            if hasattr(perr, n)
        )
        while True:
            await asyncio.sleep(300)
            try:
                await self.userbot.get_me()
            except fatal as exc:
                log.critical("Session yaroqsiz (%r).", exc)
                self.fatal_event.set()
                return
            except Exception as exc:
                log.warning("Watchdog: ulanish muammosi (%r)", exc)

    async def on_raw(self, _client, update, _users, _chats) -> None:
        if isinstance(update, raw_types.UpdateReadHistoryInbox):
            peer = update.peer
            if isinstance(peer, raw_types.PeerUser):
                self.owner_activity[peer.user_id] = time.time()

    def owner_active(self, uid: int) -> bool:
        last = self.owner_activity.get(uid, 0.0)
        return (time.time() - last) < self.d["protect_seconds"]

    async def on_outgoing(self, _client, message: Message) -> None:
        chat = message.chat
        if chat is None or (self.me and chat.id == self.me.id):
            return
        msg_id = getattr(message, "id", None) or getattr(message, "message_id", None)
        if self.inflight.get(chat.id, 0) > 0 or (chat.id, msg_id) in self.own_ids:
            return
        now = time.time()
        self.owner_activity[chat.id] = now
        rec = self.store.user_rec(chat.id)
        rec["owner_ts"] = now
        rec["stage"] = 0
        rec["last_reply"] = 0.0
        self.touch()

    async def on_incoming(self, _client, message: Message) -> None:
        self.spawn(self.process_incoming(message), "incoming")

    def away_active(self) -> bool:
        d = self.d
        if not d["away"]:
            return False
        until = d["away_until"]
        if until and time.time() >= until:
            d["away"], d["away_until"] = False, 0
            self.touch()
            return False
        return True

    def eligible(self, user) -> bool:
        if self.away_active():
            return True
        mode = self.d["mode"]
        is_contact = bool(getattr(user, "is_contact", False))
        if mode == "all":
            return True
        if mode == "selective":
            return str(user.id) in self.d["selected"]
        if mode == "unknown":
            return not is_contact
        if mode == "contacts":
            return is_contact
        return False

    async def process_incoming(self, message: Message) -> None:
        try:
            await self._process_incoming(message)
        except RPCError as exc:
            log.warning("Telegram xatosi (incoming): %s", exc)
        except Exception:
            log.exception("process_incoming xatosi")

    async def _process_incoming(self, message: Message) -> None:
        d = self.d
        if not d["enabled"]:
            return
        user = message.from_user
        if (not user or user.is_bot or getattr(user, "is_self", False)
                or user.id in SYSTEM_USER_IDS):
            return
        uid = user.id
        chat_id = message.chat.id

        if str(uid) in d["quarantine"]:
            return
        if self.owner_active(uid):
            return

        reason = self.flood_check(uid, message) or self.scan_message(message)
        if reason:
            await self.quarantine_user(user, reason, message)
            return

        if not self.eligible(user):
            return

        lock = self.locks.setdefault(uid, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            rec = self.store.user_rec(uid)
            rec["name"] = display_name(user)
            stage = int(rec["stage"])
            if stage >= 2:
                return
            if time.time() - float(rec["last_reply"]) < d["cooldown"]:
                return
            await self.run_autoreply(chat_id, uid, rec, stage)

    async def run_autoreply(self, chat_id: int, uid: int, rec: dict, stage: int) -> None:
        self.inflight[chat_id] = self.inflight.get(chat_id, 0) + 1
        try:
            st = self.d["statuses"]
            if st["enabled"]:
                for step in list(st["steps"]):
                    if not await self.show_action(chat_id, uid, step["action"], step["seconds"]):
                        return
            if self.owner_active(uid) or str(uid) in self.d["quarantine"]:
                return
            text = FIRST_REPLY if stage == 0 else SECOND_REPLY
            sent = await self.tg(
                self.userbot.send_message, chat_id, text, parse_mode=ParseMode.DISABLED
            )
            sent_id = getattr(sent, "id", None) or getattr(sent, "message_id", None)
            self.own_ids.append((chat_id, sent_id))
            rec["stage"] = stage + 1
            rec["last_reply"] = time.time()
            stats = self.d["stats"]
            stats["replies_total"] += 1
            stats["first_replies" if stage == 0 else "second_replies"] += 1
            self.touch()
        finally:
            self.inflight[chat_id] = max(0, self.inflight.get(chat_id, 1) - 1)

    async def show_action(self, chat_id: int, uid: int, action_key: str, seconds: int) -> bool:
        action = ACTIONS[action_key][0]
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        last = -10.0
        while True:
            now = loop.time()
            if now >= end:
                return True
            if self.owner_active(uid) or not self.d["enabled"]:
                with contextlib.suppress(Exception):
                    await self.userbot.send_chat_action(chat_id, ChatAction.CANCEL)
                return False
            if now - last >= 4.0:
                await self.tg(self.userbot.send_chat_action, chat_id, action)
                last = now
            await asyncio.sleep(min(0.5, max(0.01, end - loop.time())))

    def flood_check(self, uid: int, message: Message) -> Optional[str]:
        sec = self.d["security"]
        if not sec["flood_filter"]:
            return None
        group = getattr(message, "media_group_id", None)
        if group and self.last_group.get(uid) == group:
            return None
        self.last_group[uid] = group
        dq = self.flood.setdefault(uid, deque(maxlen=64))
        now = time.monotonic()
        dq.append(now)
        while dq and now - dq[0] > sec["flood_window"]:
            dq.popleft()
        if len(dq) >= sec["flood_limit"]:
            return f"Flood: {len(dq)} ta xabar {sec['flood_window']} soniyada"
        return None

    def scan_message(self, message: Message) -> Optional[str]:
        sec = self.d["security"]
        if sec["ext_filter"]:
            reason = self.check_file(message)
            if reason:
                return reason
        if sec["link_filter"]:
            reason = self.check_links(message)
            if reason:
                return reason
        return None

    @staticmethod
    def check_file(message: Message) -> Optional[str]:
        for attr in ("document", "video", "audio", "animation", "voice", "video_note"):
            media = getattr(message, attr, None)
            if not media:
                continue
            name = (getattr(media, "file_name", None) or "").strip().lower()
            mime = (getattr(media, "mime_type", None) or "").lower()
            if name:
                exts = {"." + part for part in name.split(".")[1:] if part}
                bad = exts & DANGEROUS_EXTS
                if bad:
                    return f"Xavfli fayl: {name[:60]} ({sorted(bad)[0]})"
            if mime in DANGEROUS_MIMES:
                return f"Xavfli fayl turi: {mime}"
        return None

    def check_links(self, message: Message) -> Optional[str]:
        text = message.text or message.caption or ""
        entities = list(message.entities or []) + list(message.caption_entities or [])
        urls: list[str] = []
        for ent in entities:
            etype = str(getattr(ent.type, "name", ent.type)).upper()
            if etype == "TEXT_LINK" and getattr(ent, "url", None):
                shown = utf16_slice(text, ent.offset, ent.length)
                if DOMAINISH_RE.search(shown):
                    shown_host = self._host_of(shown)
                    real_host = self._host_of(ent.url)
                    if shown_host and real_host and shown_host != real_host \
                            and not real_host.endswith("." + shown_host):
                        return f"Soxta havola: «{shown[:40]}» aslida {real_host} ga olib boradi"
                urls.append(ent.url)
            elif etype == "URL":
                urls.append(utf16_slice(text, ent.offset, ent.length))
        urls.extend(URL_RE.findall(text))
        seen = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            reason = self.check_url(url)
            if reason:
                return reason
        return None

    @staticmethod
    def _host_of(raw: str) -> str:
        url = raw.strip()
        if not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", url):
            url = "http://" + url
        try:
            host = (urlparse(url).hostname or "").lower().strip(".")
        except ValueError:
            return ""
        return host[4:] if host.startswith("www.") else host

    @staticmethod
    def _host_in(host: str, domains: list[str]) -> bool:
        return any(host == dom or host.endswith("." + dom) for dom in domains)

    def check_url(self, raw: str) -> Optional[str]:
        url = raw.strip().rstrip(").,;!?»")
        if not url:
            return None
        if not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", url):
            url = "http://" + url
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().strip(".")
        except ValueError:
            return "Noto‘g‘ri formatdagi havola"
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        sec = self.d["security"]
        if self._host_in(host, sec["bad_domains"]):
            return f"Qora ro‘yxatdagi domen: {host}"
        if self._host_in(host, sec["trusted_domains"]):
            return None
        if host in SHORTENERS:
            return f"Qisqartirilgan havola: {host}"
        if IP_RE.fullmatch(host):
            return f"IP manzilli havola: {host}"
        if "xn--" in host:
            return f"Punycode domen: {host}"
        if host.rsplit(".", 1)[-1] in BAD_TLDS:
            return f"Shubhali domen zonasi: {host}"
        low = url.lower()
        for kw in PHISH_KEYWORDS:
            if kw in low:
                return f"Fishing belgisi («{kw}»): {host}"
        return None

    async def quarantine_user(self, user, reason: str, message: Message) -> None:
        uid = user.id
        snippet = (message.text or message.caption or "")[:80]
        self.d["quarantine"][str(uid)] = {
            "name": display_name(user),
            "username": user.username or "",
            "reason": reason,
            "ts": time.time(),
        }
        self.d["stats"]["quarantined_total"] += 1
        self.touch()

        uname = f" (@{esc(user.username)})" if user.username else ""
        text = (
            "🚨 <b>KARANTIN</b>\n━━━━━━━━━━━━━━━\n"
            f"👤 {esc(display_name(user))}{uname}\n🆔 <code>{uid}</code>\n"
            f"⚠️ Sabab: <b>{esc(reason)}</b>\n"
        )
        if snippet:
            text += f"💬 Xabar: <i>{esc(snippet)}</i>\n"
        text += "\nℹ️ Unga javob yozilmaydi."
        markup = kb([
            [("✅ Karantindan chiqarish", f"nq:rel:{uid}"), ("🚫 Bloklash", f"nq:blk:{uid}")],
            [("🗑 Yopish", "nq:ok")],
        ])
        await self.notify_owner(text, markup)

    async def notify_owner(self, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> None:
        try:
            await self.tg(
                self.bot.send_message, self.owner_id, text,
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
        except Exception:
            with contextlib.suppress(Exception):
                await self.tg(self.userbot.send_message, "me", text, parse_mode=ParseMode.HTML)

    def steps_summary(self, short: bool = True) -> str:
        parts = []
        for step in self.d["statuses"]["steps"]:
            label = ACTIONS[step["action"]][1]
            emoji = label.split(" ", 1)[0]
            parts.append(f"{emoji} {step['seconds']}s" if short else f"{label} — {step['seconds']}s")
        return " ➜ ".join(parts) if short else "\n".join(f"{i}) {p}" for i, p in enumerate(parts, 1))

    def view_home(self):
        d = self.d
        on = d["enabled"]
        away = self.away_active()
        m_emoji, m_name, _ = MODES[d["mode"]]
        away_txt = "🟠 <b>YOQILGAN</b>" if away else "⚪ o‘chiq"
        if away and d["away_until"]:
            away_txt += f" ({fmt_dur(max(1, int(d['away_until'] - time.time())))} qoldi)"
        status_txt = "🟢 <b>YOQILGAN</b>" if on else "🔴 <b>O‘CHIRILGAN</b>"
        fake = "🟢 yoqilgan" if d["statuses"]["enabled"] else "🔴 o‘chiq"
        text = (
            "🤖 <b>SMART CHAT AUTOMATION</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🔌 Holat: {status_txt}\n"
            f"🏖 Band rejimi: {away_txt}\n"
            f"🎯 Rejim: {m_emoji} <b>{m_name}</b>\n"
            f"⏱ Cooldown: <b>{fmt_dur(d['cooldown'])}</b>\n"
            f"🎬 Statuslar ({fake}): {self.steps_summary()}\n"
            f"🛡 Himoya oynasi: <b>{fmt_dur(d['protect_seconds'])}</b>\n"
            f"📋 Tanlanganlar: <b>{len(d['selected'])}</b>  ·  🚧 Karantin: <b>{len(d['quarantine'])}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
        away_btn = "🟠  BAND REJIMI: YOQILGAN" if away else "⚪  BAND REJIMI: O‘CHIQ"
        markup = kb([
            [(("🟢  BOT: YOQILGAN" if on else "🔴  BOT: O‘CHIRILGAN"), "tgl")],
            [(away_btn, "away")],
            [(f"🎯  REJIM: {m_name}", "mode")],
            [(f"⏱  COOLDOWN: {fmt_dur(d['cooldown'])}", "cd")],
            [(f"🎬  FAKE STATUSLAR: {self.steps_summary()}", "st")],
            [(f"📋  RO‘YXAT ({len(d['selected'])})", "ls"),
             (f"🚧  KARANTIN ({len(d['quarantine'])})", "qr")],
            [("🛡  XAVFSIZLIK", "sec"), ("📊  STATISTIKA", "stats")],
            [("🔄  YANGILASH", "home")],
        ])
        return text, markup

    def view_mode(self):
        cur = self.d["mode"]
        lines = ["🎯 <b>ISHLASH REJIMI</b>\n━━━━━━━━━━━━━━━━━━"]
        rows = []
        for key, (emoji, name, desc) in MODES.items():
            mark = "✅ " if key == cur else ""
            lines.append(f"{emoji} <b>{name}</b> — {desc}")
            rows.append([(f"{mark}{emoji}  {name}", f"mode:set:{key}")])
        rows.append([("🔙  ORQAGA", "home")])
        return "\n".join(lines), kb(rows)

    def view_cooldown(self):
        cur = self.d["cooldown"]
        text = (
            "⏱ <b>COOLDOWN</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Hozirgi: <b>{fmt_dur(cur)}</b>\n\n"
        )
        rows, row = [], []
        for sec in COOLDOWN_PRESETS:
            row.append((("✅ " if sec == cur else "") + short_dur(sec), f"cd:set:{sec}"))
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([("✍️  BOSHQA QIYMAT", "cd:custom")])
        rows.append([("🔙  ORQAGA", "home")])
        return text, kb(rows)

    def view_statuses(self):
        st = self.d["statuses"]
        steps = st["steps"]
        text = (
            "🎬 <b>FAKE STATUSLAR</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Holat: {'🟢 yoqilgan' if st['enabled'] else '🔴 o‘chiq'}\n\n"
            f"{self.steps_summary(short=False)}\n"
        )
        rows = [[(("🟢  STATUSLAR: YOQILGAN" if st["enabled"] else "🔴  STATUSLAR: O‘CHIQ"), "st:tgl")]]
        for i, step in enumerate(steps):
            rows.append([(f"{i + 1}️⃣  {ACTIONS[step['action']][1]}", f"st:act:{i}")])
            rows.append([("➖", f"st:sec:{i}:-1"), (f"⏳ {step['seconds']}s", "noop"), ("➕", f"st:sec:{i}:1")])
        ctrl = []
        if len(steps) < MAX_STEPS:
            ctrl.append(("➕ Qadam", "st:add"))
        if len(steps) > 1:
            ctrl.append(("🗑 Oxirgisi", "st:del"))
        if ctrl:
            rows.append(ctrl)
        rows.append([("♻️  STANDART", "st:rst")])
        rows.append([("🔙  ORQAGA", "home")])
        return text, kb(rows)

    def view_list(self):
        sel = self.d["selected"]
        text = "📋 <b>TANLANGANLAR RO‘YXATI</b>\n━━━━━━━━━━━━━━━━━━\nJami: <b>{len(sel)}</b>\n"
        rows = []
        for uid, name in list(sel.items())[:15]:
            rows.append([(f"❌  {name[:26]}", f"ls:rm:{uid}")])
        rows.append([("➕  QO‘SHISH", "ls:add")])
        rows.append([("🔙  ORQAGA", "home")])
        return text, kb(rows)

    def view_quarantine(self):
        q = self.d["quarantine"]
        text = "🚧 <b>KARANTIN</b>\n━━━━━━━━━━━━━━━━━━\n"
        if not q:
            text += "<i>Karantin bo‘sh. ✨</i>"
        rows = []
        for uid, info in list(q.items())[:12]:
            text += f"\n• <b>{esc(info.get('name', uid))}</b> <code>{uid}</code>\n"
            rows.append([(f"✅  {info.get('name', uid)[:24]}", f"qr:rel:{uid}")])
        if q:
            rows.append([("🧹  HAMMASINI CHIQARISH", "qr:clr")])
        rows.append([("🔙  ORQAGA", "home")])
        return text, kb(rows)

    def view_security(self):
        sec = self.d["security"]
        def onoff(v: bool) -> str:
            return "🟢" if v else "🔴"
        text = (
            "🛡 <b>XAVFSIZLIK</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"{onoff(sec['ext_filter'])} Zararli fayllar\n"
            f"{onoff(sec['link_filter'])} Shubhali havolalar\n"
            f"{onoff(sec['flood_filter'])} Flood limit: {sec['flood_limit']}\n"
        )
        rows = [
            [(f"{onoff(sec['ext_filter'])}  FAYL FILTRI", "sec:ext")],
            [(f"{onoff(sec['link_filter'])}  HAVOLA FILTRI", "sec:lnk")],
            [(f"{onoff(sec['flood_filter'])}  FLOOD FILTRI", "sec:fld")],
            [("🔙  ORQAGA", "home")],
        ]
        return text, kb(rows)

    def view_stats(self):
        s = self.d["stats"]
        up = int(time.time() - self.started)
        text = (
            "📊 <b>STATISTIKA</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"⏳ Ish vaqti: <b>{up // 3600} soat {up % 3600 // 60} daq</b>\n"
            f"💬 Jami avto-javoblar: <b>{s['replies_total']}</b>\n"
        )
        return text, kb([[("🔄  YANGILASH", "stats")], [("🔙  ORQAGA", "home")]])

    @staticmethod
    def view_prompt(title: str, hint: str, back: str):
        return f"{title}\n━━━━━━━━━━━━━━━━━━\n{hint}", kb([[("❌  BEKOR QILISH", f"cancel:{back}")]])

    VIEWS = {
        "home": "view_home", "mode": "view_mode", "cd": "view_cooldown",
        "st": "view_statuses", "ls": "view_list", "qr": "view_quarantine",
        "sec": "view_security", "stats": "view_stats",
    }

    async def show(self, cq: CallbackQuery, view) -> None:
        text, markup = view
        try:
            await cq.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except MessageNotModified:
            pass

    async def on_callback(self, _client, cq: CallbackQuery) -> None:
        try:
            await self._on_callback(cq)
        except MessageNotModified:
            with contextlib.suppress(Exception):
                await cq.answer()
        except Exception:
            log.exception("Callback xatosi: %s", cq.data)
            with contextlib.suppress(Exception):
                await cq.answer("⚠️ Xatolik yuz berdi", show_alert=True)

    async def _on_callback(self, cq: CallbackQuery) -> None:
        d = self.d
        parts = (cq.data or "").split(":")
        route = parts[0]
        sub = parts[1] if len(parts) > 1 else ""

        if route == "noop":
            await cq.answer()
            return

        if route == "cancel":
            self.pending = None
            await cq.answer("Bekor qilindi")
            back = sub if sub in self.VIEWS else "home"
            await self.show(cq, getattr(self, self.VIEWS[back])())
            return

        if route in self.VIEWS and not sub:
            if route == "home":
                self.pending = None
            await cq.answer()
            await self.show(cq, getattr(self, self.VIEWS[route])())
            return

        if route == "tgl":
            d["enabled"] = not d["enabled"]
            self.touch()
            await cq.answer("🟢 Bot yoqildi" if d["enabled"] else "🔴 Bot o‘chirildi")
            await self.show(cq, self.view_home())

        elif route == "away":
            d["away"] = not self.away_active()
            d["away_until"] = 0
            self.touch()
            await cq.answer("🟠 Band rejimi yoqildi" if d["away"] else "⚪ Band rejimi o‘chirildi")
            await self.show(cq, self.view_home())

        elif route == "mode" and sub == "set":
            if parts[2] in MODES:
                d["mode"] = parts[2]
                self.touch()
                await cq.answer(f"{MODES[parts[2]][0]} {MODES[parts[2]][1]}")
            await self.show(cq, self.view_mode())

        elif route == "cd":
            if sub == "set":
                d["cooldown"] = max(0, int(parts[2]))
                self.touch()
                await cq.answer(f"⏱ {fmt_dur(d['cooldown'])}")
                await self.show(cq, self.view_cooldown())
            elif sub == "custom":
                self.pending = "cd"
                await cq.answer()
                await self.show(cq, self.view_prompt("✍️ <b>COOLDOWN</b>", "Qiymat yuboring: <code>45</code>", "cd"))

        elif route == "st":
            st = d["statuses"]
            steps = st["steps"]
            if sub == "tgl":
                st["enabled"] = not st["enabled"]
            elif sub == "act":
                i = int(parts[2])
                if 0 <= i < len(steps):
                    cur = ACTION_KEYS.index(steps[i]["action"])
                    steps[i]["action"] = ACTION_KEYS[(cur + 1) % len(ACTION_KEYS)]
            elif sub == "sec":
                i, delta = int(parts[2]), int(parts[3])
                if 0 <= i < len(steps):
                    steps[i]["seconds"] = max(1, min(60, steps[i]["seconds"] + delta))
            elif sub == "add" and len(steps) < MAX_STEPS:
                steps.append({"action": "typing", "seconds": 3})
            elif sub == "del" and len(steps) > 1:
                steps.pop()
            elif sub == "rst":
                st["steps"] = copy.deepcopy(DEFAULT_STEPS)
            self.touch()
            await cq.answer()
            await self.show(cq, self.view_statuses())

        elif route == "ls":
            if sub == "rm":
                removed = d["selected"].pop(parts[2], None)
                self.touch()
                await cq.answer(f"❌ {removed or 'topilmadi'} o‘chirildi")
                await self.show(cq, self.view_list())
            elif sub == "add":
                self.pending = "add"
                await cq.answer()
                await self.show(cq, self.view_prompt("➕ <b>QO‘SHISH</b>", "ID yoki @username yuboring.", "ls"))

        elif route == "qr":
            if sub == "rel":
                d["quarantine"].pop(parts[2], None)
                self.touch()
                await cq.answer("✅ Chiqarildi")
            elif sub == "clr":
                d["quarantine"].clear()
                self.touch()
                await cq.answer("🧹 Karantin tozalandi")
            await self.show(cq, self.view_quarantine())

        elif route == "sec":
            sec = d["security"]
            if sub == "ext":
                sec["ext_filter"] = not sec["ext_filter"]
            elif sub == "lnk":
                sec["link_filter"] = not sec["link_filter"]
            elif sub == "fld":
                sec["flood_filter"] = not sec["flood_filter"]
            self.touch()
            await cq.answer()
            await self.show(cq, self.view_security())
        else:
            await cq.answer()

    async def on_command(self, _client, message: Message) -> None:
        cmd = (message.command[0] if message.command else "").lower()
        args = message.command[1:] if message.command else []
        fn = self.commands.get(cmd)
        if fn:
            await fn(message, args)

    async def reply_view(self, message: Message, view) -> None:
        text, markup = view
        await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    async def cmd_panel(self, message: Message, args: list[str]) -> None:
        self.pending = None
        await self.reply_view(message, self.view_home())

    async def cmd_on(self, message: Message, args: list[str]) -> None:
        self.d["enabled"] = True
        self.touch()
        await message.reply_text("🟢 Bot yoqildi.")

    async def cmd_off(self, message: Message, args: list[str]) -> None:
        self.d["enabled"] = False
        self.touch()
        await message.reply_text("🔴 Bot o‘chirildi.")

    async def cmd_away(self, message: Message, args: list[str]) -> None:
        d = self.d
        if args and args[0].lower() in ("off", "0", "stop"):
            d["away"], d["away_until"] = False, 0
            msg = "⚪ Band rejimi o‘chirildi."
        elif args and args[0].isdigit():
            minutes = max(1, int(args[0]))
            d["away"], d["away_until"] = True, time.time() + minutes * 60
            msg = f"🟠 Band rejimi {minutes} daqiqaga yoqildi."
        else:
            d["away"] = not self.away_active()
            d["away_until"] = 0
            msg = "🟠 Band rejimi yoqildi." if d["away"] else "⚪ Band rejimi o‘chirildi."
        self.touch()
        await message.reply_text(msg)

    async def cmd_mode(self, message: Message, args: list[str]) -> None:
        if args and args[0].lower() in MODES:
            self.d["mode"] = args[0].lower()
            self.touch()
            emoji, name, desc = MODES[self.d["mode"]]
            await message.reply_text(f"{emoji} Rejim: {name} — {desc}")
        else:
            await self.reply_view(message, self.view_mode())

    async def cmd_cooldown(self, message: Message, args: list[str]) -> None:
        if args:
            secs = parse_duration(args[0])
            if secs is None:
                await message.reply_text("❌ Format: /cooldown 45 | 90s | 5m | 2h")
                return
            self.d["cooldown"] = min(secs, 7 * 86400)
            self.touch()
            await message.reply_text(f"⏱ Cooldown: {fmt_dur(self.d['cooldown'])}")
        else:
            await self.reply_view(message, self.view_cooldown())

    async def resolve_user(self, arg: str) -> tuple[int, str]:
        arg = arg.strip()
        arg = re.sub(r"(?i)^https?://t\.me/", "", arg).lstrip("@").strip("/")
        numeric = re.fullmatch(r"-?\d+", arg) is not None
        key: Any = int(arg) if numeric else arg
        try:
            user = await self.tg(self.userbot.get_users, key)
            if isinstance(user, list):
                user = user[0]
            return user.id, display_name(user)
        except Exception as exc:
            if numeric:
                return int(arg), f"ID {arg}"
            raise ValueError(f"Foydalanuvchi topilmadi: {arg}") from exc

    async def add_to_selected(self, message: Message, tokens: list[str]) -> None:
        added, failed = [], []
        for tok in tokens:
            try:
                uid, name = await self.resolve_user(tok)
                self.d["selected"][str(uid)] = name
                added.append(f"• {esc(name)} <code>{uid}</code>")
            except Exception as exc:
                failed.append(f"• {esc(tok)} — {esc(exc)}")
        self.touch()
        out = ""
        if added:
            out += "✅ <b>Qo‘shildi:</b>\n" + "\n".join(added)
        if failed:
            out += ("\n\n" if out else "") + "⚠️ <b>Xato:</b>\n" + "\n".join(failed)
        await message.reply_text(out or "Hech narsa kiritilmadi.", parse_mode=ParseMode.HTML)

    async def cmd_add(self, message: Message, args: list[str]) -> None:
        if args:
            await self.add_to_selected(message, args)
        else:
            self.pending = "add"
            await message.reply_text("➕ ID yoki @username yuboring.")

    async def cmd_remove(self, message: Message, args: list[str]) -> None:
        if not args:
            await message.reply_text("Format: /remove <id yoki @username>")
            return
        out = []
        for tok in args:
            try:
                uid, _ = await self.resolve_user(tok)
            except Exception:
                uid = int(tok) if tok.lstrip("-").isdigit() else None
            name = self.d["selected"].pop(str(uid), None) if uid is not None else None
            out.append(f"❌ {name} o‘chirildi" if name else f"⚠️ {tok} ro‘yxatda yo‘q")
        self.touch()
        await message.reply_text("\n".join(out))

    async def cmd_list(self, message: Message, args: list[str]) -> None:
        sel = self.d["selected"]
        if not sel:
            await message.reply_text("📋 Ro‘yxat bo‘sh. /add bilan qo‘shing.")
            return
        lines = [f"📋 <b>Tanlanganlar ({len(sel)}):</b>"]
        lines += [f"• {esc(name)} — <code>{uid}</code>" for uid, name in sel.items()]
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_quarantine(self, message: Message, args: list[str]) -> None:
        await self.reply_view(message, self.view_quarantine())

    async def cmd_release(self, message: Message, args: list[str]) -> None:
        if not args:
            await message.reply_text("Format: /release <id|all>")
            return
        if args[0].lower() == "all":
            n = len(self.d["quarantine"])
            self.d["quarantine"].clear()
            self.flood.clear()
            self.touch()
            await message.reply_text(f"🧹 {n} ta foydalanuvchi chiqarildi.")
            return
        info = self.d["quarantine"].pop(args[0], None)
        self.touch()
        await message.reply_text("✅ Chiqarildi" if info else "⚠️ Topilmadi")

    async def cmd_domain(self, message: Message, args: list[str]) -> None:
        await message.reply_text("🏴 Domen buyrug'i faol.")

    async def cmd_status(self, message: Message, args: list[str]) -> None:
        await self.reply_view(message, self.view_stats())

    async def cmd_help(self, message: Message, args: list[str]) -> None:
        await message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)

    async def cmd_cancel(self, message: Message, args: list[str]) -> None:
        self.pending = None
        await message.reply_text("❎ Bekor qilindi.")

    async def on_text(self, _client, message: Message) -> None:
        try:
            kind = self.pending
            if kind == "add":
                fwd = getattr(message, "forward_from", None) or getattr(
                    getattr(message, "forward_origin", None), "sender_user", None)
                self.pending = None
                if fwd:
                    self.d["selected"][str(fwd.id)] = display_name(fwd)
                    self.touch()
                    await message.reply_text(f"✅ Qo‘shildi: {display_name(fwd)} ({fwd.id})")
                elif message.text:
                    await self.add_to_selected(message, message.text.split())
                await self.reply_view(message, self.view_list())
            elif kind == "cd":
                secs = parse_duration(message.text or "")
                if secs is None:
                    await message.reply_text("❌ Noto‘g‘ri format.")
                    return
                self.pending = None
                self.d["cooldown"] = min(secs, 7 * 86400)
                self.touch()
                await self.reply_view(message, self.view_cooldown())
            else:
                await message.reply_text("ℹ️ Panelni ochish: /panel")
        except Exception:
            log.exception("on_text xatosi")


def main() -> None:
    setup_logging()
    keep_alive()
    lock = InstanceLock(LOCK_FILE)
    lock.acquire()
    store = StateStore(STATE_FILE)
    try:
        store.load()
        creds = ensure_credentials(store)
        app = SmartChatSystem(store, creds)
        LOOP.run_until_complete(app.run())
    except KeyboardInterrupt:
        log.info("Ctrl+C — to‘xtatildi.")
    except Exception:
        log.exception("Halokatli xato")
        raise
    finally:
        with contextlib.suppress(Exception):
            if store.dirty:
                store.save_sync()
        with contextlib.suppress(Exception):
            LOOP.run_until_complete(LOOP.shutdown_asyncgens())
            LOOP.close()
        lock.release()


if __name__ == "__main__":
    main()
