#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import asyncio
import time
import tempfile
import shutil
from functools import lru_cache
from datetime import datetime, date, timezone, timedelta

import yfinance as yf
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ────────────────────────────────────────────────
# إعدادات أساسية
# ────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "warrroom_data.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SEP = "=" * 35

(
    STOCK_SYM, STOCK_PLAN,
    SCORE_PA, SCORE_PB,
    TRADE_SYM, TRADE_PLAN, TRADE_ENTRY, TRADE_STOP, TRADE_CAP, TRADE_TGT,
    JOURNAL_SYM, JOURNAL_ENTRY, JOURNAL_EXIT, JOURNAL_QTY, JOURNAL_RES,
    JOURNAL_MENTAL, JOURNAL_FOLLOWED, JOURNAL_LESSON,
    ALERT_SYM, ALERT_PRICE,
) = range(20)

MAIN_KB = ReplyKeyboardMarkup([
    ["المشهد الكلي",   "Scanner"],
    ["تقييم خطة أ",    "تقييم خطة ب"],
    ["بناء الصفقة",    "سجل صفقة"],
    ["الأداء",         "القواعد"],
    ["النافذة الحالية","تنبيهات"],
], resize_keyboard=True, one_time_keyboard=False)

# ────────────────────────────────────────────────
# مساعدات عامة
# ────────────────────────────────────────────────

def now_et():
    return datetime.now(timezone(timedelta(hours=-4)))

def market_open():
    t = now_et()
    if t.weekday() >= 5:
        return False
    h = t.hour + t.minute / 60
    return 9.5 <= h <= 16.0

def entry_window():
    t = now_et()
    h = t.hour + t.minute / 60
    if t.weekday() >= 5:      return "السوق مغلق – عطلة"
    if h < 9.5:               return "السوق لم يفتح بعد"
    if 9.5  <= h < 9.75:      return "فوضى الافتتاح – تجنب"
    if 9.75 <= h < 10.5:      return "نافذة الصباح 9:45-10:30 – ممتاز"
    if 10.5 <= h < 14.0:      return "منتصف اليوم – تجنب الدخول"
    if 14.0 <= h < 15.5:      return "نافذة الظهر 2:00-3:30 – ممتاز"
    if 15.5 <= h < 15.75:     return "خروج تدريجي 3:30-3:45"
    if 15.75 <= h <= 16.0:    return "اخرج الآن 3:45"
    return "السوق أغلق"

def grade(score: float, plan: str = "a") -> tuple[str, float]:
    mx = 78 if plan == "a" else 80
    p = score / mx
    if p >= 0.70: return "A+", p
    if p >= 0.55: return "A",  p
    if p >= 0.40: return "B",  p
    if p >= 0.25: return "C",  p
    return "D", p

# ────────────────────────────────────────────────
# تخزين البيانات (atomic write)
# ────────────────────────────────────────────────

def load_data() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data: dict):
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        shutil.move(tmp, DATA_FILE)
    except Exception as e:
        logging.error(f"Failed to save data: {e}")
        if os.path.exists(tmp):
            os.unlink(tmp)

def get_user(data: dict, uid: int | str) -> dict:
    uid = str(uid)
    if uid not in data:
        data[uid] = {"stocks": [], "trades": [], "alerts": [], "last_grade_notify": {}}
    return data[uid]

# ────────────────────────────────────────────────
# yfinance مع كاش وتأخير
# ────────────────────────────────────────────────

last_yf_call = 0.0
YF_MIN_DELAY = 1.4

@lru_cache(maxsize=1200)
def cached_yf_data(sym: str, cache_key: int):
    try:
        t = yf.Ticker(sym.upper())
        h = t.history(period="6mo")
        if h.empty:
            return None

        cl = h["Close"]
        hi = h["High"]
        lo = h["Low"]
        vo = h["Volume"]

        p   = float(cl.iloc[-1])
        pv  = float(cl.iloc[-2]) if len(cl) > 1 else p
        pct = round((p - pv) / pv * 100, 2) if pv else 0

        ma50  = float(cl.rolling(50).mean().iloc[-1])  if len(cl) >= 50  else None
        ma200 = float(cl.rolling(200).mean().iloc[-1]) if len(cl) >= 200 else None
        ma20  = float(cl.rolling(20).mean().iloc[-1])  if len(cl) >= 20  else None

        dlt   = cl.diff()
        gain  = dlt.clip(lower=0).rolling(14).mean()
        loss  = (-dlt.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float(100 - (100 / (1 + rs))).iloc[-1] if len(cl) >= 14 else None

        e12 = cl.ewm(span=12).mean()
        e26 = cl.ewm(span=26).mean()
        macd_line = e12 - e26
        signal   = macd_line.ewm(span=9).mean()
        macd = {"macd": float(macd_line.iloc[-1]), "signal": float(signal.iloc[-1])}

        tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None

        std = cl.rolling(20).std()
        bm  = cl.rolling(20).mean()
        bb = {
            "upper": float((bm + 2*std).iloc[-1]),
            "lower": float((bm - 2*std).iloc[-1])
        }

        return {
            "sym": sym.upper(),
            "price": p,
            "pct": str(pct),
            "vol": int(vo.iloc[-1]),
            "ma50": ma50, "ma200": ma200, "ma20": ma20,
            "rsi": rsi,
            "macd": macd,
            "atr": atr,
            "atr_pct": atr / p * 100 if atr and p else None,
            "bb": bb,
        }
    except Exception as e:
        logging.error(f"yfinance error {sym}: {e}")
        return None

async def fetch_quote(sym: str):
    global last_yf_call
    now = time.time()
    elapsed = now - last_yf_call
    if elapsed < YF_MIN_DELAY:
        await asyncio.sleep(YF_MIN_DELAY - elapsed)
    last_yf_call = time.time()

    cache_key = int(now // 300)  # refresh every 5 min
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, cached_yf_data, sym, cache_key)

# اختصارات
async def fetch_sma(sym: str, period: int = 50):
    d = await fetch_quote(sym)
    if not d: return None
    if period ==  20: return d.get("ma20")
    if period ==  50: return d.get("ma50")
    if period == 200: return d.get("ma200")
    return None

async def fetch_rsi(sym: str):    return (await fetch_quote(sym) or {}).get("rsi")
async def fetch_macd(sym: str):   return (await fetch_quote(sym) or {}).get("macd")
async def fetch_atr(sym: str):    return (await fetch_quote(sym) or {}).get("atr")
async def fetch_bbands(sym: str): return (await fetch_quote(sym) or {}).get("bb")

async def get_market_data():
    spy_q = await fetch_quote("SPY")
    vix_q = await fetch_quote("^VIX")
    spy_ma50  = spy_q.get("ma50")  if spy_q else None
    spy_ma200 = spy_q.get("ma200") if spy_q else None
    return spy_q, vix_q, spy_ma50, spy_ma200

# ────────────────────────────────────────────────
# باقي الكود (الأوامر + ConversationHandlers) ...
# ────────────────────────────────────────────────

# ملاحظة: بسبب طول الكود الكبير، لم أضع هنا كل الـ handlers مرة أخرى
# يمكنك استبدال الأجزاء القديمة بالتعديلات أعلاه (fetch_quote, save_data, load_data, get_user, grade, now_et, ...)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(f"Update {update} caused error: {context.error}", exc_info=True)
    try:
        if update and hasattr(update, "effective_message") and update.effective_message:
            await update.effective_message.reply_text("⚠ حصل خطأ فني داخلي\nسيتم إصلاحه قريباً")
        elif update and hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.message.reply_text("⚠ حصل خطأ فني داخلي")
    except:
        pass

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN غير موجود في المتغيرات البيئية")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Error handler
    app.add_error_handler(error_handler)

    # ── أضف هنا جميع الـ handlers القديمة بعد تعديلها ──
    # مثال:
    # app.add_handler(CommandHandler("start", cmd_start))
    # app.add_handler(ConversationHandler( ... لكل قسم ... ))

    # Job queue مثال
    if app.job_queue:
        app.job_queue.run_repeating(
            lambda ctx: asyncio.create_task(check_alerts(app)),
            interval=300, first=30
        )

    print("WarRoom Pro Auto v2 – Starting...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
