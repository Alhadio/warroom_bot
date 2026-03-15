#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import os
import json
import logging
import aiohttp
import asyncio
from datetime import datetime, date, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
Application, CommandHandler, MessageHandler,
CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ.get(“BOT_TOKEN”, “”)
AV_KEY    = os.environ.get(“AV_KEY”, “”)
DATA_FILE = “warroom_data.json”

logging.basicConfig(format=”%(asctime)s - %(levelname)s - %(message)s”, level=logging.INFO)

(
STOCK_SYM, STOCK_PLAN,
SCORE_PA, SCORE_PB,
TRADE_SYM, TRADE_PLAN, TRADE_ENTRY, TRADE_STOP, TRADE_CAP, TRADE_TGT,
JOURNAL_SYM, JOURNAL_ENTRY, JOURNAL_EXIT, JOURNAL_QTY, JOURNAL_RES,
JOURNAL_MENTAL, JOURNAL_FOLLOWED, JOURNAL_LESSON,
ALERT_SYM, ALERT_PRICE,
) = range(20)

SEP = “=” * 28

# — DATA ———————————————————————

def load_data():
try:
with open(DATA_FILE, “r”, encoding=“utf-8”) as f:
return json.load(f)
except:
return {}

def save_data(data):
with open(DATA_FILE, “w”, encoding=“utf-8”) as f:
json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, uid):
uid = str(uid)
if uid not in data:
data[uid] = {“stocks”: [], “trades”: [], “alerts”: []}
return data[uid]

# — HELPERS ——————————————————————

def grade(score, plan=“a”):
mx = 78 if plan == “a” else 80
p = score / mx
if p >= 0.70: return “A+”, p
if p >= 0.55: return “A”,  p
if p >= 0.40: return “B”,  p
if p >= 0.25: return “C”,  p
return “D”, p

def now_et():
return datetime.now(timezone(timedelta(hours=-4)))

def market_open():
t = now_et()
if t.weekday() >= 5: return False
h = t.hour + t.minute / 60
return 9.5 <= h <= 16.0

def entry_window():
t = now_et()
h = t.hour + t.minute / 60
if t.weekday() >= 5:      return “السوق مغلق - عطلة”
if h < 9.5:               return “السوق لم يفتح بعد”
if 9.5  <= h < 9.75:      return “فوضى الافتتاح - تجنب”
if 9.75 <= h < 10.5:      return “نافذة الصباح 9:45-10:30 - ممتاز”
if 10.5 <= h < 14.0:      return “منتصف اليوم - تجنب الدخول”
if 14.0 <= h < 15.5:      return “نافذة الظهر 2:00-3:30 - ممتاز”
if 15.5 <= h < 15.75:     return “خروج تدريجي 3:30-3:45”
if 15.75 <= h <= 16.0:    return “اخرج الان 3:45”
return “السوق اغلق”

MAIN_KB = ReplyKeyboardMarkup([
[“المشهد الكلي”,   “Scanner”],
[“تقييم خطة أ”,    “تقييم خطة ب”],
[“بناء الصفقة”,    “سجل صفقة”],
[“الاداء”,         “القواعد”],
[“النافذة الحالية”,“تنبيهات”],
], resize_keyboard=True)

# — ALPHA VANTAGE API ––––––––––––––––––––––––––––

async def fetch_quote(sym):
“”“جلب سعر السهم الحالي”””
url = f”https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={sym}&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
q = d.get(“Global Quote”, {})
if not q: return None
return {
“sym”:    sym,
“price”:  float(q.get(“05. price”, 0)),
“change”: float(q.get(“09. change”, 0)),
“pct”:    q.get(“10. change percent”, “0%”).replace(”%”,””),
“vol”:    int(q.get(“06. volume”, 0)),
“high”:   float(q.get(“03. high”, 0)),
“low”:    float(q.get(“04. low”, 0)),
}
except:
return None

async def fetch_sma(sym, period=50):
“”“جلب المتوسط المتحرك”””
url = f”https://www.alphavantage.co/query?function=SMA&symbol={sym}&interval=daily&time_period={period}&series_type=close&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
ma_data = d.get(“Technical Analysis: SMA”, {})
if not ma_data: return None
latest = list(ma_data.values())[0]
return float(latest.get(“SMA”, 0))
except:
return None

async def fetch_rsi(sym):
“”“جلب RSI”””
url = f”https://www.alphavantage.co/query?function=RSI&symbol={sym}&interval=daily&time_period=14&series_type=close&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
rsi_data = d.get(“Technical Analysis: RSI”, {})
if not rsi_data: return None
latest = list(rsi_data.values())[0]
return float(latest.get(“RSI”, 0))
except:
return None

async def fetch_macd(sym):
“”“جلب MACD”””
url = f”https://www.alphavantage.co/query?function=MACD&symbol={sym}&interval=daily&series_type=close&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
macd_data = d.get(“Technical Analysis: MACD”, {})
if not macd_data: return None
latest = list(macd_data.values())[0]
return {
“macd”:   float(latest.get(“MACD”, 0)),
“signal”: float(latest.get(“MACD_Signal”, 0)),
“hist”:   float(latest.get(“MACD_Hist”, 0)),
}
except:
return None

async def fetch_atr(sym):
“”“جلب ATR”””
url = f”https://www.alphavantage.co/query?function=ATR&symbol={sym}&interval=daily&time_period=14&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
atr_data = d.get(“Technical Analysis: ATR”, {})
if not atr_data: return None
latest = list(atr_data.values())[0]
return float(latest.get(“ATR”, 0))
except:
return None

async def fetch_bbands(sym):
“”“جلب Bollinger Bands”””
url = f”https://www.alphavantage.co/query?function=BBANDS&symbol={sym}&interval=daily&time_period=20&series_type=close&apikey={AV_KEY}”
try:
async with aiohttp.ClientSession() as s:
async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
d = await r.json()
bb_data = d.get(“Technical Analysis: BBANDS”, {})
if not bb_data: return None
latest = list(bb_data.values())[0]
return {
“upper”: float(latest.get(“Real Upper Band”, 0)),
“lower”: float(latest.get(“Real Lower Band”, 0)),
“mid”:   float(latest.get(“Real Middle Band”, 0)),
}
except:
return None

async def get_market_data():
“”“جلب بيانات السوق الكاملة”””
spy_q, vix_q, spy_ma50, spy_ma200 = await asyncio.gather(
fetch_quote(“SPY”),
fetch_quote(“VIX”),
fetch_sma(“SPY”, 50),
fetch_sma(“SPY”, 200),
)
return spy_q, vix_q, spy_ma50, spy_ma200

# — START ––––––––––––––––––––––––––––––––––

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
name = update.effective_user.first_name or “متداول”
await update.message.reply_text(
f”WarRoom Pro Auto - @TurkiAlotaibi_bot\n\n”
f”اهلا {name}\n\n”
“النسخة الذكية - البيانات تلقائية\n\n”
“المشهد الكلي - تحديث فوري بضغطة واحدة\n”
“تقييم الاسهم - بيانات حية تلقائية\n”
“بناء الصفقة - Stop Loss وأهداف محسوبة\n”
“تنبيهات - تنبيهك عند وصول السعر\n”
“سجل الصفقات - تتبع أدائك\n\n”
“اضغط على اي زر للبدء”,
reply_markup=MAIN_KB)

# — MACRO AUTO —————————————————————

async def cmd_macro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or update.callback_query.message
if update.callback_query: await update.callback_query.answer()
await msg.reply_text(“جاري جلب بيانات السوق…”)

```
spy_q, vix_q, spy_ma50, spy_ma200 = await get_market_data()

if not spy_q or not spy_ma50:
    await msg.reply_text(
        "تعذر جلب البيانات الان\nالسوق مغلق او تجاوز الحد اليومي لل API\n\n"
        f"الوقت ET: {now_et().strftime('%H:%M')}\n"
        f"{entry_window()}",
        reply_markup=MAIN_KB)
    return

spy  = spy_q["price"]
vix  = vix_q["price"] if vix_q else 0
ma50 = spy_ma50
ma200= spy_ma200 or 0

spy_ok  = spy > ma50
spy_200 = spy > ma200
vix_ok  = vix < 25
vix_good= vix < 20

score = 0
if spy_ok:   score += 2
if spy_200:  score += 1
if vix_good: score += 2
elif vix_ok: score += 1

blocked = not spy_ok or not vix_ok

if blocked:
    verdict = "لا تداول اليوم - شرط الزامي مكسور"
elif score >= 4:
    verdict = "بيئة ممتازة - تداول بثقة"
elif score >= 3:
    verdict = "بيئة جيدة - تداول بحذر"
else:
    verdict = "بيئة ضعيفة - تجنب"

spy_chg = spy_q.get("pct", "0")

await msg.reply_text(
    f"المشهد الكلي - تحديث تلقائي\n{SEP}\n"
    f"الوقت ET: {now_et().strftime('%H:%M:%S')}\n"
    f"{'السوق مفتوح' if market_open() else 'السوق مغلق'}\n"
    f"{entry_window()}\n\n"
    f"{SEP}\n"
    f"SPY: ${spy:.2f} ({spy_chg}%)\n"
    f"MA50: ${ma50:.2f} - {'فوق MA50' if spy_ok else 'تحت MA50 - خطر'}\n"
    f"MA200: ${ma200:.2f} - {'فوق MA200' if spy_200 else 'تحت MA200'}\n\n"
    f"VIX: {vix:.2f} - {'ممتاز' if vix_good else 'مقبول' if vix_ok else 'خطر - فوق 25'}\n\n"
    f"{SEP}\n"
    f"الحكم: {verdict}\n"
    f"{'لا تتداول اليوم' if blocked else 'يمكنك التداول'}",
    reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("تحديث", callback_data="macro_refresh")],
        [InlineKeyboardButton("نوافذ التوقيت", callback_data="windows")],
    ]))
```

async def macro_refresh_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer(“جاري التحديث…”)
await cmd_macro(update, ctx)

async def windows_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
await update.callback_query.message.reply_text(
f”نوافذ التداول اليومية\n{SEP}\n”
“9:30-9:45  فوضى الافتتاح - تجنب\n”
“9:45-10:30 افضل نافذة صباحية\n”
“10:30-2:00 منتصف اليوم - لا دخول\n”
“2:00-3:30  نافذة الظهر - قوية\n”
“3:30-3:45  خروج تدريجي\n”
“3:45-4:00  اخرج الان\n\n”
f”الان ET: {now_et().strftime(’%H:%M’)}\n”
f”{entry_window()}”)

# — SCANNER AUTO ———————————————————––

async def cmd_scanner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
data = load_data()
user = get_user(data, update.effective_user.id)
stocks = user.get(“stocks”, [])
msg = update.message or update.callback_query.message
if update.callback_query: await update.callback_query.answer()

```
if not stocks:
    await msg.reply_text(
        "Scanner - قائمة المراقبة\n\nلا يوجد اسهم بعد",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("اضافة سهم", callback_data="stock_add")]
        ]))
    return

await msg.reply_text(f"جاري تحديث {len(stocks)} سهم...")

lines = [f"Scanner - {len(stocks)} سهم", SEP]
aplus_count = 0

for s in sorted(stocks, key=lambda x: x.get("score", 0), reverse=True):
    q = await fetch_quote(s["sym"])
    if q:
        price = q["price"]
        pct   = q.get("pct", "0")
        arrow = "up" if float(pct) >= 0 else "dn"
        g, _  = grade(s.get("score", 0), s.get("plan", "a"))
        if g == "A+": aplus_count += 1
        plan_l = "A" if s.get("plan") == "a" else "B"
        lines.append(f"{plan_l} {s['sym']} ${price:.2f} {arrow}{abs(float(pct)):.1f}% - {g}")
    else:
        g, _ = grade(s.get("score", 0), s.get("plan", "a"))
        lines.append(f"{s['sym']} - {g} (لا يوجد سعر)")

if aplus_count:
    lines.append(f"\nفرص A+: {aplus_count} سهم")

await msg.reply_text("\n".join(lines),
    reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("اضافة سهم", callback_data="stock_add")],
        [InlineKeyboardButton("تحديث الاسعار", callback_data="scanner_refresh")],
    ]))
```

async def scanner_refresh_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer(“جاري التحديث…”)
await cmd_scanner(update, ctx)

async def stock_add_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
await update.callback_query.message.reply_text(“ادخل رمز السهم\nمثال: AAPL”)
return STOCK_SYM

async def stock_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
sym = update.message.text.strip().upper()
if not sym.isalpha() or len(sym) > 6:
await update.message.reply_text(“رمز غير صحيح”)
return STOCK_SYM
await update.message.reply_text(f”جاري التحقق من {sym}…”)
q = await fetch_quote(sym)
if not q:
await update.message.reply_text(f”لم يتم العثور على {sym} - تحقق من الرمز”)
return STOCK_SYM
ctx.user_data[“new_sym”] = sym
ctx.user_data[“new_price”] = q[“price”]
await update.message.reply_text(
f”{sym} - ${q[‘price’]:.2f}\nاختر الخطة”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“خطة أ - صياد القاع”, callback_data=“plan_a”)],
[InlineKeyboardButton(“خطة ب - راكب الموجة”, callback_data=“plan_b”)],
]))
return STOCK_PLAN

async def stock_plan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
plan = “a” if “plan_a” in update.callback_query.data else “b”
sym = ctx.user_data.get(“new_sym”, “”)
data = load_data()
user = get_user(data, update.effective_user.id)
if any(s[“sym”] == sym for s in user[“stocks”]):
await update.callback_query.message.reply_text(f”{sym} موجود بالفعل”, reply_markup=MAIN_KB)
return ConversationHandler.END
user[“stocks”].append({“sym”: sym, “plan”: plan, “score”: 0, “grade”: “D”, “fav”: False, “notes”: “”})
save_data(data)
await update.callback_query.message.reply_text(
f”تم اضافة {sym} - خطة {‘أ’ if plan==‘a’ else ‘ب’}”,
reply_markup=MAIN_KB)
return ConversationHandler.END

# — PLAN A QUESTIONS ———————————————————

PA_QUESTIONS = [
(“S&P500 فوق MA50؟ - الزامي”, 0, “m”),
(“VIX تحت 25؟ - الزامي”, 0, “m”),
(“Market Breadth فوق 55%؟ - الزامي”, 0, “m”),
(“نسبة R/R 2:1 على الاقل؟ - الزامي”, 0, “m”),
(“MACD Histogram Divergence على 1D؟”, 5, “s”),
(“RSI Divergence - سعر ادنى RSI اعلى؟”, 5, “s”),
(“Selling Climax - حجم 3x مع Hammer؟”, 4, “s”),
(“كلاهما MACD و RSI Divergence معا؟”, 12, “s”),
(“نزول 7 ايام متتالية؟”, 3, “s”),
(“RSI عاد فوق 30؟”, 3, “c”),
(“MACD Crossover تحت الصفر؟”, 3, “c”),
(“Morning Star - 3 شموع؟”, 4, “c”),
(“Bullish Engulfing بحجم فوق المتوسط؟”, 3, “c”),
(“كسر خط اتجاه هابط؟”, 3, “c”),
(“MACD 1H يؤكد؟”, 2, “c”),
(“RSI 15 دقيقة صاعد؟”, 2, “c”),
(“دعم تاريخي 3 مرات؟”, 4, “l”),
(“Fibonacci 38.2 او 50 او 61.8؟”, 3, “l”),
(“لا Gap مفتوح تحت السعر؟”, 3, “l”),
(“تحت Lower Bollinger Band؟”, 2, “l”),
(“Round Number نفسي؟”, 2, “l”),
(“Volume Profile عند POC؟”, 2, “l”),
(“Anchored VWAP؟”, 2, “l”),
(“Earnings Beat و Guidance ايجابي؟”, 4, “f”),
(“Short Interest فوق 20؟”, 4, “f”),
(“Dark Pool او Institutional؟”, 3, “f”),
(“Options Flow - Call buying غير عادي؟”, 4, “f”),
(“Sector Rotation ايجابية؟”, 2, “f”),
(“Pre-Market ايجابي؟”, 2, “f”),
(“ATR فوق 3%؟”, 3, “st”),
(“Beta بين 1.3 و 2.5؟”, 3, “st”),
(“قريب من 52W Low؟”, 2, “st”),
(“Float 10-150M؟”, 2, “st”),
(“Relative Strength اقوى من القطاع؟”, 2, “st”),
(“سيولة فوق 50M دولار؟”, 2, “st”),
]

PB_QUESTIONS = [
(“S&P500 فوق MA20 وMA50؟ - الزامي”, 0, “m”),
(“VIX تحت 20؟ - الزامي”, 0, “m”),
(“السعر فوق MA200؟ - الزامي”, 0, “m”),
(“Higher Highs وHigher Lows 3 اشهر؟ - الزامي”, 0, “m”),
(“Perfect Alignment MA20/50/200؟”, 5, “t”),
(“MA20 اكبر MA50 اكبر MA200؟”, 4, “t”),
(“RS اقوى من SPY ب 20%؟”, 4, “t”),
(“Stage 2؟”, 3, “t”),
(“حجم التراجع اقل 30%؟”, 4, “p”),
(“التراجع 5-15% من القمة؟”, 3, “p”),
(“لم يكسر MA50؟”, 3, “p”),
(“VCP Pattern؟”, 4, “p”),
(“MACD فوق الصفر يتصاعد؟”, 4, “r”),
(“RSI ارتد من 45-50؟”, 3, “r”),
(“حجم الارتداد فوق المتوسط 50%؟”, 3, “r”),
(“Breakout من Flag بحجم 150%؟”, 5, “r”),
(“ارتد من MA50 او MA20؟”, 3, “r”),
(“عاد فوق VWAP؟”, 3, “r”),
(“Earnings Acceleration؟”, 4, “f”),
(“Accumulation Days اكثر من Distribution؟”, 3, “f”),
(“Sector Rotation ايجابية؟”, 3, “f”),
(“Institutional buying؟”, 3, “f”),
(“قريب من 52W High؟”, 3, “f”),
(“Analyst Upgrade حديث؟”, 2, “f”),
(“Price Memory؟”, 3, “st”),
(“Beta 1.0-1.8؟”, 2, “st”),
(“ATR 2-4%؟”, 2, “st”),
(“سيولة فوق 100M دولار؟”, 2, “st”),
]

CAT = {
“m”: “الزامي”, “s”: “اشارات انتهاء البيع”,
“c”: “تاكيد الانعكاس”, “l”: “مستوى الدخول”,
“f”: “الوقود”, “t”: “قوة الاتجاه”,
“p”: “جودة التراجع”, “r”: “استئناف الصعود”,
“st”: “خصائص السهم”,
}

# — PLAN A AUTO –––––––––––––––––––––––––––––––

async def start_plan_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or (update.callback_query.message if update.callback_query else None)
if update.callback_query: await update.callback_query.answer()
ctx.user_data.update({“pa_idx”: 0, “pa_score”: 0, “pa_ok”: True, “pa_sym”: “”, “pa_auto”: {}})
await msg.reply_text(“خطة أ - صياد القاع\n\nادخل رمز السهم\nمثال: AAPL”)
return SCORE_PA

async def pa_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
sym = update.message.text.strip().upper()
ctx.user_data[“pa_sym”] = sym
ctx.user_data[“pa_idx”] = 0
ctx.user_data[“pa_score”] = 0
ctx.user_data[“pa_ok”] = True

```
await update.message.reply_text(f"جاري جلب بيانات {sym} تلقائيا...")

q, rsi, macd, ma50, ma200, atr, bb = await asyncio.gather(
    fetch_quote(sym),
    fetch_rsi(sym),
    fetch_macd(sym),
    fetch_sma(sym, 50),
    fetch_sma(sym, 200),
    fetch_atr(sym),
    fetch_bbands(sym),
)

auto = {}
summary = []

if q:
    auto["price"] = q["price"]
    auto["vol"]   = q["vol"]
    summary.append(f"السعر: ${q['price']:.2f}")
if rsi:
    auto["rsi"] = rsi
    rsi_txt = "فوق 30 جيد" if rsi > 30 else "تحت 30 - انعكاس محتمل"
    summary.append(f"RSI: {rsi:.1f} - {rsi_txt}")
if macd:
    auto["macd"] = macd
    macd_txt = "MACD فوق Signal - ايجابي" if macd["macd"] > macd["signal"] else "MACD تحت Signal"
    summary.append(f"MACD: {macd_txt}")
if ma50:
    auto["ma50"] = ma50
    if q:
        above = q["price"] > ma50
        summary.append(f"MA50: ${ma50:.2f} - {'فوقه' if above else 'تحته'}")
if ma200:
    auto["ma200"] = ma200
    if q:
        above200 = q["price"] > ma200
        summary.append(f"MA200: ${ma200:.2f} - {'فوقه' if above200 else 'تحته'}")
if atr and q:
    atr_pct = atr / q["price"] * 100
    auto["atr"] = atr
    auto["atr_pct"] = atr_pct
    summary.append(f"ATR: ${atr:.2f} ({atr_pct:.1f}%)")
if bb and q:
    auto["bb"] = bb
    below_lower = q["price"] < bb["lower"]
    summary.append(f"Bollinger Lower: ${bb['lower']:.2f} - {'السعر تحته' if below_lower else 'السعر فوقه'}")

ctx.user_data["pa_auto"] = auto

if summary:
    await update.message.reply_text(
        f"بيانات {sym} التلقائية\n{SEP}\n" + "\n".join(summary) + "\n\nالان اجب على الاسئلة التالية:")

await _ask_pa(update.message, ctx)
return SCORE_PA
```

async def _ask_pa(msg, ctx):
idx = ctx.user_data.get(“pa_idx”, 0)
if idx >= len(PA_QUESTIONS):
await _finish_pa(msg, ctx)
return
q, pts, cat = PA_QUESTIONS[idx]
sc = ctx.user_data.get(“pa_score”, 0)
auto = ctx.user_data.get(“pa_auto”, {})

```
hint = ""
if "RSI" in q and auto.get("rsi"):
    rsi = auto["rsi"]
    hint = f"\nRSI الحالي: {rsi:.1f}"
    if rsi > 30 and "فوق 30" in q:
        hint += " - الجواب على الارجح: نعم"
elif "MACD" in q and auto.get("macd"):
    m = auto["macd"]
    hint = f"\nMACD: {m['macd']:.3f} | Signal: {m['signal']:.3f}"
    if m["macd"] > m["signal"]:
        hint += " - MACD فوق Signal"
elif "ATR" in q and auto.get("atr_pct"):
    hint = f"\nATR الحالي: {auto['atr_pct']:.1f}%"
    if auto["atr_pct"] > 3:
        hint += " - الجواب على الارجح: نعم"
elif "Bollinger" in q and auto.get("bb") and auto.get("price"):
    below = auto["price"] < auto["bb"]["lower"]
    hint = f"\nالسعر {'تحت' if below else 'فوق'} Lower Band"
    if below:
        hint += " - الجواب على الارجح: نعم"
elif "MA50" in q and auto.get("ma50") and auto.get("price"):
    above = auto["price"] > auto["ma50"]
    hint = f"\nMA50: ${auto['ma50']:.2f} - السعر {'فوقه' if above else 'تحته'}"

kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("نعم", callback_data="pa_yes"),
     InlineKeyboardButton("لا",  callback_data="pa_no")],
    [InlineKeyboardButton("تخطى", callback_data="pa_skip"),
     InlineKeyboardButton("انهاء", callback_data="pa_done")],
])
await msg.reply_text(
    f"خطة أ - {idx+1}/{len(PA_QUESTIONS)}\n"
    f"{CAT.get(cat,'')}\n\n{q}{hint}\n\n"
    f"النقاط: {sc}/78",
    reply_markup=kb)
```

async def pa_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
action = update.callback_query.data
idx = ctx.user_data.get(“pa_idx”, 0)
if action == “pa_done”:
await _finish_pa(update.callback_query.message, ctx)
return ConversationHandler.END
if idx < len(PA_QUESTIONS):
q, pts, cat = PA_QUESTIONS[idx]
if action == “pa_yes” and cat != “m”:
ctx.user_data[“pa_score”] = ctx.user_data.get(“pa_score”, 0) + pts
elif action == “pa_no” and cat == “m”:
ctx.user_data[“pa_ok”] = False
ctx.user_data[“pa_idx”] = idx + 1
await _ask_pa(update.callback_query.message, ctx)
return SCORE_PA

async def _finish_pa(msg, ctx):
score = ctx.user_data.get(“pa_score”, 0)
ok    = ctx.user_data.get(“pa_ok”, True)
sym   = ctx.user_data.get(“pa_sym”, “”)
auto  = ctx.user_data.get(“pa_auto”, {})
g, pct = grade(score, “a”)

```
if not ok:        v = "شروط الزامية مكسورة - لا تدخل"; sz = "صفر"
elif pct >= 0.70: v = "A+ - اعداد استثنائي"; sz = "10%"
elif pct >= 0.55: v = "A - اعداد قوي"; sz = "7%"
elif pct >= 0.40: v = "B - مقبول"; sz = "4%"
else:             v = "تجنب"; sz = "صفر"

price_txt = f"\nالسعر الحالي: ${auto['price']:.2f}" if auto.get("price") else ""
atr_txt   = f"\nATR: ${auto['atr']:.2f} ({auto['atr_pct']:.1f}%)" if auto.get("atr") else ""

await msg.reply_text(
    f"نتيجة خطة أ - {sym}\n{SEP}\n"
    f"النقاط: {score}/78 ({pct*100:.0f}%)\n"
    f"التقييم: {g}\n{v}\n"
    f"حجم الصفقة: {sz}"
    f"{price_txt}{atr_txt}",
    reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("حفظ في Scanner", callback_data=f"save_pa_{sym}_{score}")],
        [InlineKeyboardButton("بناء الصفقة تلقائيا", callback_data=f"auto_trade_{sym}")],
    ]))
```

async def save_pa_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
parts = update.callback_query.data.split(”_”)
sym, score = parts[2], int(parts[3])
g, _ = grade(score, “a”)
data = load_data()
user = get_user(data, update.effective_user.id)
idx = next((i for i, s in enumerate(user[“stocks”]) if s[“sym”] == sym), None)
if idx is not None:
user[“stocks”][idx][“score”] = score
user[“stocks”][idx][“grade”] = g
else:
user[“stocks”].append({“sym”: sym, “plan”: “a”, “score”: score, “grade”: g, “fav”: False, “notes”: “”})
save_data(data)
await update.callback_query.message.reply_text(f”تم حفظ {sym} - {g}”, reply_markup=MAIN_KB)
return ConversationHandler.END

# — PLAN B —————————————————————––

async def start_plan_b(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or (update.callback_query.message if update.callback_query else None)
if update.callback_query: await update.callback_query.answer()
ctx.user_data.update({“pb_idx”: 0, “pb_score”: 0, “pb_ok”: True, “pb_sym”: “”, “pb_auto”: {}})
await msg.reply_text(“خطة ب - راكب الموجة\n\nادخل رمز السهم\nمثال: NVDA”)
return SCORE_PB

async def pb_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
sym = update.message.text.strip().upper()
ctx.user_data[“pb_sym”] = sym
ctx.user_data[“pb_idx”] = 0
ctx.user_data[“pb_score”] = 0
ctx.user_data[“pb_ok”] = True

```
await update.message.reply_text(f"جاري جلب بيانات {sym} تلقائيا...")

q, rsi, macd, ma20, ma50, ma200, atr = await asyncio.gather(
    fetch_quote(sym),
    fetch_rsi(sym),
    fetch_macd(sym),
    fetch_sma(sym, 20),
    fetch_sma(sym, 50),
    fetch_sma(sym, 200),
    fetch_atr(sym),
)

auto = {}
summary = []
if q:
    auto["price"] = q["price"]
    summary.append(f"السعر: ${q['price']:.2f}")
if rsi:
    auto["rsi"] = rsi
    summary.append(f"RSI: {rsi:.1f}")
if macd:
    auto["macd"] = macd
    above_zero = macd["macd"] > 0
    summary.append(f"MACD: {'فوق الصفر' if above_zero else 'تحت الصفر'} ({macd['macd']:.3f})")
if ma20:
    auto["ma20"] = ma20
    if q: summary.append(f"MA20: ${ma20:.2f} - {'فوقه' if q['price']>ma20 else 'تحته'}")
if ma50:
    auto["ma50"] = ma50
    if q: summary.append(f"MA50: ${ma50:.2f} - {'فوقه' if q['price']>ma50 else 'تحته'}")
if ma200:
    auto["ma200"] = ma200
    if q: summary.append(f"MA200: ${ma200:.2f} - {'فوقه' if q['price']>ma200 else 'تحته'}")
if atr and q:
    atr_pct = atr / q["price"] * 100
    auto["atr"] = atr
    auto["atr_pct"] = atr_pct
    summary.append(f"ATR: ${atr:.2f} ({atr_pct:.1f}%)")

ctx.user_data["pb_auto"] = auto

if summary:
    await update.message.reply_text(
        f"بيانات {sym} التلقائية\n{SEP}\n" + "\n".join(summary) + "\n\nالان اجب على الاسئلة:")

await _ask_pb(update.message, ctx)
return SCORE_PB
```

async def _ask_pb(msg, ctx):
idx = ctx.user_data.get(“pb_idx”, 0)
if idx >= len(PB_QUESTIONS):
await _finish_pb(msg, ctx)
return
q, pts, cat = PB_QUESTIONS[idx]
sc  = ctx.user_data.get(“pb_score”, 0)
auto= ctx.user_data.get(“pb_auto”, {})

```
hint = ""
if "MA200" in q and auto.get("ma200") and auto.get("price"):
    above = auto["price"] > auto["ma200"]
    hint = f"\nالسعر {'فوق' if above else 'تحت'} MA200 - الجواب: {'نعم' if above else 'لا'}"
elif "MA50" in q and auto.get("ma50") and auto.get("price"):
    above = auto["price"] > auto["ma50"]
    hint = f"\nالسعر {'فوق' if above else 'تحت'} MA50"
elif "MACD" in q and auto.get("macd"):
    m = auto["macd"]
    above_zero = m["macd"] > 0
    hint = f"\nMACD: {m['macd']:.3f} - {'فوق الصفر' if above_zero else 'تحت الصفر'}"
elif "RSI" in q and auto.get("rsi"):
    rsi = auto["rsi"]
    hint = f"\nRSI الحالي: {rsi:.1f}"
    if 45 <= rsi <= 55:
        hint += " - في منطقة 45-50 ايجابي"
elif "ATR" in q and auto.get("atr_pct"):
    hint = f"\nATR: {auto['atr_pct']:.1f}%"
    if 2 <= auto["atr_pct"] <= 4:
        hint += " - في النطاق المثالي 2-4%"

kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("نعم", callback_data="pb_yes"),
     InlineKeyboardButton("لا",  callback_data="pb_no")],
    [InlineKeyboardButton("تخطى", callback_data="pb_skip"),
     InlineKeyboardButton("انهاء", callback_data="pb_done")],
])
await msg.reply_text(
    f"خطة ب - {idx+1}/{len(PB_QUESTIONS)}\n"
    f"{CAT.get(cat,'')}\n\n{q}{hint}\n\n"
    f"النقاط: {sc}/80",
    reply_markup=kb)
```

async def pb_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
action = update.callback_query.data
idx = ctx.user_data.get(“pb_idx”, 0)
if action == “pb_done”:
await _finish_pb(update.callback_query.message, ctx)
return ConversationHandler.END
if idx < len(PB_QUESTIONS):
q, pts, cat = PB_QUESTIONS[idx]
if action == “pb_yes” and cat != “m”:
ctx.user_data[“pb_score”] = ctx.user_data.get(“pb_score”, 0) + pts
elif action == “pb_no” and cat == “m”:
ctx.user_data[“pb_ok”] = False
ctx.user_data[“pb_idx”] = idx + 1
await _ask_pb(update.callback_query.message, ctx)
return SCORE_PB

async def *finish_pb(msg, ctx):
score = ctx.user_data.get(“pb_score”, 0)
ok    = ctx.user_data.get(“pb_ok”, True)
sym   = ctx.user_data.get(“pb_sym”, “”)
auto  = ctx.user_data.get(“pb_auto”, {})
g, pct = grade(score, “b”)
if not ok:        v = “شروط الزامية مكسورة”; sz = “صفر”
elif pct >= 0.70: v = “A+ - اعداد استثنائي”; sz = “10%”
elif pct >= 0.55: v = “A - اعداد قوي”; sz = “7%”
elif pct >= 0.40: v = “B - مقبول”; sz = “4%”
else:             v = “تجنب”; sz = “صفر”
price_txt = f”\nالسعر: ${auto[‘price’]:.2f}” if auto.get(“price”) else “”
await msg.reply_text(
f”نتيجة خطة ب - {sym}\n{SEP}\n”
f”النقاط: {score}/80 ({pct*100:.0f}%)\n”
f”التقييم: {g}\n{v}\n”
f”حجم الصفقة: {sz}{price_txt}”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“حفظ في Scanner”, callback_data=f”save_pb*{sym}*{score}”)],
[InlineKeyboardButton(“بناء الصفقة تلقائيا”, callback_data=f”auto_trade*{sym}”)],
]))

async def save_pb_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
parts = update.callback_query.data.split(”_”)
sym, score = parts[2], int(parts[3])
g, _ = grade(score, “b”)
data = load_data()
user = get_user(data, update.effective_user.id)
idx = next((i for i, s in enumerate(user[“stocks”]) if s[“sym”] == sym), None)
if idx is not None:
user[“stocks”][idx][“score”] = score
user[“stocks”][idx][“grade”] = g
else:
user[“stocks”].append({“sym”: sym, “plan”: “b”, “score”: score, “grade”: g, “fav”: False, “notes”: “”})
save_data(data)
await update.callback_query.message.reply_text(f”تم حفظ {sym} - {g}”, reply_markup=MAIN_KB)
return ConversationHandler.END

# — AUTO TRADE BUILD ———————————————————

async def auto_trade_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
sym = update.callback_query.data.replace(“auto_trade_”, “”)
await update.callback_query.message.reply_text(f”جاري جلب بيانات {sym} لبناء الصفقة…”)

```
q, atr, ma50 = await asyncio.gather(
    fetch_quote(sym),
    fetch_atr(sym),
    fetch_sma(sym, 50),
)

if not q:
    await update.callback_query.message.reply_text("تعذر جلب البيانات", reply_markup=MAIN_KB)
    return

price = q["price"]
atr_v = atr or price * 0.02
sl    = price - (atr_v * 1.5)
tgt   = price * 1.03
risk  = price - sl
reward= tgt - price
ratio = reward / risk if risk > 0 else 0
size  = int(10000 * 0.10 / risk) if risk > 0 else 0

t1 = price * 1.02
t2 = price * 1.03
t3 = price * 1.05

await update.callback_query.message.reply_text(
    f"خطة الصفقة التلقائية - {sym}\n{SEP}\n"
    f"السعر الحالي: ${price:.2f}\n"
    f"ATR: ${atr_v:.2f}\n\n"
    f"دخول مقترح: ${price:.2f}\n"
    f"Stop Loss: ${sl:.2f} (-{(risk/price*100):.1f}%)\n"
    f"هدف: ${tgt:.2f} (+3%)\n"
    f"R/R: {ratio:.2f}:1 {'ممتاز' if ratio>=2 else 'مقبول' if ratio>=1.5 else 'ضعيف'}\n\n"
    f"الحجم 10%: {size} سهم\n\n"
    f"{SEP}\n"
    f"الخروج التدريجي\n"
    f"الهدف 1: ${t1:.2f} (+2%) - اخرج 50%\n"
    f"الهدف 2: ${t2:.2f} (+3%) - اخرج 40%\n"
    f"الهدف 3: ${t3:.2f} (+5%) - ابق 10%\n\n"
    f"Trailing Stop\n"
    f"عند ${price*1.015:.2f} (+1.5%) - SL الى الدخول\n"
    f"عند ${price*1.02:.2f} (+2%) - SL الى +0.75%",
    reply_markup=MAIN_KB)
```

# — TRADE BUILDER MANUAL —————————————————–

async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or (update.callback_query.message if update.callback_query else None)
if update.callback_query: await update.callback_query.answer()
await msg.reply_text(“بناء الصفقة\n\nادخل رمز السهم\nمثال: AAPL”)
return TRADE_SYM

async def trade_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
sym = update.message.text.strip().upper()
ctx.user_data[“t_sym”] = sym
await update.message.reply_text(f”جاري جلب سعر {sym}…”)
q = await fetch_quote(sym)
if q:
ctx.user_data[“t_auto_price”] = q[“price”]
await update.message.reply_text(
f”{sym} - ${q[‘price’]:.2f}\n\nاختر الخطة”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“خطة أ”, callback_data=“tplan_a”),
InlineKeyboardButton(“خطة ب”, callback_data=“tplan_b”)],
]))
else:
await update.message.reply_text(
f”{sym}\n\nاختر الخطة”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“خطة أ”, callback_data=“tplan_a”),
InlineKeyboardButton(“خطة ب”, callback_data=“tplan_b”)],
]))
return TRADE_PLAN

async def trade_plan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
ctx.user_data[“t_plan”] = “a” if “tplan_a” in update.callback_query.data else “b”
price = ctx.user_data.get(“t_auto_price”)
if price:
await update.callback_query.message.reply_text(
f”السعر الحالي: ${price:.2f}\n\nادخل سعر الدخول\nاو اضغط استخدام السعر الحالي”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(f”استخدام ${price:.2f}”, callback_data=f”use_price_{price}”)],
]))
else:
await update.callback_query.message.reply_text(“ادخل سعر الدخول\nمثال: 145.50”)
return TRADE_ENTRY

async def use_price_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
price = float(update.callback_query.data.replace(“use_price_”, “”))
ctx.user_data[“t_entry”] = price
await update.callback_query.message.reply_text(
f”سعر الدخول: ${price:.2f}\n\nادخل Stop Loss\nمثال: {price*0.97:.2f}”)
return TRADE_STOP

async def trade_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
ctx.user_data[“t_entry”] = float(update.message.text.replace(”,”, “.”))
entry = ctx.user_data[“t_entry”]
await update.message.reply_text(
f”سعر الدخول: ${entry:.2f}\n\nادخل Stop Loss\nمثال: {entry*0.97:.2f}”)
return TRADE_STOP
except:
await update.message.reply_text(“ادخل رقما صحيحا”)
return TRADE_ENTRY

async def trade_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
sl = float(update.message.text.replace(”,”, “.”))
entry = ctx.user_data.get(“t_entry”, 0)
if sl >= entry:
await update.message.reply_text(“Stop Loss يجب ان يكون اقل من سعر الدخول”)
return TRADE_STOP
ctx.user_data[“t_stop”] = sl
await update.message.reply_text(“ادخل راس المال\nمثال: 10000”)
return TRADE_CAP
except:
await update.message.reply_text(“ادخل رقما”)
return TRADE_STOP

async def trade_cap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
ctx.user_data[“t_cap”] = float(update.message.text.replace(”,”, “.”).replace(”$”, “”))
await update.message.reply_text(“ادخل هدف الربح %\nمثال: 3”)
return TRADE_TGT
except:
await update.message.reply_text(“ادخل رقما”)
return TRADE_CAP

async def trade_tgt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
ctx.user_data[“t_tgt”] = float(update.message.text.replace(”,”, “.”).replace(”%”, “”))
await _show_trade(update.message, ctx)
return ConversationHandler.END
except:
await update.message.reply_text(“ادخل رقما”)
return TRADE_TGT

async def _show_trade(msg, ctx):
sym   = ctx.user_data.get(“t_sym”, “”)
entry = ctx.user_data.get(“t_entry”, 0)
sl    = ctx.user_data.get(“t_stop”, 0)
cap   = ctx.user_data.get(“t_cap”, 10000)
tgt   = ctx.user_data.get(“t_tgt”, 3)
plan  = ctx.user_data.get(“t_plan”, “a”)
target = entry * (1 + tgt / 100)
risk   = entry - sl
reward = target - entry
ratio  = reward / risk if risk > 0 else 0
size   = int(cap * 0.10 / risk) if risk > 0 else 0
t1 = entry * 1.02
t2 = entry * 1.03
t3 = entry * 1.05
await msg.reply_text(
f”خطة الصفقة - {sym}\n{SEP}\n”
f”خطة {‘أ’ if plan==‘a’ else ‘ب’}\n”
f”دخول: ${entry:.2f}\n”
f”هدف: ${target:.2f} (+{tgt}%)\n”
f”Stop: ${sl:.2f} (-{risk/entry*100:.1f}%)\n”
f”R/R: {ratio:.2f}:1 {‘ممتاز’ if ratio>=2 else ‘اقل من 2:1’}\n\n”
f”الحجم 10%: {size} سهم = ${size*entry:,.0f}\n”
f”ربح: +${size*reward:.0f} - خسارة: -${size*risk:.0f}\n\n”
f”{SEP}\n”
f”خطة الخروج\n”
f”الهدف 1: ${t1:.2f} (+2%) - اخرج 50%\n”
f”الهدف 2: ${t2:.2f} (+3%) - اخرج 40%\n”
f”الهدف 3: ${t3:.2f} (+5%) - ابق 10%\n\n”
f”Trailing Stop\n”
f”عند ${entry*1.015:.2f} (+1.5%) - SL الى الدخول\n”
f”عند ${entry*1.02:.2f} (+2%) - SL الى +0.75%\n”
f”عند ${entry*1.025:.2f} (+2.5%) - SL الى +1.5%”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“سجل هذه الصفقة”, callback_data=“journal_from_trade”)],
]))

# — ALERTS —————————————————————––

async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
data = load_data()
user = get_user(data, update.effective_user.id)
alerts = user.get(“alerts”, [])
msg = update.message or update.callback_query.message
if update.callback_query: await update.callback_query.answer()

```
lines = [f"تنبيهات الاسعار\n{SEP}"]
if alerts:
    for a in alerts:
        lines.append(f"{a['sym']} عند ${a['price']:.2f} - {'فوق' if a['above'] else 'تحت'}")
else:
    lines.append("لا يوجد تنبيهات")

await msg.reply_text("\n".join(lines),
    reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("اضافة تنبيه", callback_data="add_alert")],
        [InlineKeyboardButton("حذف الكل", callback_data="clear_alerts")],
    ]))
```

async def add_alert_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
await update.callback_query.message.reply_text(“ادخل رمز السهم للتنبيه\nمثال: AAPL”)
return ALERT_SYM

async def alert_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
ctx.user_data[“alert_sym”] = update.message.text.strip().upper()
q = await fetch_quote(ctx.user_data[“alert_sym”])
price_hint = f”\nالسعر الحالي: ${q[‘price’]:.2f}” if q else “”
await update.message.reply_text(f”ادخل السعر المستهدف للتنبيه{price_hint}”)
return ALERT_PRICE

async def alert_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
price = float(update.message.text.replace(”,”, “.”))
sym   = ctx.user_data.get(“alert_sym”, “”)
q     = await fetch_quote(sym)
above = price > (q[“price”] if q else price)
data  = load_data()
user  = get_user(data, update.effective_user.id)
user.setdefault(“alerts”, []).append({
“sym”: sym, “price”: price, “above”: above,
“uid”: update.effective_user.id
})
save_data(data)
await update.message.reply_text(
f”تم اضافة التنبيه\n{sym} عند ${price:.2f} - {‘فوق’ if above else ‘تحت’} السعر الحالي”,
reply_markup=MAIN_KB)
return ConversationHandler.END
except:
await update.message.reply_text(“ادخل رقما”)
return ALERT_PRICE

async def clear_alerts_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
data = load_data()
user = get_user(data, update.effective_user.id)
user[“alerts”] = []
save_data(data)
await update.callback_query.message.reply_text(“تم حذف كل التنبيهات”, reply_markup=MAIN_KB)

# — ALERT CHECKER ————————————————————

async def check_alerts(app):
“”“يفحص التنبيهات كل 5 دقائق”””
data = load_data()
triggered = []
for uid, user in data.items():
for alert in user.get(“alerts”, []):
q = await fetch_quote(alert[“sym”])
if not q: continue
price = q[“price”]
hit = (alert[“above”] and price >= alert[“price”]) or   
(not alert[“above”] and price <= alert[“price”])
if hit:
triggered.append((uid, alert, price))

```
for uid, alert, current_price in triggered:
    try:
        await app.bot.send_message(
            chat_id=int(uid),
            text=f"تنبيه السعر\n{SEP}\n"
                 f"{alert['sym']} وصل ${current_price:.2f}\n"
                 f"هدفك كان ${alert['price']:.2f}\n"
                 f"{'السعر فوق هدفك' if alert['above'] else 'السعر تحت هدفك'}")
        data[uid]["alerts"] = [a for a in data[uid]["alerts"] if a != alert]
    except:
        pass

if triggered:
    save_data(data)
```

# — MORNING REPORT ———————————————————–

async def send_morning_report(app):
“”“تقرير صباحي يومي الساعة 9:00 AM ET”””
spy_q, vix_q, spy_ma50, _ = await get_market_data()
if not spy_q: return

```
spy  = spy_q["price"]
vix  = vix_q["price"] if vix_q else 0
ma50 = spy_ma50 or 0
spy_ok = spy > ma50
vix_ok = vix < 25

if spy_ok and vix_ok:
    verdict = "بيئة جيدة - يمكنك التداول اليوم"
else:
    verdict = "تجنب التداول اليوم - شروط مكسورة"

msg = (f"تقرير الصباح - WarRoom Pro\n{SEP}\n"
       f"SPY: ${spy:.2f} {'فوق MA50' if spy_ok else 'تحت MA50'}\n"
       f"VIX: {vix:.2f} {'ممتاز' if vix<20 else 'مقبول' if vix<25 else 'خطر'}\n\n"
       f"{verdict}\n\n"
       f"نافذة الدخول الاولى: 9:45 AM ET")

data = load_data()
for uid in data.keys():
    try:
        await app.bot.send_message(chat_id=int(uid), text=msg)
    except:
        pass
```

# — JOURNAL ——————————————————————

async def cmd_journal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or (update.callback_query.message if update.callback_query else None)
if update.callback_query: await update.callback_query.answer()
await msg.reply_text(“تسجيل صفقة\n\nادخل رمز السهم\nمثال: AAPL”)
return JOURNAL_SYM

async def journal_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
ctx.user_data[“j_sym”] = update.message.text.strip().upper()
await update.message.reply_text(“ادخل سعر الدخول”)
return JOURNAL_ENTRY

async def journal_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
ctx.user_data[“j_entry”] = float(update.message.text.replace(”,”, “.”))
await update.message.reply_text(“ادخل سعر الخروج\nادخل 0 اذا الصفقة مفتوحة”)
return JOURNAL_EXIT
except:
await update.message.reply_text(“ادخل رقما”)
return JOURNAL_ENTRY

async def journal_exit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
val = float(update.message.text.replace(”,”, “.”))
ctx.user_data[“j_exit”] = val if val > 0 else None
await update.message.reply_text(“ادخل عدد الاسهم”)
return JOURNAL_QTY
except:
await update.message.reply_text(“ادخل رقما”)
return JOURNAL_EXIT

async def journal_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
try:
ctx.user_data[“j_qty”] = float(update.message.text.replace(”,”, “.”))
await update.message.reply_text(“النتيجة”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“ربح”, callback_data=“jres_win”),
InlineKeyboardButton(“خسارة”, callback_data=“jres_loss”)],
[InlineKeyboardButton(“مفتوحة”, callback_data=“jres_open”)],
]))
return JOURNAL_RES
except:
await update.message.reply_text(“ادخل رقما”)
return JOURNAL_QTY

async def journal_res_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
ctx.user_data[“j_res”] = update.callback_query.data.replace(“jres_”, “”)
await update.callback_query.message.reply_text(“الحالة النفسية”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“مثالي”, callback_data=“jm_optimal”)],
[InlineKeyboardButton(“جيد”,   callback_data=“jm_good”)],
[InlineKeyboardButton(“ضعيف”,  callback_data=“jm_poor”)],
]))
return JOURNAL_MENTAL

async def journal_mental_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
ctx.user_data[“j_mental”] = update.callback_query.data.replace(“jm_”, “”)
await update.callback_query.message.reply_text(“هل اتبعت النظام؟”,
reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton(“نعم”, callback_data=“jf_yes”)],
[InlineKeyboardButton(“جزئيا”, callback_data=“jf_partial”)],
[InlineKeyboardButton(“لا”, callback_data=“jf_no”)],
]))
return JOURNAL_FOLLOWED

async def journal_followed_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
await update.callback_query.answer()
ctx.user_data[“j_followed”] = update.callback_query.data.replace(“jf_”, “”)
await update.callback_query.message.reply_text(
“الدرس المستفاد\nاكتب ما تعلمته او ارسل - للتخطي”)
return JOURNAL_LESSON

async def journal_lesson(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
lesson = update.message.text.strip()
if lesson == “-”: lesson = “”
sym      = ctx.user_data.get(“j_sym”, “”)
entry    = ctx.user_data.get(“j_entry”, 0)
exit_p   = ctx.user_data.get(“j_exit”)
qty      = ctx.user_data.get(“j_qty”, 1)
res      = ctx.user_data.get(“j_res”, “open”)
mental   = ctx.user_data.get(“j_mental”, “good”)
followed = ctx.user_data.get(“j_followed”, “yes”)
pnl = (exit_p - entry) * qty if exit_p else None
pct = ((exit_p - entry) / entry * 100) if exit_p else None
data = load_data()
user = get_user(data, update.effective_user.id)
user[“trades”].insert(0, {
“id”: int(datetime.now().timestamp()),
“sym”: sym, “date”: date.today().isoformat(),
“entry”: entry, “exit”: exit_p, “qty”: qty,
“res”: res, “pnl”: pnl, “pct”: pct,
“plan”: ctx.user_data.get(“t_plan”, “a”),
“mental”: mental, “followed”: followed, “lesson”: lesson,
})
save_data(data)
ri = {“win”: “ربح”, “loss”: “خسارة”, “open”: “مفتوحة”}
mt = {“optimal”: “مثالي”, “good”: “جيد”, “poor”: “ضعيف”}.get(mental, “”)
ft = {“yes”: “نعم”, “partial”: “جزئي”, “no”: “لا”}.get(followed, “”)
lines = [f”تم التسجيل - {sym}”, SEP,
f”دخول: {entry:.2f} - خروج: {exit_p:.2f if exit_p else 0}”,
f”النتيجة: {ri.get(res,’’)}”]
if pnl is not None:
lines.append(f”P&L: {’+’ if pnl>=0 else ‘’}{pnl:.2f} ({’+’ if pct>=0 else ‘’}{pct:.2f}%)”)
lines += [f”النفسية: {mt} - النظام: {ft}”]
if lesson: lines.append(f”الدرس: {lesson}”)
await update.message.reply_text(”\n”.join(lines), reply_markup=MAIN_KB)
return ConversationHandler.END

# — PERFORMANCE –––––––––––––––––––––––––––––––

async def cmd_perf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
data = load_data()
user = get_user(data, update.effective_user.id)
trades = user.get(“trades”, [])
msg = update.message or update.callback_query.message
if update.callback_query: await update.callback_query.answer()
if len(trades) < 2:
await msg.reply_text(“سجل صفقتين على الاقل لعرض الاحصاءات”, reply_markup=MAIN_KB)
return
wins   = [t for t in trades if t.get(“res”) == “win”]
losses = [t for t in trades if t.get(“res”) == “loss”]
closed = [t for t in trades if t.get(“res”) != “open”]
total_pnl = sum(t.get(“pnl”) or 0 for t in trades)
avg_win  = sum(abs(t.get(“pct”) or 0) for t in wins)   / len(wins)   if wins   else 0
avg_loss = sum(abs(t.get(“pct”) or 0) for t in losses) / len(losses) if losses else 1
wr = len(wins) / len(closed) * 100 if closed else 0
pf = avg_win / avg_loss if avg_loss > 0 else 0
pa = [t for t in trades if t.get(“plan”) == “a”]
pb = [t for t in trades if t.get(“plan”) == “b”]
def plan_wr(lst):
cl = [t for t in lst if t.get(“res”) != “open”]
w  = [t for t in lst if t.get(“res”) == “win”]
return len(w)/len(cl)*100 if cl else 0
with_pct = [t for t in trades if t.get(“pct”) is not None]
best  = max(with_pct, key=lambda t: t[“pct”]) if with_pct else None
worst = min(with_pct, key=lambda t: t[“pct”]) if with_pct else None
lines = [
f”تحليل الاداء\n{SEP}”,
f”اجمالي: {len(trades)} صفقة”,
f”نسبة الفوز: {wr:.0f}% ({len(wins)}W / {len(losses)}L)”,
f”Profit Factor: {pf:.2f}x”,
f”اجمالي P&L: {’+’ if total_pnl>=0 else ‘’}{total_pnl:.2f}”,
f”متوسط الربح: +{avg_win:.2f}% | الخسارة: -{avg_loss:.2f}%”,
SEP,
f”خطة أ: {len(pa)} صفقة - فوز {plan_wr(pa):.0f}%”,
f”خطة ب: {len(pb)} صفقة - فوز {plan_wr(pb):.0f}%”,
]
if best and worst:
lines += [SEP,
f”افضل: {best[‘sym’]} +{best[‘pct’]:.2f}%”,
f”اسوا: {worst[‘sym’]} {worst[‘pct’]:.2f}%”]
lines += [SEP,
“نسبة الفوز ممتازة” if wr>=65 else “قابلة للتحسين” if wr>=50 else “راجع شروط الدخول”,
“Profit Factor ممتاز” if pf>=2 else “مقبول” if pf>=1.3 else “راجع Stop Loss”]
await msg.reply_text(”\n”.join(lines), reply_markup=MAIN_KB)

# — RULES ––––––––––––––––––––––––––––––––––

async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message or update.callback_query.message
if update.callback_query: await update.callback_query.answer()
await msg.reply_text(
f”القواعد الذهبية\n{SEP}\n”
“ادارة راس المال\n”
“- حجم الصفقة 10% كحد اقصى\n”
“- حد الخسارة اليومي -3%\n”
“- حد الخسارة الشهري -10%\n”
“- اقصى صفقتين يوميا\n\n”
“القواعد النفسية\n”
“- 3 خسائر متتالية - اغلق وعد غدا\n”
“- بعد خسارة - انتظر ساعتين\n”
“- Revenge Trading = نهاية الحساب\n\n”
“التوقيت\n”
“- الدخول 9:45-10:30 او 2:00-3:30 ET\n”
“- خروج الزامي قبل 3:45 PM\n\n”
“قواعد الدخول\n”
“- لا دخول بدون Stop Loss\n”
“- R/R 2:1 على الاقل\n”
“- SPY فوق MA50 - لا يكسر\n”
“- VIX تحت 25 للخطة أ - تحت 20 للخطة ب”,
reply_markup=MAIN_KB)

async def cmd_window(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
t = now_et()
await update.message.reply_text(
f”النافذة الحالية\n\n”
f”الوقت ET: {t.strftime(’%H:%M:%S’)}\n”
f”{‘السوق مفتوح’ if market_open() else ‘السوق مغلق’}\n”
f”{entry_window()}”,
reply_markup=MAIN_KB)

# — ROUTERS ——————————————————————

async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
routes = {
“المشهد الكلي”:    cmd_macro,
“Scanner”:         cmd_scanner,
“تقييم خطة أ”:    start_plan_a,
“تقييم خطة ب”:    start_plan_b,
“بناء الصفقة”:    cmd_trade,
“سجل صفقة”:       cmd_journal,
“الاداء”:          cmd_perf,
“القواعد”:         cmd_rules,
“النافذة الحالية”: cmd_window,
“تنبيهات”:         cmd_alerts,
}
handler = routes.get(update.message.text)
if handler:
return await handler(update, ctx)

async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
d = update.callback_query.data
if d == “macro_refresh”:   return await macro_refresh_cb(update, ctx)
elif d == “windows”:       await windows_cb(update, ctx)
elif d == “stock_add”:     return await stock_add_cb(update, ctx)
elif d == “scanner_refresh”: return await scanner_refresh_cb(update, ctx)
elif d == “journal_from_trade”: return await cmd_journal(update, ctx)
elif d == “add_alert”:     return await add_alert_cb(update, ctx)
elif d == “clear_alerts”:  await clear_alerts_cb(update, ctx)
elif d.startswith(“auto_trade_”): await auto_trade_cb(update, ctx)
elif d.startswith(“use_price_”): return await use_price_cb(update, ctx)

# — MAIN ———————————————————————

def main():
if not BOT_TOKEN:
print(“BOT_TOKEN غير موجود”)
return
if not AV_KEY:
print(“AV_KEY غير موجود”)
return

```
app = Application.builder().token(BOT_TOKEN).build()

# Job Queue - تقرير صباحي 9:00 AM ET كل يوم عمل
job_queue = app.job_queue
if job_queue:
    # فحص التنبيهات كل 5 دقائق
    job_queue.run_repeating(
        lambda ctx: asyncio.create_task(check_alerts(app)),
        interval=300, first=60)
    # تقرير صباحي 9:00 AM ET = 13:00 UTC
    from datetime import time as dtime
    job_queue.run_daily(
        lambda ctx: asyncio.create_task(send_morning_report(app)),
        time=dtime(13, 0, 0, tzinfo=timezone.utc))

stock_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(stock_add_cb, pattern="^stock_add$"),
        CommandHandler("add", stock_add_cb),
    ],
    states={
        STOCK_SYM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, stock_sym)],
        STOCK_PLAN: [CallbackQueryHandler(stock_plan_cb, pattern="^plan_[ab]$")],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

pa_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^تقييم خطة أ$"), start_plan_a),
        CommandHandler("plana", start_plan_a),
    ],
    states={
        SCORE_PA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, pa_sym_handler),
            CallbackQueryHandler(pa_answer_cb,  pattern="^pa_"),
            CallbackQueryHandler(save_pa_cb,    pattern="^save_pa_"),
        ],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

pb_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^تقييم خطة ب$"), start_plan_b),
        CommandHandler("planb", start_plan_b),
    ],
    states={
        SCORE_PB: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, pb_sym_handler),
            CallbackQueryHandler(pb_answer_cb,  pattern="^pb_"),
            CallbackQueryHandler(save_pb_cb,    pattern="^save_pb_"),
        ],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

trade_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^بناء الصفقة$"), cmd_trade),
        CommandHandler("trade", cmd_trade),
    ],
    states={
        TRADE_SYM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_sym)],
        TRADE_PLAN:  [CallbackQueryHandler(trade_plan_cb, pattern="^tplan_")],
        TRADE_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, trade_entry),
            CallbackQueryHandler(use_price_cb, pattern="^use_price_"),
        ],
        TRADE_STOP:  [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_stop)],
        TRADE_CAP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_cap)],
        TRADE_TGT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_tgt)],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

journal_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^سجل صفقة$"), cmd_journal),
        CommandHandler("journal", cmd_journal),
        CallbackQueryHandler(cmd_journal, pattern="^journal_from_trade$"),
    ],
    states={
        JOURNAL_SYM:      [MessageHandler(filters.TEXT & ~filters.COMMAND, journal_sym)],
        JOURNAL_ENTRY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, journal_entry)],
        JOURNAL_EXIT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, journal_exit)],
        JOURNAL_QTY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, journal_qty)],
        JOURNAL_RES:      [CallbackQueryHandler(journal_res_cb,      pattern="^jres_")],
        JOURNAL_MENTAL:   [CallbackQueryHandler(journal_mental_cb,   pattern="^jm_")],
        JOURNAL_FOLLOWED: [CallbackQueryHandler(journal_followed_cb, pattern="^jf_")],
        JOURNAL_LESSON:   [MessageHandler(filters.TEXT & ~filters.COMMAND, journal_lesson)],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

alert_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^تنبيهات$"), cmd_alerts),
        CallbackQueryHandler(add_alert_cb, pattern="^add_alert$"),
    ],
    states={
        ALERT_SYM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, alert_sym)],
        ALERT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, alert_price)],
    },
    fallbacks=[CommandHandler("start", cmd_start)],
)

app.add_handler(CommandHandler("start",   cmd_start))
app.add_handler(CommandHandler("macro",   cmd_macro))
app.add_handler(CommandHandler("scanner", cmd_scanner))
app.add_handler(CommandHandler("perf",    cmd_perf))
app.add_handler(CommandHandler("rules",   cmd_rules))
app.add_handler(CommandHandler("window",  cmd_window))
app.add_handler(CommandHandler("alerts",  cmd_alerts))
app.add_handler(stock_conv)
app.add_handler(pa_conv)
app.add_handler(pb_conv)
app.add_handler(trade_conv)
app.add_handler(journal_conv)
app.add_handler(alert_conv)
app.add_handler(CallbackQueryHandler(cb_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

print("@TurkiAlotaibi_bot Auto - Running...")
app.run_polling(drop_pending_updates=True)
```

if **name** == “**main**”:
main()
