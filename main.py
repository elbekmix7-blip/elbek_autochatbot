#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.types import Message

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = Path(os.getenv("STATE_PATH") or (BASE_DIR / "state.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("smartchat")

# Bazaviy holat
STATE: dict[str, Any] = {
    "enabled": True,
    "cooldown": 20,
    "selected": {},
    "users": {}
}

def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return STATE

def save_state(data: dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass

def main() -> None:
    api_id = int(os.getenv("TG_API_ID") or 0)
    api_hash = os.getenv("TG_API_HASH") or ""
    session_string = os.getenv("STRING_SESSION") or ""

    if not api_id or not api_hash or not session_string:
        sys.exit("❌ Render muhitida TG_API_ID, TG_API_HASH yoki STRING_SESSION yetishmayapti!")

    # Faqat Userbot orqali to'g'ridan-to'g'ri ishlaydigan sodda tizim
    app = Client(
        "my_userbot",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=True
    )

    state = load_state()

    FIRST_REPLY = "Salom! 🤖 Hozir band edim, xabaringizni yozib qoldirishingiz mumkin, tez orada javob beraman."
    SECOND_REPLY = "Xabaringiz uchun rahmat! 🙏 Imkon topilishi bilan o'zim aloqaga chiqaman."

    @app.on_message(filters.private & filters.incoming & ~filters.service)
    async def handle_incoming(_client: Client, message: Message):
        if not state.get("enabled", True):
            return

        user = message.from_user
        if not user or user.is_bot or user.is_self:
            return

        uid = str(user.id)
        # Faqat qo'shilgan odamlarga javob beradi
        if uid not in state.get("selected", {}):
            return

        rec = state["users"].setdefault(uid, {"stage": 0, "last_reply": 0.0})
        stage = int(rec["stage"])

        if stage >= 2:
            return  # Ko'p bezovta qilmasligi uchun 2 tadan ortiq yozmaydi

        if time.time() - float(rec["last_reply"]) < state.get("cooldown", 20):
            return

        text = FIRST_REPLY if stage == 0 else SECOND_REPLY
        
        try:
            await asyncio.sleep(1.0)
            await message.reply_text(text)
            rec["stage"] = stage + 1
            rec["last_reply"] = time.time()
            save_state(state)
            log.info(f"Avto-javob yuborildi: {user.first_name} (Bosqich: {stage + 1})")
        except Exception as e:
            log.error(f"Xatolik: {e}")

    # O'zingiz boshqarishingiz uchun oddiy buyruqlar (o'zingizga yozganingizda ishlaydi)
    @app.on_message(filters.private & filters.outgoing & filters.command(["add", "remove", "list", "on", "off"]))
    async def handle_commands(_client: Client, message: Message):
        cmd = message.command[0]
        args = message.command[1:]

        if cmd == "on":
            state["enabled"] = True
            save_state(state)
            await message.edit("🟢 Avto-javob yoqildi.")
        elif cmd == "off":
            state["enabled"] = False
            save_state(state)
            await message.edit("🔴 Avto-javob o'chirildi.")
        elif cmd == "add":
            if not args:
                await message.edit("❌ Format: /add <id yoki username>")
                return
            for arg in args:
                clean = arg.lstrip("@")
                try:
                    target = await app.get_users(int(clean) if clean.isdigit() else clean)
                    state["selected"][str(target.id)] = target.first_name
                    save_state(state)
                    await message.edit(f"✅ Qo'shildi: {target.first_name} (`{target.id}`)")
                except Exception as e:
                    await message.edit(f"❌ Topilmadi: {arg} ({e})")
        elif cmd == "remove":
            if not args:
                await message.edit("❌ Format: /remove <id>")
                return
            for arg in args:
                removed = state["selected"].pop(arg, None)
                save_state(state)
                await message.edit(f"❌ O'chirildi: {arg}" if removed else f"⚠️ Topilmadi: {arg}")
        elif cmd == "list":
            sel = state.get("selected", {})
            if not sel:
                await message.edit("📋 Ro'yxat bo'sh.")
                return
            txt = "📋 **Tanlanganlar:**\n" + "\n".join(f"• {name} (`{uid}`)" for uid, name in sel.items())
            await message.edit(txt)

    log.info("🚀 Userbot ishga tushmoqda...")
    app.run()

if __name__ == "__main__":
    main()
