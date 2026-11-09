#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import contextlib
import copy
import html
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

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
    from pyrogram.errors import FloodWait, RPCError
    from pyrogram.handlers import MessageHandler, RawUpdateHandler
    from pyrogram.raw import types as raw_types
    from pyrogram.types import Message
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
    "Salom! 🤖 Hozir band edilar, xabaringizni yozib qoldirishingiz mumkin. "
    "Imkon topilishi bilan o‘zlari javob beradilar."
)
SECOND_REPLY = (
    "Xabaringiz uchun rahmat! 🙏 Imkon topilishi bilan o‘zlari aloqaga chiqadilar."
)

SYSTEM_USER_IDS = {777000, 42777, 1087968824}

DEFAULT_STATE: dict[str, Any] = {
    "enabled": True,
    "cooldown": 20,
    "selected": {},
    "users": {},
}

log = logging.getLogger("smartchat")


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.handlers.clear()
    log.addHandler(console)


web_app = Flask(__name__)


@web_app.route("/")
def web_index():
    up = int(time.time() - STARTED_AT)
    return f"<h1>🤖 Smart Chat Automation Ishlayapti</h1><p>Uptime: {up}s</p>"


@web_app.route("/health")
def web_health():
    return jsonify(ok=True, uptime=int(time.time() - STARTED_AT))


def _run_web() -> None:
    try:
        web_app.run(host="0.0.0.0", port=WEB_PORT, threaded=True, use_reloader=False)
    except Exception:
        pass


def keep_alive() -> None:
    threading.Thread(target=_run_web, daemon=True).start()
    print(f"🌐 Veb-server 0.0.0.0:{WEB_PORT} da ishga tushdi.")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def display_name(user: Any) -> str:
    parts = [getattr(user, "first_name", None), getattr(user, "last_name", None)]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    username = getattr(user, "username", None)
    return f"@{username}" if username else f"ID {getattr(user, 'id', '?')}"


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.d: dict[str, Any] = copy.deepcopy(DEFAULT_STATE)
        self.dirty = False

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text("utf-8"))
                if isinstance(loaded, dict):
                    self.d.update(loaded)
            except Exception:
                pass

    def touch(self) -> None:
        self.dirty = True

    async def flush(self) -> None:
        if not self.dirty:
            return
        self.dirty = False
        try:
            await asyncio.to_thread(self.path.write_text, json.dumps(self.d, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            self.dirty = True

    async def autosave_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            await self.flush()

    def user_rec(self, uid: int) -> dict[str, Any]:
        rec = self.d["users"].setdefault(str(uid), {})
        rec.setdefault("stage", 0)
        rec.setdefault("last_reply", 0.0)
        return rec


class SmartChatSystem:
    def __init__(self, store: StateStore, creds: dict[str, Any]) -> None:
        self.store = store
        self.creds = creds
        self.userbot: Client = None  # type: ignore
        self.bot: Client = None  # type: ignore
        self.me = None
        self.bot_me = None
        self.owner_id = 6841567673

        self.tasks: set[asyncio.Task] = set()
        self.locks: dict[int, asyncio.Lock] = {}
        self.own_ids: deque = deque(maxlen=1000)

    @property
    def d(self) -> dict[str, Any]:
        return self.store.d

    def touch(self) -> None:
        self.store.touch()

    def spawn(self, coro, name: str = "task") -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def tg(self, func, *args, retries: int = 3, **kwargs):
        for _ in range(retries):
            try:
                return await func(*args, **kwargs)
            except FloodWait as exc:
                await asyncio.sleep(int(getattr(exc, "value", 5)) + 1)
        raise RuntimeError("FloodWait tugadi")

    async def run(self) -> None:
        self.userbot = Client(
            "userbot",
            api_id=self.creds["api_id"],
            api_hash=self.creds["api_hash"],
            session_string=self.creds["session_string"],
            in_memory=True,
        )
        self.bot = Client(
            "assistant",
            api_id=self.creds["api_id"],
            api_hash=self.creds["api_hash"],
            bot_token=self.creds["bot_token"],
            in_memory=True,
        )
        self._register_handlers()
        
        await self.userbot.start()
        self.me = await self.userbot.get_me()
        self.owner_id = self.me.id
        
        await self.bot.start()
        self.bot_me = await self.bot.get_me()

        log.info("✅ Userbot ishga tushdi: %s", self.me.id)
        log.info("✅ Assistant bot ishga tushdi: @%s", self.bot_me.username)

        self.spawn(self.store.autosave_loop(), "autosave")

        await idle()
        await self._shutdown()

    async def _shutdown(self) -> None:
        for client in (self.bot, self.userbot):
            if client:
                with contextlib.suppress(Exception):
                    await client.stop()

    def _register_handlers(self) -> None:
        ub, bt = self.userbot, self.bot
        
        # Userbot kiruvchi xabarlarni ushlaydi
        ub.add_handler(MessageHandler(self.on_incoming, filters.private & filters.incoming & ~filters.service), group=0)
        
        # Assistant bot (faqat o'zingiz yozasiz) buyruqlari
        owner_flt = filters.user(self.owner_id)
        bt.add_handler(MessageHandler(self.cmd_start, filters.private & owner_flt & filters.command("start")), group=0)
        bt.add_handler(MessageHandler(self.cmd_on, filters.private & owner_flt & filters.command("on")), group=0)
        bt.add_handler(MessageHandler(self.cmd_off, filters.private & owner_flt & filters.command("off")), group=0)
        bt.add_handler(MessageHandler(self.cmd_add, filters.private & owner_flt & filters.command("add")), group=0)
        bt.add_handler(MessageHandler(self.cmd_list, filters.private & owner_flt & filters.command("list")), group=0)
        bt.add_handler(MessageHandler(self.cmd_remove, filters.private & owner_flt & filters.command("remove")), group=0)

    # --- Assistant Bot Buyruqlari ---
    async def cmd_start(self, _client, message: Message) -> None:
        await message.reply_text(
            "🤖 <b>Avto-javob tizimi ishlayapti!</b>\n\n"
            "Buyruqlar:\n"
            "/on - Botni yoqish\n"
            "/off - Botni o'chirish\n"
            "/add <id/@username> - Tanlanganlarga qo'shish\n"
            "/remove <id/@username> - Ro'yxatdan o'chirish\n"
            "/list - Tanlanganlar ro'yxati",
            parse_mode=ParseMode.HTML
        )

    async def cmd_on(self, _client, message: Message) -> None:
        self.d["enabled"] = True
        self.touch()
        await message.reply_text("🟢 Bot yoqildi.")

    async def cmd_off(self, _client, message: Message) -> None:
        self.d["enabled"] = False
        self.touch()
        await message.reply_text("🔴 Bot o'chirildi.")

    async def cmd_add(self, _client, message: Message) -> None:
        args = message.command[1:] if message.command else []
        if not args:
            await message.reply_text("❌ Format: /add <id yoki username>")
            return
        
        added = []
        for arg in args:
            clean = arg.lstrip("@")
            try:
                user = await self.userbot.get_users(int(clean) if clean.isdigit() else clean)
                self.d["selected"][str(user.id)] = display_name(user)
                added.append(f"• {display_name(user)} (`{user.id}`)")
            except Exception as e:
                added.append(f"• {arg} — Topilmadi ({e})")
        
        self.touch()
        await message.reply_text("✅ Qo'shildi:\n" + "\n".join(added), parse_mode=ParseMode.HTML)

    async def cmd_remove(self, _client, message: Message) -> None:
        args = message.command[1:] if message.command else []
        if not args:
            await message.reply_text("❌ Format: /remove <id>")
            return
        
        removed = []
        for arg in args:
            name = self.d["selected"].pop(arg, None)
            removed.append(f"❌ {arg} o'chirildi" if name else f"⚠️ {arg} ro'yxatda yo'q")
        self.touch()
        await message.reply_text("\n".join(removed))

    async def cmd_list(self, _client, message: Message) -> None:
        sel = self.d["selected"]
        if not sel:
            await message.reply_text("📋 Ro'yxat bo'sh. /add bilan qo'shing.")
            return
        lines = [f"📋 <b>Tanlanganlar ({len(sel)}):</b>"]
        lines += [f"• {name} — `{uid}`" for uid, name in sel.items()]
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    # --- Userbot: Avto-javob berish qismi ---
    async def on_incoming(self, _client, message: Message) -> None:
        if not self.d["enabled"]:
            return
        user = message.from_user
        if not user or user.is_bot or user.id == self.owner_id:
            return

        uid = str(user.id)
        # Faqat /add orqali qo'shilgan tanlangan odamlarga javob beradi
        if uid not in self.d["selected"]:
            return

        lock = self.locks.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            rec = self.store.user_rec(user.id)
            stage = int(rec["stage"])
            if stage >= 2:
                return  # Ikki marta yozgandan keyin jim turadi

            if time.time() - float(rec["last_reply"]) < self.d["cooldown"]:
                return

            text = FIRST_REPLY if stage == 0 else SECOND_REPLY
            await asyncio.sleep(1.5)  # ozgina kutib yozish
            await self.tg(self.userbot.send_message, message.chat.id, text)

            rec["stage"] = stage + 1
            rec["last_reply"] = time.time()
            self.touch()


def main() -> None:
    setup_logging()
    keep_alive()
    store = StateStore(STATE_FILE)
    store.load()
    
    creds = {
        "api_id": int(os.getenv("TG_API_ID") or 0),
        "api_hash": os.getenv("TG_API_HASH") or "",
        "bot_token": os.getenv("TG_BOT_TOKEN") or "",
        "session_string": os.getenv("STRING_SESSION") or "",
    }
    
    if not creds["api_id"] or not creds["api_hash"] or not creds["bot_token"] or not creds["session_string"]:
        sys.exit("❌ .env yoki Render muhitida o'zgaruvchilar yetishmayapti!")

    app = SmartChatSystem(store, creds)
    LOOP.run_until_complete(app.run())


if __name__ == "__main__":
    main()
