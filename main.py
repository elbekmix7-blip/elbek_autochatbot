#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 Smart Chat Automation Userbot  (Pyrogram + StringSession + Render/Docker)
==============================================================================

Bitta faylli userbot. Hammasi sizning shaxsiy Telegram profilingizda ishlaydi.
Boshqaruv faqat "Saved Messages" (Saqlangan xabarlar) orqali.

ENV O'ZGARUVCHILAR
------------------
Majburiy:
  API_ID            my.telegram.org dan
  API_HASH          my.telegram.org dan
  STRING_SESSION    Pyrogram session string  (python main.py --session  bilan olinadi)

Ixtiyoriy (hammasida default qiymat bor):
  PORT                     Flask keep-alive porti                  (7860)
  DEFAULT_MODE             selected | all                          (selected)
  PHASE_SECONDS            har bir soxta status davomiyligi, soniya (3)
  OWNER_ACTIVE_WINDOW      egasi yozgandan keyin "faol suhbat" oynasi, soniya (900)
  READ_ACTIVE_WINDOW       egasi o'qigandan keyin "faol suhbat" oynasi, soniya (120)
  BURST_GRACE              1-javobdan keyin shu soniya ichidagi xabarlar bitta deb sanaladi (8)
  MAX_MESSAGE_AGE          shundan eski xabarlarga javob berilmaydi, soniya (3600)
  QUARANTINE_THRESHOLD     xavf bali shu qiymatga yetsa karantin (2)
  TRUSTED_DOMAINS          ishonchli domenlar, vergul bilan (t.me,telegram.org,...)
  STATE_FILE               lokal holat fayli                       (data/state.json)
  CLOUD_STATE              Saved Messages ichida zaxira nusxa       (1)
  STARTUP_NOTICE           ishga tushganda Saved Messages'ga xabar  (1)
  SELF_PING                RENDER_EXTERNAL_URL ni o'zi chaqirib turadi (1)
  LOG_LEVEL                INFO / DEBUG                            (INFO)

BUYRUQLAR (faqat Saved Messages): /on /off /add /remove /list /status /panel
/help  +  qo'shimcha: /mode /quarantine /release /reset
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

# ------------------------------------------------------------------------------
# MUHIM: event loop Pyrogram import qilinishidan OLDIN yaratiladi.
# Pyrogram (sync.py) import paytida asyncio.get_event_loop() ni chaqiradi.
# Python 3.12+ da loop bo'lmasa DeprecationWarning/RuntimeError chiqadi, hamda
# "attached to a different loop" xatosi kelib chiqadi. Shu sababli BITTA loop
# yaratib, butun dastur (Client, handlerlar, tasklar) shu loopda ishlaydi.
# ------------------------------------------------------------------------------
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

from pyrogram import Client, enums, filters  # noqa: E402
from pyrogram import __version__ as PYROGRAM_VERSION  # noqa: E402
from pyrogram import errors as pyro_errors  # noqa: E402
from pyrogram.handlers import MessageHandler, RawUpdateHandler  # noqa: E402
from pyrogram.raw import types as raw_types  # noqa: E402


# ==============================================================================
# 1. KONFIGURATSIYA
# ==============================================================================
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

    PHASE_SECONDS: float = _env_float("PHASE_SECONDS", 3.0)
    ACTION_REFRESH: float = 2.5  # Telegram status ~5s yashaydi, shuning uchun yangilab turamiz

    OWNER_ACTIVE_WINDOW: float = _env_float("OWNER_ACTIVE_WINDOW", 900.0)
    READ_ACTIVE_WINDOW: float = _env_float("READ_ACTIVE_WINDOW", 120.0)
    BURST_GRACE: float = _env_float("BURST_GRACE", 8.0)
    MAX_MESSAGE_AGE: float = _env_float("MAX_MESSAGE_AGE", 3600.0)
    HISTORY_CHECK_LIMIT: int = _env_int("HISTORY_CHECK_LIMIT", 8)

    QUARANTINE_THRESHOLD: int = _env_int("QUARANTINE_THRESHOLD", 2)
    NOTICE_THROTTLE: float = 600.0  # bir foydalanuvchi uchun karantin xabarnomasi oralig'i

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


# ==============================================================================
# 2. LOGGING
# ==============================================================================
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


# ==============================================================================
# 3. MATNLAR
# ==============================================================================
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
    "<b>Boshqaruv</b> (faqat shu chatda):\n"
    "• <code>/on</code> — avto-javobni yoqish\n"
    "• <code>/off</code> — avto-javobni o'chirish\n"
    "• <code>/status</code> — joriy holat va statistika\n"
    "• <code>/panel</code> — to'liq boshqaruv paneli\n"
    "• <code>/list</code> — tanlanganlar ro'yxati\n"
    "• <code>/help</code> — shu yordam\n\n"
    "<b>Odam qo'shish (ID so'ralmaydi):</b>\n"
    "1️⃣ <code>/add @username</code>\n"
    "2️⃣ Odamning xabarini shu chatga <b>forward</b> qiling, so'ng unga "
    "<b>reply</b> qilib <code>/add</code> yozing (yoki forwarddan keyin shunchaki "
    "<code>/add</code>)\n"
    "3️⃣ <code>/add 123456789</code> (raqamli ID)\n"
    "Bir nechtasini birdan: <code>/add @a @b 12345</code>\n\n"
    "<b>Olib tashlash:</b> <code>/remove @username</code> | ID | forward+reply | "
    "<code>/remove all</code>\n\n"
    "<b>Qo'shimcha:</b>\n"
    "• <code>/mode selected</code> — faqat tanlanganlarga javob (default)\n"
    "• <code>/mode all</code> — barcha shaxsiy chatlarga javob\n"
    "• <code>/quarantine</code> — karantindagilar ro'yxati\n"
    "• <code>/release @user|ID|all</code> — karantindan chiqarish\n"
    "• <code>/reset @user|ID|all</code> — suhbat bosqichini noldan boshlash\n\n"
    "<b>Mantiq:</b> avval 9 soniyalik tabiiy status (3s rasm → 3s fayl → 3s yozish), "
    "keyin javob. 1-xabarga to'liq salom, 2-xabarga minnatdorchilik, undan keyin "
    "siz qo'lda javob yozguningizcha bot jim turadi. Siz o'zingiz yozayotgan yoki "
    "o'qigan suhbatlarga bot aralashmaydi."
)


# ==============================================================================
# 4. UMUMIY YORDAMCHI FUNKSIYALAR
# ==============================================================================
esc = html.escape


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
    """Telegram entity offsetlari UTF-16 birliklarida bo'ladi."""
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def defang(text: str) -> str:
    """Zararli havolani bosib yubormaslik uchun zararsizlantirish."""
    return text.replace("http", "hxxp").replace(".", "[.]")


def split_text(text: str, limit: int = 3800) -> List[str]:
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # juda uzun bitta qator
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
    """pyrogram.errors dan xatolik klassini xavfsiz olish (versiyalar farqiga chidamli)."""
    obj = getattr(pyro_errors, name, None)
    if obj is None:
        return type(name, (Exception,), {})  # hech qachon ko'tarilmaydigan "bo'sh" klass
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


# ==============================================================================
# 5. XAVFSIZLIK SKANERI (KARANTIN FILTRI)
# ==============================================================================
DANGEROUS_EXTENSIONS: Set[str] = {
    "apk", "apks", "xapk", "apkm", "exe", "bat", "cmd", "com", "scr", "pif",
    "msi", "msp", "jar", "vbs", "vbe", "js", "jse", "wsf", "wsh", "ps1", "psm1",
    "lnk", "dll", "sys", "reg", "hta", "cpl", "gadget", "sh", "bin", "run",
    "appimage", "dmg", "pkg", "chm", "url", "inf", "scf", "bash", "elf",
}
RISKY_EXTENSIONS: Set[str] = {"docm", "xlsm", "pptm", "html", "htm", "svg", "iso", "img"}
DANGEROUS_MIME_PARTS: Tuple[str, ...] = (
    "android.package-archive", "x-msdownload", "x-msdos-program", "x-dosexec",
    "x-executable", "x-sh", "x-bat", "java-archive", "x-msi", "vnd.microsoft.portable-executable",
    "x-apple-diskimage",
)

SHORTENERS: Set[str] = {
    "bit.ly", "tinyurl.com", "cutt.ly", "is.gd", "t.ly", "rb.gy", "shorturl.at",
    "ow.ly", "goo.gl", "tiny.cc", "buff.ly", "rebrand.ly", "s.id", "v.gd",
    "clck.ru", "vk.cc", "u.to", "qr.net", "shorte.st", "adf.ly", "bc.vc",
    "ouo.io", "soo.gd", "trib.al", "t.co", "tr.ee", "shrtco.de", "short.io",
}
SUSPICIOUS_TLDS: Set[str] = {
    "xyz", "top", "click", "tk", "ml", "ga", "cf", "gq", "icu", "buzz", "cyou",
    "monster", "rest", "work", "zip", "mov", "country", "kim", "loan", "men",
    "party", "review", "stream", "download", "racing", "win", "bid", "trade",
    "webcam", "science", "date", "faith", "accountant", "cam", "sbs", "quest",
    "support", "cfd", "lol", "fit", "gdn",
}
PHISH_KEYWORDS: Tuple[str, ...] = (
    "airdrop", "giveaway", "claim", "wallet", "freebtc", "bonus", "prize",
    "gift", "verify", "verification", "login", "signin", "suspend", "unlock",
    "recover", "premium", "crypto", "invest", "casino", "1win", "mostbet",
    "lucky", "reward", "free-", "-free",
)
BRAND_TOKENS: Tuple[str, ...] = ("telegram", "tgram", "t-me", "telegr")

TRUSTED_DOMAINS: Set[str] = {
    "t.me", "telegram.me", "telegram.org", "telegram.dog", "telegra.ph",
    "google.com", "youtube.com", "youtu.be", "wikipedia.org", "github.com",
    "instagram.com", "facebook.com", "linkedin.com", "x.com", "twitter.com",
    "microsoft.com", "microsoftonline.com", "apple.com", "zoom.us", "gov.uz",
    "uz.wikipedia.org", "anthropic.com", "claude.ai",
}
for _extra in _env_str("TRUSTED_DOMAINS").split(","):
    _extra = _extra.strip().lower()
    if _extra:
        TRUSTED_DOMAINS.add(_extra)

URL_RE = re.compile(r"(?i)\b(?:(?:https?|ftp)://|www\.)[^\s<>\"'«»]+")
_SHORT_ALT = "|".join(re.escape(d) for d in sorted(SHORTENERS, key=len, reverse=True))
BARE_SHORT_RE = re.compile(rf"(?i)(?<![\w@./-])(?:{_SHORT_ALT})/[^\s<>\"']+")
_TLD_ALT = "|".join(sorted(SUSPICIOUS_TLDS))
BARE_SUSPICIOUS_RE = re.compile(
    rf"(?i)(?<![\w@./-])(?:[a-z0-9-]+\.)+(?:{_TLD_ALT})\b(?:/[^\s<>\"']*)?"
)
DISPLAY_LOOKS_LIKE_URL = re.compile(
    r"(?i)^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/:?#].*)?$"
)
NUMERIC_HOST_RE = re.compile(r"(?i)^(?:0x[0-9a-f]+|\d{8,10})$")


@dataclass
class ScanResult:
    score: int
    reasons: List[str]

    @property
    def flagged(self) -> bool:
        return self.score >= Config.QUARANTINE_THRESHOLD and bool(self.reasons)


def _is_trusted_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def analyze_url(raw: str, display: Optional[str] = None) -> Tuple[int, List[str]]:
    """Bitta havolani baholaydi. (ball, sabablar) qaytaradi."""
    url = raw.strip().rstrip(".,;:!?)]}\"'")
    if not url:
        return 0, []
    lowered = url.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:")):
        return 3, [f"Xavfli sxema: {defang(lowered[:30])}"]
    if lowered.startswith("tg://"):
        return 0, []

    candidate = url if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url) else "http://" + url
    try:
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return 1, ["Noto'g'ri formatdagi havola"]
    if not host:
        return 0, []

    score = 0
    reasons: List[str] = []

    if "@" in parts.netloc:
        score += 3
        reasons.append("Havola ichida '@' (domenni yashirish hiylasi)")

    if _is_trusted_host(host):
        return score, [f"{r} [{defang(host)}]" for r in reasons]

    # Havola matni va haqiqiy manzil mos kelmasligi
    if display:
        shown = display.strip()
        if " " not in shown and DISPLAY_LOOKS_LIKE_URL.match(shown):
            try:
                shown_host = (
                    urlsplit(shown if "://" in shown else "http://" + shown).hostname or ""
                ).lower()
            except ValueError:
                shown_host = ""
            if shown_host.startswith("www."):
                shown_host = shown_host[4:]
            if shown_host and not (
                host == shown_host
                or host.endswith("." + shown_host)
                or shown_host.endswith("." + host)
            ):
                score += 3
                reasons.append("Havola matni aldamchi (ko'rinadigan manzil boshqa joyga olib boradi)")

    is_ip = False
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = True
    except ValueError:
        is_ip = bool(NUMERIC_HOST_RE.match(host))
    if is_ip:
        score += 3
        reasons.append("Havola IP-manzilga olib boradi")

    if "xn--" in host:
        score += 3
        reasons.append("Punycode domen (o'xshash belgilar bilan aldash)")

    ext = os.path.splitext(parts.path.lower())[1].lstrip(".")
    if ext in DANGEROUS_EXTENSIONS:
        score += 3
        reasons.append(f"Havola xavfli fayl (.{ext}) yuklatadi")

    if host in SHORTENERS or any(host.endswith("." + s) for s in SHORTENERS):
        score += 2
        reasons.append("Qisqartirilgan havola (manzil yashirin)")

    tld = host.rsplit(".", 1)[-1]
    if tld in SUSPICIOUS_TLDS:
        score += 2
        reasons.append(f"Shubhali domen zonasi (.{tld})")

    if any(token in host for token in BRAND_TOKENS):
        score += 3
        reasons.append("Telegram brendiga o'xshatilgan soxta domen")

    keywords = [k for k in PHISH_KEYWORDS if k in host]
    if keywords:
        score += min(2, len(keywords))
        reasons.append("Fishing kalit so'zlari: " + ", ".join(sorted(set(keywords))[:4]))

    if host.count("-") >= 3 or len(host) > 45:
        score += 1
        reasons.append("G'ayritabiiy uzun/tirelarga boy domen")

    return score, [f"{r} [{defang(host)}]" if "[" not in r else r for r in reasons]


class Scanner:
    """Kiruvchi xabarni fayllar va havolalar bo'yicha tekshiradi."""

    MEDIA_ATTRS = ("document", "video", "audio", "animation")

    def scan(self, message: Any) -> ScanResult:
        total = 0
        reasons: List[str] = []
        for scorer in (self._scan_files, self._scan_links):
            try:
                score, found = scorer(message)
            except Exception:  # skaner hech qachon asosiy oqimni buzmasligi kerak
                log.exception("Skanerda kutilmagan xatolik")
                continue
            total += score
            reasons.extend(found)
        seen: Set[str] = set()
        unique = [r for r in reasons if not (r in seen or seen.add(r))]
        return ScanResult(total, unique)

    # ---- fayllar --------------------------------------------------------
    def _scan_files(self, message: Any) -> Tuple[int, List[str]]:
        score = 0
        reasons: List[str] = []
        for attr in self.MEDIA_ATTRS:
            media = getattr(message, attr, None)
            if media is None:
                continue
            name = (getattr(media, "file_name", None) or "").strip()
            mime = (getattr(media, "mime_type", None) or "").lower()
            lowered = name.lower()

            if "\u202e" in name:
                score += 3
                reasons.append("Fayl nomida RTL-belgi (kengaytmani yashirish hiylasi)")

            ext = os.path.splitext(lowered)[1].lstrip(".")
            if ext in DANGEROUS_EXTENSIONS:
                score += 3
                reasons.append(f"Xavfli fayl: «{name}» (.{ext})")
            elif ext in RISKY_EXTENSIONS:
                score += 1
                reasons.append(f"Ehtiyot bo'ling: «{name}» (.{ext})")

            if mime and any(part in mime for part in DANGEROUS_MIME_PARTS):
                if ext not in DANGEROUS_EXTENSIONS:
                    score += 3
                    reasons.append(f"Xavfli fayl turi (MIME): {mime}")
        return score, reasons

    # ---- havolalar ------------------------------------------------------
    def _extract_links(self, message: Any) -> List[Tuple[str, Optional[str]]]:
        text = message.text or message.caption or ""
        entities = message.entities or message.caption_entities or []
        found: List[Tuple[str, Optional[str]]] = []
        seen: Set[str] = set()

        def push(url: str, display: Optional[str] = None) -> None:
            key = url.strip().rstrip(".,;:!?)]}\"'").lower()
            if key and key not in seen:
                seen.add(key)
                found.append((url, display))

        for ent in entities:
            etype = getattr(getattr(ent, "type", None), "name", str(getattr(ent, "type", "")))
            if etype == "TEXT_LINK" and getattr(ent, "url", None):
                push(ent.url, utf16_slice(text, ent.offset, ent.length))
            elif etype == "URL":
                push(utf16_slice(text, ent.offset, ent.length))
        for regex in (URL_RE, BARE_SHORT_RE, BARE_SUSPICIOUS_RE):
            for match in regex.finditer(text):
                push(match.group(0))
        return found

    def _scan_links(self, message: Any) -> Tuple[int, List[str]]:
        total = 0
        reasons: List[str] = []
        for url, display in self._extract_links(message)[:15]:
            score, found = analyze_url(url, display)
            total += score
            reasons.extend(found)
        return total, reasons


# ==============================================================================
# 6. HOLAT SAQLASH (lokal fayl + Saved Messages ichida zaxira)
# ==============================================================================
STATE_TAG = "🗄 USERBOT_STATE_V1 (avtomatik zaxira nusxa — o'chirmang)"
STATE_TAG_PREFIX = "🗄 USERBOT_STATE_V1"


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.enabled: bool = True
        self.mode: str = Config.DEFAULT_MODE if Config.DEFAULT_MODE in {"selected", "all"} else "selected"
        self.selected: Dict[str, Dict[str, Any]] = {}
        self.quarantine: Dict[str, Dict[str, Any]] = {}
        self.chats: Dict[str, Dict[str, Any]] = {}
        self.stats: Dict[str, int] = {"replies_sent": 0, "aborted": 0, "quarantined": 0}
        self.updated_at: float = 0.0
        self.dirty: bool = False
        self._cloud_msg_id: Optional[int] = None

    # ---- mutatsiya belgisi ---------------------------------------------
    def touch(self) -> None:
        self.updated_at = time.time()
        self.dirty = True

    # ---- serializatsiya -------------------------------------------------
    def to_dict(self, include_chats: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "v": 1,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
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
        mode = str(data.get("mode", self.mode)).lower()
        self.mode = mode if mode in {"selected", "all"} else "selected"
        sel = data.get("selected", {})
        self.selected = {str(k): dict(v) for k, v in sel.items()} if isinstance(sel, dict) else {}
        qua = data.get("quarantine", {})
        self.quarantine = {str(k): dict(v) for k, v in qua.items()} if isinstance(qua, dict) else {}
        chats = data.get("chats", {})
        self.chats = {str(k): dict(v) for k, v in chats.items()} if isinstance(chats, dict) else {}
        stats = data.get("stats", {})
        if isinstance(stats, dict):
            for key in ("replies_sent", "aborted", "quarantined"):
                self.stats[key] = int(stats.get(key, self.stats.get(key, 0)))
        self.updated_at = float(data.get("updated_at", 0.0))

    # ---- chat holati ----------------------------------------------------
    def chat(self, chat_id: int) -> Dict[str, Any]:
        key = str(chat_id)
        state = self.chats.get(key)
        if state is None:
            state = {"stage": 0, "last_reply_at": 0.0}
            self.chats[key] = state
        return state

    def reset_chat(self, chat_id: int) -> bool:
        key = str(chat_id)
        if key in self.chats:
            del self.chats[key]
            self.touch()
            return True
        return False

    # ---- lokal fayl -----------------------------------------------------
    def load_file(self) -> bool:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.apply_dict(data)
            log.info("Holat fayldan yuklandi (%s)", self.path)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            log.warning("Holat faylini o'qib bo'lmadi: %s", exc)
            return False

    def save_file(self) -> None:
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as exc:
            log.warning("Holatni faylga yozib bo'lmadi: %s", exc)

    # ---- Saved Messages ichidagi zaxira --------------------------------
    @staticmethod
    def _encode(data: Dict[str, Any]) -> str:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")

    async def cloud_load(self, client: Client, me_id: int) -> bool:
        if not Config.CLOUD_STATE:
            return False
        try:
            async for msg in client.get_chat_history(me_id, limit=Config.CLOUD_SCAN_LIMIT):
                text = msg.text or ""
                if not text.startswith(STATE_TAG_PREFIX):
                    continue
                self._cloud_msg_id = msg.id
                try:
                    payload = text.split("\n", 1)[1].strip()
                    data = json.loads(zlib.decompress(base64.b64decode(payload)).decode("utf-8"))
                except Exception as exc:
                    log.warning("Zaxira xabarini o'qib bo'lmadi: %s", exc)
                    return False
                if float(data.get("updated_at", 0.0)) > self.updated_at:
                    self.apply_dict(data)
                    log.info("Holat Saved Messages zaxirasidan tiklandi")
                    return True
                return False
        except Exception as exc:
            log.warning("Saved Messages'dan zaxirani qidirishda xatolik: %s", exc)
        return False

    async def cloud_save(self, client: Client, me_id: int) -> None:
        if not Config.CLOUD_STATE:
            return
        text = f"{STATE_TAG}\n{self._encode(self.to_dict(True))}"
        if len(text) > 4000:
            text = f"{STATE_TAG}\n{self._encode(self.to_dict(False))}"
        if len(text) > 4000:
            log.warning("Holat zaxira xabariga sig'maydi (%d belgi) — faqat lokal fayl", len(text))
            return
        try:
            if self._cloud_msg_id:
                try:
                    await client.edit_message_text(
                        me_id, self._cloud_msg_id, text, parse_mode=enums.ParseMode.DISABLED
                    )
                    return
                except MessageNotModified:
                    return
                except FloodWait as exc:
                    await asyncio.sleep(min(flood_seconds(exc), 30))
                    return
                except RPCError as exc:
                    log.info("Zaxira xabarini tahrirlab bo'lmadi (%s) — yangisi yuboriladi", exc)
                    old_id = self._cloud_msg_id
                    self._cloud_msg_id = None
                    with contextlib.suppress(Exception):
                        await client.delete_messages(me_id, old_id)
            sent = await client.send_message(me_id, text, parse_mode=enums.ParseMode.DISABLED)
            self._cloud_msg_id = sent.id
        except Exception as exc:
            log.warning("Zaxira nusxani Saved Messages'ga yozib bo'lmadi: %s", exc)

    async def flush(self, client: Optional[Client], me_id: Optional[int]) -> None:
        self.dirty = False
        self.save_file()
        if client is not None and me_id is not None and RUNTIME.get("connected"):
            await self.cloud_save(client, me_id)


# ==============================================================================
# 7. FLASK KEEP-ALIVE (Render 7860 port talabi) — alohida oqimda
# ==============================================================================
def start_keepalive_server() -> None:
    port = Config.PORT

    def status_payload() -> Dict[str, Any]:
        return {
            "status": "ok",
            "connected": bool(RUNTIME.get("connected")),
            "uptime_seconds": int(time.time() - START_TS),
        }

    def run_flask() -> None:
        from flask import Flask, jsonify

        flask_app = Flask("keepalive")

        @flask_app.route("/")
        def index() -> Tuple[str, int]:
            return "Smart Chat Automation Userbot is running ✅", 200

        @flask_app.route("/health")
        def health():  # type: ignore[no-untyped-def]
            return jsonify(status_payload()), 200

        flask_app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)

    def run_stdlib() -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps(status_payload()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                return

        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

    def runner() -> None:
        try:
            try:
                import flask  # noqa: F401
            except ImportError:
                log.warning("Flask topilmadi — oddiy http.server ishlatilmoqda")
                run_stdlib()
                return
            run_flask()
        except Exception:
            log.exception("Keep-alive server to'xtab qoldi")

    threading.Thread(target=runner, name="keepalive-http", daemon=True).start()
    log.info("Keep-alive veb-server %d portda ishga tushdi", port)


def start_self_ping() -> None:
    """Render bepul rejimida uxlab qolmasligi uchun o'z tashqi URL'ini chaqirib turadi."""
    base = _env_str("SELF_PING_URL") or _env_str("RENDER_EXTERNAL_URL")
    if not Config.SELF_PING or not base:
        return
    target = base.rstrip("/") + "/health"

    def runner() -> None:
        import urllib.request

        time.sleep(60)
        while True:
            try:
                with urllib.request.urlopen(target, timeout=20) as resp:
                    resp.read(64)
            except Exception as exc:
                log.debug("Self-ping muvaffaqiyatsiz: %s", exc)
            time.sleep(max(60.0, Config.SELF_PING_INTERVAL))

    threading.Thread(target=runner, name="self-ping", daemon=True).start()
    log.info("Self-ping yoqildi: %s", target)


# ==============================================================================
# 8. AVTO-JAVOB DVIGATELI
# ==============================================================================
class _Aborted(Exception):
    """Avto-javob ketma-ketligi o'z-o'zidan bekor qilindi."""


def forward_info(message: Any) -> Tuple[Optional[Any], Optional[str], Optional[Any]]:
    """(foydalanuvchi, yashirin_ism, kanal/guruh) — Pyrogram 2.0 va yangi forward_origin uchun."""
    user = getattr(message, "forward_from", None)
    hidden = getattr(message, "forward_sender_name", None)
    chat = getattr(message, "forward_from_chat", None)
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        user = user or getattr(origin, "sender_user", None)
        hidden = hidden or getattr(origin, "sender_user_name", None)
        chat = chat or getattr(origin, "chat", None)
    return user, hidden, chat


def is_forwarded(message: Any) -> bool:
    return bool(
        getattr(message, "forward_date", None)
        or getattr(message, "forward_from", None)
        or getattr(message, "forward_sender_name", None)
        or getattr(message, "forward_from_chat", None)
        or getattr(message, "forward_origin", None)
    )


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
        self.last_notice: Dict[str, float] = {}
        self._sent_q: Deque[Tuple[int, int]] = collections.deque(maxlen=1000)
        self._sent_set: Set[Tuple[int, int]] = set()

    # ---- bot yuborgan xabarlarni eslab qolish -------------------------------
    def remember_sent(self, chat_id: int, msg_id: int) -> None:
        key = (chat_id, msg_id)
        if len(self._sent_q) == self._sent_q.maxlen:
            self._sent_set.discard(self._sent_q[0])
        self._sent_q.append(key)
        self._sent_set.add(key)

    def is_bot_message(self, message: Any) -> bool:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is not None and (chat_id, message.id) in self._sent_set:
            return True
        return (message.text or "").strip() in BOT_TEXTS

    # ---- tasklarni boshqarish ----------------------------------------------
    def is_running(self, chat_id: int) -> bool:
        task = self.tasks.get(chat_id)
        return task is not None and not task.done()

    def cancel_sequence(self, chat_id: int, reason: str) -> None:
        task = self.tasks.get(chat_id)
        if task is not None and not task.done():
            log.info("[%s] avto-javob bekor qilindi: %s", chat_id, reason)
            task.cancel()

    def cancel_all(self, reason: str) -> None:
        for chat_id in list(self.tasks):
            self.cancel_sequence(chat_id, reason)

    def _on_task_done(self, chat_id: int, task: asyncio.Task) -> None:
        if self.tasks.get(chat_id) is task:
            self.tasks.pop(chat_id, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                log.error("[%s] avto-javob taski xatolik bilan tugadi: %r", chat_id, exc)

    # ---- faol suhbat himoyasi ----------------------------------------------
    def owner_activity_reason(self, chat_id: int) -> Optional[str]:
        now = time.time()
        if now - self.owner_out.get(chat_id, 0.0) < Config.OWNER_ACTIVE_WINDOW:
            return "egasi yaqinda shu suhbatda yozgan"
        if now - self.owner_read.get(chat_id, 0.0) < Config.READ_ACTIVE_WINDOW:
            return "egasi suhbatni yaqinda o'qigan"
        return None

    async def _history_shows_owner_activity(self, client: Client, chat_id: int) -> bool:
        """Restartdan keyin yoki boshqa qurilmadan yozilgan javoblarni ham ushlaydi."""
        limit_ts = time.time() - Config.OWNER_ACTIVE_WINDOW
        try:
            async for item in client.get_chat_history(chat_id, limit=Config.HISTORY_CHECK_LIMIT):
                stamp = item.date.timestamp() if item.date else 0.0
                if stamp and stamp < limit_ts:
                    break
                if item.outgoing and not self.is_bot_message(item):
                    self.owner_out[chat_id] = max(self.owner_out.get(chat_id, 0.0), stamp or time.time())
                    return True
        except FloodWait:
            return False
        except Exception as exc:
            log.debug("[%s] tarixni tekshirib bo'lmadi: %s", chat_id, exc)
        return False

    # ---- xom update: egasi suhbatni o'qidi ---------------------------------
    async def on_raw_update(self, client: Client, update: Any, users: Any, chats: Any) -> None:
        try:
            if isinstance(update, raw_types.UpdateReadHistoryInbox):
                peer = update.peer
                if isinstance(peer, raw_types.PeerUser):
                    uid = int(peer.user_id)
                    if uid == self.app.me_id:
                        return
                    # Bot o'zi xabar yuborganda Telegram "o'qildi" belgisini qo'yishi mumkin — e'tiborsiz
                    if time.time() - self.last_bot_send.get(uid, 0.0) < 6.0:
                        return
                    self.owner_read[uid] = time.time()
                    self.cancel_sequence(uid, "egasi suhbatni o'qidi")
        except Exception:
            log.exception("Raw updateni qayta ishlashda xatolik")

    # ---- egasining chiquvchi xabari ----------------------------------------
    async def on_owner_outgoing(self, client: Client, message: Any) -> None:
        try:
            chat_id = message.chat.id
            if chat_id == self.app.me_id:
                return
            if getattr(message, "service", None):
                return
            if self.is_bot_message(message):
                return
            self.owner_out[chat_id] = time.time()
            self.cancel_sequence(chat_id, "egasi o'zi javob yozdi")
            if self.store.reset_chat(chat_id):
                log.info("[%s] egasi javob yozdi — bosqich nolga qaytarildi", chat_id)
        except Exception:
            log.exception("Chiquvchi xabarni qayta ishlashda xatolik")

    # ---- kiruvchi xabar ------------------------------------------------------
    async def on_incoming(self, client: Client, message: Any) -> None:
        try:
            await self._handle_incoming(client, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Kiruvchi xabarni qayta ishlashda xatolik")

    async def _handle_incoming(self, client: Client, message: Any) -> None:
        user = message.from_user
        if user is None or user.is_self or user.is_bot:
            return
        if getattr(message, "service", None) or user.id == 777000:
            return
        if getattr(user, "is_deleted", False):
            return

        # 1) Xavfsizlik — doim ishlaydi (avto-javob o'chiq bo'lsa ham)
        scan = self.scanner.scan(message)
        if scan.flagged:
            await self._quarantine(client, message, user, scan)
            return

        uid_key = str(user.id)
        if uid_key in self.store.quarantine:
            return
        if not self.store.enabled:
            return

        if self.store.mode == "selected":
            record = self.store.selected.get(uid_key)
            if record is None:
                return
            self._refresh_record(record, user)

        chat_id = message.chat.id
        if message.date and (time.time() - message.date.timestamp()) > Config.MAX_MESSAGE_AGE:
            return

        async with self.locks[chat_id]:
            if self.is_running(chat_id):
                return  # ketma-ketlik ketyapti — yangi xabarlar shu javobga qo'shiladi

            reason = self.owner_activity_reason(chat_id)
            if reason:
                log.info("[%s] jim turildi: %s", chat_id, reason)
                return

            state = self.store.chats.get(str(chat_id)) or {"stage": 0, "last_reply_at": 0.0}
            stage = int(state.get("stage", 0))
            if stage >= 2:
                return  # egasi qo'lda javob yozguncha jim
            if stage >= 1 and time.time() - float(state.get("last_reply_at", 0.0)) < Config.BURST_GRACE:
                return  # 1-javobdan zumda kelgan xabarlar — bitta "burst"

            if await self._history_shows_owner_activity(client, chat_id):
                log.info("[%s] jim turildi: tarixda egasining yaqin javobi bor", chat_id)
                return

            task = asyncio.create_task(
                self._sequence(client, chat_id, user.id), name=f"autoreply-{chat_id}"
            )
            self.tasks[chat_id] = task
            task.add_done_callback(lambda t, cid=chat_id: self._on_task_done(cid, t))

    @staticmethod
    def _refresh_record(record: Dict[str, Any], user: Any) -> None:
        new_name = display_name(user)
        new_username = getattr(user, "username", None)
        if record.get("name") != new_name or record.get("username") != new_username:
            record["name"] = new_name
            record["username"] = new_username

    # ---- karantin -------------------------------------------------------------
    async def _quarantine(self, client: Client, message: Any, user: Any, scan: ScanResult) -> None:
        key = str(user.id)
        first_time = key not in self.store.quarantine
        entry = self.store.quarantine.get(key, {})
        known = list(entry.get("reasons", []))
        for reason in scan.reasons:
            if reason not in known:
                known.append(reason)
        entry.update(
            {
                "name": display_name(user),
                "username": getattr(user, "username", None),
                "since": entry.get("since", time.time()),
                "last_at": time.time(),
                "reasons": known[-12:],
            }
        )
        self.store.quarantine[key] = entry
        if first_time:
            self.store.stats["quarantined"] += 1
        self.store.touch()
        self.cancel_sequence(message.chat.id, "karantin")

        now = time.time()
        if not first_time and now - self.last_notice.get(key, 0.0) < Config.NOTICE_THROTTLE:
            return
        self.last_notice[key] = now

        preview = (message.text or message.caption or "").strip()
        media_name = ""
        for attr in Scanner.MEDIA_ATTRS:
            media = getattr(message, attr, None)
            if media is not None and getattr(media, "file_name", None):
                media_name = media.file_name
                break
        lines = [
            "🚨 <b>KARANTIN</b>" + (" (yangi)" if first_time else " (takroriy xavf)"),
            f"👤 {mention(user.id, display_name(user))}"
            + (f" (@{esc(user.username)})" if getattr(user, "username", None) else "")
            + f" — <code>{user.id}</code>",
            "",
            "<b>Sabablar:</b>",
        ]
        lines += [f"• {esc(r)}" for r in scan.reasons[:8]]
        if media_name:
            lines.append(f"\n📎 Fayl: <code>{esc(defang(media_name))}</code>")
        if preview:
            lines.append(f"\n✉️ Xabar: <code>{esc(defang(preview[:200]))}</code>")
        lines.append(
            "\nBu foydalanuvchiga avto-javob berilmaydi va xabarlari e'tiborsiz qoldiriladi.\n"
            f"Qaytarish: <code>/release {user.id}</code>"
        )
        await self.app.say("\n".join(lines))
        log.warning("[%s] foydalanuvchi karantinga olindi: %s", user.id, "; ".join(scan.reasons[:3]))

    # ---- fake statuslar + javob ----------------------------------------------
    def _abort_reason(self, chat_id: int, uid: int, started: float) -> Optional[str]:
        if not self.store.enabled:
            return "avto-javob o'chirildi"
        if str(uid) in self.store.quarantine:
            return "foydalanuvchi karantinga olindi"
        if self.store.mode == "selected" and str(uid) not in self.store.selected:
            return "foydalanuvchi ro'yxatdan olib tashlandi"
        if self.owner_out.get(chat_id, 0.0) > started:
            return "egasi yozdi"
        if self.owner_read.get(chat_id, 0.0) > started:
            return "egasi o'qidi"
        return None

    async def _send_action(self, client: Client, chat_id: int, action: Any) -> None:
        try:
            await client.send_chat_action(chat_id, action)
        except FloodWait as exc:
            await asyncio.sleep(min(flood_seconds(exc, 3.0), 30.0))
        except RPCError as exc:
            log.debug("[%s] chat action yuborilmadi: %s", chat_id, exc)

    async def _hold_action(
        self, client: Client, chat_id: int, uid: int, action: Any, seconds: float, started: float
    ) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        next_send = 0.0
        while True:
            now = loop.time()
            if now >= end:
                return
            reason = self._abort_reason(chat_id, uid, started)
            if reason:
                raise _Aborted(reason)
            if now >= next_send:
                await self._send_action(client, chat_id, action)
                next_send = loop.time() + Config.ACTION_REFRESH
            await asyncio.sleep(max(0.0, min(0.4, end - loop.time())))

    async def _send_text(self, client: Client, chat_id: int, text: str) -> Optional[Any]:
        for attempt in (1, 2):
            try:
                return await client.send_message(chat_id, text, parse_mode=enums.ParseMode.DISABLED)
            except FloodWait as exc:
                wait = flood_seconds(exc)
                if attempt == 2 or wait > 60:
                    log.warning("[%s] FloodWait %.0fs — javob yuborilmadi", chat_id, wait)
                    return None
                await asyncio.sleep(wait + 1)
            except RPCError as exc:
                log.warning("[%s] javob yuborib bo'lmadi: %s", chat_id, exc)
                return None
        return None

    async def _sequence(self, client: Client, chat_id: int, uid: int) -> None:
        started = time.time()
        completed = False
        phases = (
            ("rasm yuklayapti", enums.ChatAction.UPLOAD_PHOTO),
            ("fayl yuklayapti", enums.ChatAction.UPLOAD_DOCUMENT),
            ("yozyapti", enums.ChatAction.TYPING),
        )
        try:
            for label, action in phases:
                log.debug("[%s] status: %s", chat_id, label)
                await self._hold_action(client, chat_id, uid, action, Config.PHASE_SECONDS, started)

            reason = self._abort_reason(chat_id, uid, started)
            if reason:
                raise _Aborted(reason)

            state = self.store.chat(chat_id)
            stage = int(state.get("stage", 0))
            text = FIRST_REPLY if stage == 0 else SECOND_REPLY
            sent = await self._send_text(client, chat_id, text)
            if sent is None:
                return
            self.remember_sent(chat_id, sent.id)
            self.last_bot_send[chat_id] = time.time()
            state["stage"] = stage + 1
            state["last_reply_at"] = time.time()
            self.store.stats["replies_sent"] += 1
            self.store.touch()
            completed = True
            log.info("[%s] %d-bosqich avto-javobi yuborildi", chat_id, stage + 1)
        except _Aborted as exc:
            self.store.stats["aborted"] += 1
            self.store.touch()
            log.info("[%s] avto-javob to'xtatildi: %s", chat_id, exc)
        except asyncio.CancelledError:
            self.store.stats["aborted"] += 1
            self.store.touch()
            raise
        except Exception:
            log.exception("[%s] avto-javob ketma-ketligida xatolik", chat_id)
        finally:
            if not completed:
                with contextlib.suppress(Exception):
                    await client.send_chat_action(chat_id, enums.ChatAction.CANCEL)


# ==============================================================================
# 9. ASOSIY ILOVA: Saved Messages buyruqlari + hayot sikli
# ==============================================================================
@dataclass
class Target:
    uid: int
    name: str
    username: Optional[str]
    resolved: bool = True


def parse_user_ref(token: str) -> Tuple[Optional[str], Any]:
    """('id', int) | ('username', str) | (None, None)"""
    t = token.strip().strip(",;")
    if not t:
        return None, None
    mo = re.search(r"(?i)tg://user\?id=(\d+)", t)
    if mo:
        return "id", int(mo.group(1))
    if re.fullmatch(r"\d{3,15}", t):
        return "id", int(t)
    t = re.sub(r"(?i)^(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/", "", t)
    t = t.split("?")[0].split("/")[0].lstrip("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", t):
        return "username", t
    return None, None


class UserbotApp:
    PENDING_TTL = 600.0

    def __init__(self) -> None:
        self.store = Store(Config.STATE_FILE)
        self.client: Optional[Client] = None
        self.me_id: Optional[int] = None
        self.stop_event = asyncio.Event()
        self.exit_code = 0
        self.bg_tasks: List[asyncio.Task] = []
        self.pending_forward: Optional[Dict[str, Any]] = None
        self.engine = Engine(self)
        self.f_saved = self._build_saved_filter()
        self.commands = {
            "help": self.cmd_help,
            "start": self.cmd_help,
            "on": self.cmd_on,
            "off": self.cmd_off,
            "status": self.cmd_status,
            "panel": self.cmd_panel,
            "list": self.cmd_list,
            "add": self.cmd_add,
            "remove": self.cmd_remove,
            "mode": self.cmd_mode,
            "quarantine": self.cmd_quarantine,
            "release": self.cmd_release,
            "reset": self.cmd_reset,
        }

    # ---- filtrlar -------------------------------------------------------------
    def _build_saved_filter(self) -> Any:
        app = self

        async def saved_func(_flt: Any, _client: Any, message: Any) -> bool:
            user = message.from_user
            return bool(
                app.me_id
                and user is not None
                and user.is_self
                and message.chat is not None
                and message.chat.id == app.me_id
            )

        return filters.create(saved_func, "SavedMessagesFilter")

    def _register_handlers(self, client: Client) -> None:
        client.add_handler(RawUpdateHandler(self.engine.on_raw_update), group=-1)
        client.add_handler(MessageHandler(self.on_saved_message, self.f_saved), group=0)
        client.add_handler(
            MessageHandler(
                self.engine.on_owner_outgoing,
                filters.private & filters.outgoing & ~self.f_saved,
            ),
            group=0,
        )
        client.add_handler(
            MessageHandler(self.engine.on_incoming, filters.private & filters.incoming), group=1
        )

    def _make_client(self) -> Client:
        client = Client(
            "smart_userbot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.STRING_SESSION,
            in_memory=True,
            sleep_threshold=Config.SLEEP_THRESHOLD,
        )
        self._register_handlers(client)
        return client

    # ---- Saved Messages'ga javob -----------------------------------------------
    async def say(self, text: str) -> None:
        if self.client is None:
            return
        for chunk in split_text(text):
            try:
                await self.client.send_message("me", chunk, parse_mode=enums.ParseMode.HTML)
            except FloodWait as exc:
                await asyncio.sleep(min(flood_seconds(exc), 30))
                with contextlib.suppress(Exception):
                    await self.client.send_message("me", chunk, parse_mode=enums.ParseMode.HTML)
            except Exception as exc:
                log.warning("Saved Messages'ga yozib bo'lmadi: %s", exc)

    # ---- Saved Messages handleri -----------------------------------------------
    async def on_saved_message(self, client: Client, message: Any) -> None:
        try:
            if getattr(message, "service", None):
                return
            if is_forwarded(message):
                self._remember_forward(message)
                return
            text = (message.text or "").strip()
            if not text.startswith("/"):
                return
            parts = text.split()
            command = parts[0][1:].split("@", 1)[0].lower()
            args = parts[1:]
            handler = self.commands.get(command)
            if handler is None:
                await self.say(f"❓ Noma'lum buyruq: <code>{esc(parts[0])}</code>\n/help ni yozing.")
                return
            await handler(message, args)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Buyruqni bajarishda xatolik")
            await self.say("⚠️ Buyruqni bajarishda ichki xatolik yuz berdi. Loglarni tekshiring.")

    def _remember_forward(self, message: Any) -> None:
        user, hidden, chat = forward_info(message)
        info: Dict[str, Any] = {"ts": time.time(), "user": None, "hidden": hidden, "chat": None}
        if user is not None and not getattr(user, "is_self", False):
            info["user"] = Target(user.id, display_name(user), getattr(user, "username", None), True)
            info["hidden"] = None
        elif chat is not None:
            info["chat"] = getattr(chat, "title", None) or "kanal/guruh"
        self.pending_forward = info

    # ---- manzil (target) aniqlash -------------------------------------------------
    def _local_find(self, uid: Optional[int] = None, username: Optional[str] = None) -> Optional[Target]:
        for source in (self.store.selected, self.store.quarantine):
            for key, rec in source.items():
                if uid is not None and int(key) == uid:
                    return Target(int(key), rec.get("name") or f"ID {key}", rec.get("username"), True)
                if username and (rec.get("username") or "").lower() == username.lower():
                    return Target(int(key), rec.get("name") or f"ID {key}", rec.get("username"), True)
        return None

    async def _resolve_token(self, token: str, local_first: bool) -> Tuple[Optional[Target], Optional[str]]:
        kind, value = parse_user_ref(token)
        if kind is None:
            return None, f"«{esc(token)}» — tushunarsiz format (@username, ID yoki t.me havolasi kerak)"
        if local_first:
            found = self._local_find(uid=value if kind == "id" else None,
                                     username=value if kind == "username" else None)
            if found:
                return found, None
        try:
            user = await self.client.get_users(value)  # type: ignore[union-attr]
            if isinstance(user, list):
                user = user[0]
            if user.is_bot:
                return None, f"«{esc(token)}» — bu bot, odam emas"
            if user.is_self:
                return None, "O'zingizni qo'shib bo'lmaydi"
            return Target(user.id, display_name(user), getattr(user, "username", None), True), None
        except FloodWait as exc:
            await asyncio.sleep(min(flood_seconds(exc), 20))
            return None, f"«{esc(token)}» — Telegram vaqtincha cheklov qo'ydi, birozdan keyin urinib ko'ring"
        except Exception as exc:
            log.debug("get_users(%r) xatolik: %r", value, exc)
            if kind == "id":
                # Raqamli ID — Telegram sessiya keshida bo'lmasa ham qabul qilamiz
                return Target(int(value), f"ID {value}", None, False), None
            return None, f"«{esc(token)}» — foydalanuvchi topilmadi"

    async def _collect_targets(
        self, message: Any, args: List[str], local_first: bool
    ) -> Tuple[List[Target], List[str]]:
        targets: List[Target] = []
        notes: List[str] = []

        replied = getattr(message, "reply_to_message", None)
        if replied is not None:
            user, hidden, chat = forward_info(replied)
            if user is not None and not getattr(user, "is_self", False):
                if getattr(user, "is_bot", False):
                    notes.append("Forward qilingan xabar botdan — bot qo'shilmaydi")
                else:
                    targets.append(Target(user.id, display_name(user), getattr(user, "username", None), True))
            elif hidden:
                notes.append(
                    f"«{esc(hidden)}» profilini yashirgan, forwarddan ID olib bo'lmaydi. "
                    "<code>/add @username</code> yoki ID bilan qo'shing"
                )
            elif chat is not None:
                notes.append("Bu xabar kanal/guruhdan forward qilingan — odam emas")
            else:
                notes.append("Reply qilingan xabar forward emas. Odamning xabarini forward qilib, unga reply qiling")

        for token in args:
            if token.lower() == "all":
                continue
            target, note = await self._resolve_token(token, local_first)
            if target is not None:
                targets.append(target)
            if note:
                notes.append(note)

        if not targets and not notes and not args and replied is None:
            pending = self.pending_forward
            if pending and time.time() - pending["ts"] < self.PENDING_TTL:
                if pending["user"] is not None:
                    targets.append(pending["user"])
                elif pending["hidden"]:
                    notes.append(
                        f"«{esc(pending['hidden'])}» profilini yashirgan, forwarddan ID olib bo'lmaydi. "
                        "<code>/add @username</code> yoki ID bilan qo'shing"
                    )
                elif pending["chat"]:
                    notes.append("Oxirgi forward kanal/guruhdan — odam emas")
        # takrorlarni olib tashlash
        unique: Dict[int, Target] = {}
        for t in targets:
            unique.setdefault(t.uid, t)
        return list(unique.values()), notes

    # ---- buyruqlar --------------------------------------------------------------
    async def cmd_help(self, message: Any, args: List[str]) -> None:
        await self.say(HELP_TEXT)

    async def cmd_on(self, message: Any, args: List[str]) -> None:
        self.store.enabled = True
        self.store.touch()
        await self.say("✅ Avto-javob <b>yoqildi</b>.")

    async def cmd_off(self, message: Any, args: List[str]) -> None:
        self.store.enabled = False
        self.store.touch()
        self.engine.cancel_all("avto-javob /off qilindi")
        await self.say("⛔ Avto-javob <b>o'chirildi</b>. (Xavfsizlik skaneri ishlashda davom etadi.)")

    async def cmd_add(self, message: Any, args: List[str]) -> None:
        targets, notes = await self._collect_targets(message, args, local_first=False)
        if not targets and not notes:
            await self.say(
                "➕ <b>Odam qo'shish</b> — ID so'ralmaydi:\n"
                "1️⃣ <code>/add @username</code>\n"
                "2️⃣ Odamning xabarini shu yerga <b>forward</b> qiling, so'ng "
                "<code>/add</code> yozing (yoki forward xabarga reply qiling)\n"
                "3️⃣ <code>/add 123456789</code>"
            )
            return
        lines: List[str] = []
        for t in targets:
            key = str(t.uid)
            existing = self.store.selected.get(key)
            record = {
                "name": t.name,
                "username": t.username,
                "added": existing.get("added") if existing else time.time(),
            }
            self.store.selected[key] = record
            label = mention(t.uid, t.name) + (f" (@{esc(t.username)})" if t.username else "")
            tail = "" if t.resolved else " — <i>ism noma'lum, ID bo'yicha qo'shildi</i>"
            lines.append(("♻️ Allaqachon ro'yxatda: " if existing else "✅ Qo'shildi: ") + f"{label} — <code>{t.uid}</code>{tail}")
        if targets:
            self.store.touch()
            self.pending_forward = None
        lines += [f"⚠️ {n}" for n in notes]
        if self.store.mode == "all":
            lines.append("\nℹ️ Hozir rejim <b>all</b> — ro'yxat hisobga olinmaydi. <code>/mode selected</code>")
        lines.append(f"\n📋 Jami tanlanganlar: <b>{len(self.store.selected)}</b>")
        await self.say("\n".join(lines))

    async def cmd_remove(self, message: Any, args: List[str]) -> None:
        if args and args[0].lower() == "all":
            count = len(self.store.selected)
            self.store.selected.clear()
            self.store.touch()
            self.engine.cancel_all("ro'yxat tozalandi")
            await self.say(f"🗑 Ro'yxat tozalandi ({count} ta).")
            return
        targets, notes = await self._collect_targets(message, args, local_first=True)
        if not targets and not notes:
            await self.say("➖ Foydalanish: <code>/remove @username</code> | ID | forward+reply | <code>/remove all</code>")
            return
        lines: List[str] = []
        for t in targets:
            if self.store.selected.pop(str(t.uid), None) is not None:
                self.store.reset_chat(t.uid)
                self.engine.cancel_sequence(t.uid, "ro'yxatdan olib tashlandi")
                lines.append(f"🗑 Olib tashlandi: {mention(t.uid, t.name)} — <code>{t.uid}</code>")
                self.store.touch()
            else:
                lines.append(f"ℹ️ Ro'yxatda yo'q: {mention(t.uid, t.name)} — <code>{t.uid}</code>")
        lines += [f"⚠️ {n}" for n in notes]
        lines.append(f"\n📋 Qoldi: <b>{len(self.store.selected)}</b>")
        await self.say("\n".join(lines))

    @staticmethod
    def _stage_label(stage: int) -> str:
        if stage <= 0:
            return "yangi"
        if stage == 1:
            return "1-javob yuborilgan"
        return "jim (sizning javobingiz kutilmoqda)"

    async def cmd_list(self, message: Any, args: List[str]) -> None:
        if not self.store.selected:
            await self.say("📋 Tanlanganlar ro'yxati bo'sh. <code>/add @username</code> bilan qo'shing.")
            return
        lines = [f"📋 <b>Tanlanganlar ({len(self.store.selected)})</b> — rejim: <b>{self.store.mode}</b>\n"]
        for index, (key, rec) in enumerate(self.store.selected.items(), start=1):
            stage = int(self.store.chats.get(key, {}).get("stage", 0))
            uname = f" (@{esc(rec['username'])})" if rec.get("username") else ""
            lines.append(
                f"{index}. {mention(int(key), rec.get('name') or key)}{uname} — "
                f"<code>{key}</code> · {self._stage_label(stage)}"
            )
        await self.say("\n".join(lines))

    def _status_block(self) -> str:
        active = sum(1 for t in self.engine.tasks.values() if not t.done())
        silent = sum(1 for v in self.store.chats.values() if int(v.get("stage", 0)) >= 2)
        mode_text = "faqat tanlanganlarga" if self.store.mode == "selected" else "barcha shaxsiy chatlarga"
        return (
            f"• Avto-javob: {'✅ yoqilgan' if self.store.enabled else '⛔ o`chirilgan'}\n"
            f"• Rejim: <b>{self.store.mode}</b> ({mode_text})\n"
            f"• Tanlanganlar: <b>{len(self.store.selected)}</b>\n"
            f"• Karantinda: <b>{len(self.store.quarantine)}</b>\n"
            f"• Hozir ishlayotgan javoblar: <b>{active}</b>\n"
            f"• Jim turgan suhbatlar: <b>{silent}</b>\n"
            f"• Yuborilgan avto-javoblar: <b>{self.store.stats['replies_sent']}</b>\n"
            f"• Bekor qilinganlar: <b>{self.store.stats['aborted']}</b>\n"
            f"• Karantinga olinganlar (jami): <b>{self.store.stats['quarantined']}</b>\n"
            f"• Ishlash vaqti: {human_duration(time.time() - START_TS)}\n"
            f"• Python {platform.python_version()} · Pyrogram {esc(str(PYROGRAM_VERSION))}"
        )

    async def cmd_status(self, message: Any, args: List[str]) -> None:
        await self.say("📊 <b>Holat</b>\n" + self._status_block())

    async def cmd_panel(self, message: Any, args: List[str]) -> None:
        text = (
            "🎛 <b>Boshqaruv paneli</b>\n\n"
            + self._status_block()
            + "\n\n<b>Faol suhbat himoyasi:</b>\n"
            f"• Siz yozgandan keyin {int(Config.OWNER_ACTIVE_WINDOW // 60)} daqiqa jim\n"
            f"• Siz o'qigandan keyin {int(Config.READ_ACTIVE_WINDOW)} soniya jim\n\n"
            "<b>Tezkor buyruqlar:</b>\n"
            "<code>/on</code> · <code>/off</code> · <code>/add</code> · <code>/remove</code> · "
            "<code>/list</code> · <code>/mode</code> · <code>/quarantine</code> · "
            "<code>/release</code> · <code>/reset</code> · <code>/help</code>"
        )
        await self.say(text)

    async def cmd_mode(self, message: Any, args: List[str]) -> None:
        if not args:
            await self.say(
                f"⚙️ Joriy rejim: <b>{self.store.mode}</b>\n"
                "<code>/mode selected</code> — faqat tanlanganlarga\n"
                "<code>/mode all</code> — barcha shaxsiy chatlarga"
            )
            return
        value = args[0].lower()
        if value in {"selected", "tanlangan", "tanlanganlar"}:
            self.store.mode = "selected"
        elif value in {"all", "hamma", "barcha"}:
            self.store.mode = "all"
        else:
            await self.say("⚠️ Rejim: <code>selected</code> yoki <code>all</code>")
            return
        self.store.touch()
        await self.say(f"⚙️ Rejim o'zgardi: <b>{self.store.mode}</b>")

    async def cmd_quarantine(self, message: Any, args: List[str]) -> None:
        if not self.store.quarantine:
            await self.say("🛡 Karantin bo'sh.")
            return
        lines = [f"🚨 <b>Karantin ({len(self.store.quarantine)})</b>\n"]
        for index, (key, rec) in enumerate(self.store.quarantine.items(), start=1):
            uname = f" (@{esc(rec['username'])})" if rec.get("username") else ""
            reasons = rec.get("reasons") or []
            first = esc(str(reasons[0])) if reasons else "—"
            lines.append(
                f"{index}. {mention(int(key), rec.get('name') or key)}{uname} — <code>{key}</code>\n"
                f"   ↳ {first}"
            )
        lines.append("\nChiqarish: <code>/release ID</code> yoki <code>/release all</code>")
        await self.say("\n".join(lines))

    async def cmd_release(self, message: Any, args: List[str]) -> None:
        if args and args[0].lower() == "all":
            count = len(self.store.quarantine)
            self.store.quarantine.clear()
            self.store.touch()
            await self.say(f"✅ Karantin tozalandi ({count} ta).")
            return
        targets, notes = await self._collect_targets(message, args, local_first=True)
        if not targets and not notes:
            await self.say("Foydalanish: <code>/release @username|ID|all</code>")
            return
        lines: List[str] = []
        for t in targets:
            if self.store.quarantine.pop(str(t.uid), None) is not None:
                self.store.touch()
                lines.append(f"✅ Karantindan chiqarildi: {mention(t.uid, t.name)} — <code>{t.uid}</code>")
            else:
                lines.append(f"ℹ️ Karantinda emas: {mention(t.uid, t.name)} — <code>{t.uid}</code>")
        lines += [f"⚠️ {n}" for n in notes]
        await self.say("\n".join(lines))

    async def cmd_reset(self, message: Any, args: List[str]) -> None:
        if args and args[0].lower() == "all":
            count = len(self.store.chats)
            self.store.chats.clear()
            self.store.touch()
            self.engine.cancel_all("bosqichlar nolga qaytarildi")
            await self.say(f"♻️ Barcha suhbat bosqichlari nolga qaytarildi ({count} ta).")
            return
        targets, notes = await self._collect_targets(message, args, local_first=True)
        if not targets and not notes:
            await self.say("Foydalanish: <code>/reset @username|ID|all</code>")
            return
        lines: List[str] = []
        for t in targets:
            self.engine.cancel_sequence(t.uid, "reset")
            self.engine.owner_out.pop(t.uid, None)
            self.engine.owner_read.pop(t.uid, None)
            self.store.reset_chat(t.uid)
            lines.append(f"♻️ Nolga qaytarildi: {mention(t.uid, t.name)} — <code>{t.uid}</code>")
        lines += [f"⚠️ {n}" for n in notes]
        await self.say("\n".join(lines))

    # ---- hayot sikli ------------------------------------------------------------
    async def _start_client(self) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            attempt += 1
            self.client = self._make_client()
            try:
                await self.client.start()
                return
            except AuthKeyDuplicated:
                log.warning("AUTH_KEY_DUPLICATED — eski nusxa to'xtashini kutyapman (%d)", attempt)
                delay = 20
            except FATAL_AUTH_ERRORS as exc:
                log.critical("STRING_SESSION yaroqsiz yoki bekor qilingan: %r. Yangisini oling.", exc)
                self.exit_code = 3
                self.stop_event.set()
                raise SystemExit(3)
            except FloodWait as exc:
                delay = min(flood_seconds(exc, 10.0) + 1, 300)
                log.warning("FloodWait %.0fs — kutilmoqda", delay)
            except (ConnectionError, OSError, asyncio.TimeoutError, TimeoutError) as exc:
                delay = min(5 * attempt, 60)
                log.warning("Ulanish xatosi (%r) — %ds dan keyin qayta uriniladi", exc, delay)
            except RPCError as exc:
                delay = min(10 * attempt, 120)
                log.warning("Telegram xatosi (%r) — %ds dan keyin qayta uriniladi", exc, delay)
            with contextlib.suppress(Exception):
                await self.client.stop()
            if attempt >= 12:
                log.critical("Telegramga ulanib bo'lmadi — chiqilmoqda (Render qayta ishga tushiradi)")
                self.exit_code = 1
                raise SystemExit(1)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)

    async def _autosave_loop(self) -> None:
        while not self.stop_event.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=Config.AUTOSAVE_INTERVAL)
            if self.store.dirty:
                try:
                    await self.store.flush(self.client, self.me_id)
                except Exception:
                    log.exception("Avto-saqlashda xatolik")

    async def _watchdog_loop(self) -> None:
        failures = 0
        while not self.stop_event.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=Config.WATCHDOG_INTERVAL)
            if self.stop_event.is_set():
                return
            try:
                await asyncio.wait_for(self.client.get_me(), timeout=45)  # type: ignore[union-attr]
                failures = 0
                RUNTIME["connected"] = True
                RUNTIME["last_ok"] = time.time()
            except Exception as exc:
                failures += 1
                RUNTIME["connected"] = False
                log.warning("Watchdog: ulanish tekshiruvi muvaffaqiyatsiz (%d/3): %r", failures, exc)
                if failures >= 3:
                    log.critical("Watchdog: ulanish tiklanmadi — jarayon qayta ishga tushiriladi")
                    self.exit_code = 1
                    self.stop_event.set()
                    return

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

    async def run(self) -> int:
        self._install_signal_handlers()
        self.store.load_file()
        await self._start_client()

        me = await self.client.get_me()  # type: ignore[union-attr]
        self.me_id = me.id
        RUNTIME["connected"] = True
        RUNTIME["last_ok"] = time.time()
        log.info("Userbot ishga tushdi: %s (ID %s)", display_name(me), me.id)

        if await self.store.cloud_load(self.client, self.me_id):  # type: ignore[arg-type]
            self.store.save_file()

        self.bg_tasks = [
            asyncio.create_task(self._autosave_loop(), name="autosave"),
            asyncio.create_task(self._watchdog_loop(), name="watchdog"),
        ]

        if Config.STARTUP_NOTICE:
            await self.say(
                "🟢 <b>Userbot ishga tushdi.</b>\n"
                f"Avto-javob: {'yoqilgan' if self.store.enabled else 'o`chirilgan'} · "
                f"rejim: <b>{self.store.mode}</b> · tanlanganlar: <b>{len(self.store.selected)}</b>\n"
                "Yordam: <code>/help</code>"
            )

        await self.stop_event.wait()
        await self.shutdown()
        return self.exit_code

    async def shutdown(self) -> None:
        log.info("To'xtatilmoqda...")
        self.engine.cancel_all("o'chirilmoqda")
        for task in self.bg_tasks:
            task.cancel()
        for task in self.bg_tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self.client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.store.flush(self.client, self.me_id), timeout=15)
            RUNTIME["connected"] = False
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.client.stop(), timeout=15)
        log.info("To'xtatildi.")


# ==============================================================================
# 10. STRING SESSION GENERATORI  (python main.py --session)
# ==============================================================================
async def generate_session() -> None:
    print("=== STRING_SESSION generatori ===")
    api_id = int(Config.API_ID or input("API_ID: ").strip())
    api_hash = Config.API_HASH or input("API_HASH: ").strip()
    async with Client("session_generator", api_id=api_id, api_hash=api_hash, in_memory=True) as app:
        session = await app.export_session_string()
    print("\nSizning STRING_SESSION (hech kimga bermang!):\n")
    print(session)
    print("\nUni Render'dagi STRING_SESSION environment variable'iga qo'ying.")


# ==============================================================================
# 11. KIRISH NUQTASI
# ==============================================================================
async def amain() -> int:
    app = UserbotApp()  # Client va asyncio obyektlari ishlayotgan loop ichida yaratiladi
    return await app.run()


def _shutdown_loop() -> None:
    with contextlib.suppress(Exception):
        pending = [t for t in asyncio.all_tasks(LOOP) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            LOOP.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        LOOP.run_until_complete(LOOP.shutdown_asyncgens())
    with contextlib.suppress(Exception):
        LOOP.close()


def main() -> None:
    if "--session" in sys.argv:
        try:
            LOOP.run_until_complete(generate_session())
        finally:
            _shutdown_loop()
        return

    missing = [
        name
        for name, value in (
            ("API_ID", Config.API_ID),
            ("API_HASH", Config.API_HASH),
            ("STRING_SESSION", Config.STRING_SESSION),
        )
        if not value
    ]
    if missing:
        log.critical("Majburiy environment o'zgaruvchilar yo'q: %s", ", ".join(missing))
        sys.exit(2)

    start_keepalive_server()
    start_self_ping()

    exit_code = 0
    try:
        exit_code = LOOP.run_until_complete(amain())
    except SystemExit as exc:
        exit_code = int(exc.code or 0) if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        log.info("Ctrl+C — to'xtatilmoqda")
    except Exception:
        log.exception("Kutilmagan halokatli xatolik")
        exit_code = 1
    finally:
        _shutdown_loop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
