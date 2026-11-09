# -*- coding: utf-8 -*-
"""
ELBEK SMART CHAT AUTOMATION - ULTIMATE GOLD & BLACK EDITION
Egasi: Elbek Ziyodullayev
"""

import os
import json
import time
import asyncio
import logging
from pathlib import Path
from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "bot.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("smartchat")

class Store:
    DEFAULTS = {
        "enabled": True,
        "mode": "selective",
        "cooldown": 300,
        "selected": {},
    }
    def __init__(self, path: Path):
        self.path = path
        self.d = dict(self.DEFAULTS)
        if path.exists():
            try:
                self.d.update(json.loads(path.read_text("utf-8")))
            except Exception:
                pass
    def save(self):
        try:
            self.path.write_text(json.dumps(self.d, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

state = Store(STATE_FILE)

# Bot Token orqali ishlaydigan barqaror boshqaruv va avto-javob tizimi
API_ID = int(os.getenv("TG_API_ID", "38967428") or "38967428")
API_HASH = os.getenv("TG_API_HASH", "8f38d3840aaec1c6d36e2f1807d4b460")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")

app = Client(
    "elbek_smart_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=str(BASE_DIR),
    parse_mode=ParseMode.HTML,
)

def get_panel_markup():
    status = "🟡 YOQIQ [ACTIVE]" if state.d["enabled"] else "⚫ O'CHIQ [OFF]"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"⚡ Bot Holati: {status}", callback_data="tgl"),
        ],
        [
            InlineKeyboardButton(f"🎯 Rejim: {state.d['mode'].upper()}", callback_data="mode"),
            InlineKeyboardButton(f"📋 Tanlanganlar: {len(state.d['selected'])}", callback_data="list")
        ],
        [
            InlineKeyboardButton("🟡 [ + ] Qo'shish (/add)", callback_data="help_add"),
            InlineKeyboardButton("⚫ [ 🔄 ] Yangilash", callback_data="home")
        ]
    ])

@app.on_message(filters.command(["start", "panel", "help"]))
async def panel_cmd(_client, message):
    text = (
        "⚡ <b>ELBEK SMART CHAT PANEL</b> 🟡⚫\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Hacker darajasidagi avtomatlashtirilgan boshqaruv tizimi.</i>\n\n"
        f"• Holat: <b>{'YOQIQ 🟡' if state.d['enabled'] else 'O‘CHIQ ⚫'}</b>\n"
        f"• Ishlash rejimi: <code>{state.d['mode']}</code>\n"
        f"• Tanlanganlar soni: <b>{len(state.d['selected'])} ta</b>"
    )
    await message.reply_text(text, reply_markup=get_panel_markup())

@app.on_callback_query()
async def callbacks(_client, cq):
    data = cq.data
    m = cq.message

    if data == "tgl":
        state.d["enabled"] = not state.d["enabled"]
        state.save()
        await cq.answer("Holat o'zgartirildi!")
        await m.edit_text("⚡ <b>ELBEK SMART CHAT PANEL</b> 🟡⚫", reply_markup=get_panel_markup())
    elif data == "mode":
        modes = ["selective", "all", "unknown"]
        curr = state.d["mode"]
        nxt = modes[(modes.index(curr) + 1) % len(modes)]
        state.d["mode"] = nxt
        state.save()
        await cq.answer(f"Rejim: {nxt}")
        await m.edit_text("⚡ <b>ELBEK SMART CHAT PANEL</b> 🟡⚫", reply_markup=get_panel_markup())
    elif data == "list":
        sel = state.d["selected"]
        txt = "📋 <b>Tanlanganlar ro'yxati:</b>\n\n" + "\n".join(f"• <code>{uid}</code>: {name}" for uid, name in sel.items()) if sel else "📋 Ro'yxat hozircha bo'sh."
        back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="home")]])
        await cq.answer()
        await m.edit_text(txt, reply_markup=back)
    elif data in ("home", "help_add"):
        txt = "⚡ <b>ELBEK SMART CHAT PANEL</b> 🟡⚫\n\nQuyidagi tugmalar orqali boshqaring:"
        if data == "help_add":
            txt = "➕ Tanlanganlarga qo'shish uchun chatga yuboring:\n<code>/add ID_yoki_username</code>"
        await cq.answer()
        await m.edit_text(txt, reply_markup=get_panel_markup())

@app.on_message(filters.command("add") & filters.private)
async def add_cmd(_client, message):
    args = message.command[1:]
    if not args:
        await message.reply_text("❌ Format: /add <id yoki username>")
        return
    for arg in args:
        clean = arg.lstrip("@")
        try:
            target = await app.get_users(int(clean) if clean.isdigit() else clean)
            state.d["selected"][str(target.id)] = target.first_name
            state.save()
            await message.reply_text(f"🟡 <b>Qo'shildi:</b> {target.first_name} (<code>{target.id}</code>)")
        except Exception as e:
            await message.reply_text(f"❌ Xato: {arg} ({e})")

if __name__ == "__main__":
    log.info("🟡⚫ Elbek Smart Chat Panel ishga tushmoqda...")
    app.run()
