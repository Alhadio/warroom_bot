#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE  = "warroom_data.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

(
    MACRO_VIX, MACRO_SPY, MACRO_BREADTH, MACRO_FED, MACRO_EVENTS,
    STOCK_SYM, STOCK_PLAN,
    SCORE_PA, SCORE_PB,
    TRADE_SYM, TRADE_PLAN, TRADE_ENTRY, TRADE_STOP, TRADE_CAP, TRADE_TGT,
    JOURNAL_SYM, JOURNAL_ENTRY, JOURNAL_EXIT, JOURNAL_QTY, JOURNAL_RES,
    JOURNAL_MENTAL, JOURNAL_FOLLOWED, JOURNAL_LESSON,
) = range(23)

SEP = "=" * 28

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data:
        data[uid] = {"stocks": [], "trades": []}
    return data[uid]

def grade(score, plan="a"):
    mx = 78 if plan == "a" else 80
    p = score / mx
    if p >= 0.70: return "A+", p
    if p >= 0.55: return "A",  p
    if p >= 0.40: return "B",  p
    if p >= 0.25: return "C",  p
    return "D", p

def now_et():
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=-4)))

def market_open():
    t = now_et()
    if t.weekday() >= 5: return False
    h = t.hour + t.minute / 60
    return 9.5 <= h <= 16.0

def entry_window():
    t = now_et()
    h = t.hour + t.minute / 60
    if t.weekday() >= 5:      return "السوق مغلق - عطلة"
    if h < 9.5:               return "السوق لم يفتح بعد"
    if 9.5  <= h < 9.75:      return "فوضى الافتتاح - تجنب"
    if 9.75 <= h < 10.5:      return "نافذة الصباح 9:45-10:30 - ممتاز"
    if 10.5 <= h < 14.0:      return "منتصف اليوم - تجنب الدخول"
    if 14.0 <= h < 15.5:      return "نافذة الظهر 2:00-3:30 - ممتاز"
    if 15.5 <= h < 15.75:     return "خروج تدريجي 3:30-3:45"
    if 15.75 <= h < 16.0:     return "اخرج الان 3:45"
    return "السوق اغلق"

MAIN_KB = ReplyKeyboardMarkup([
    ["المشهد الكلي",   "Scanner"],
    ["تقييم خطة أ",    "تقييم خطة ب"],
    ["بناء الصفقة",    "سجل صفقة"],
    ["الاداء",         "القواعد"],
    ["النافذة الحالية","مساعدة"],
], resize_keyboard=True)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "متداول"
    await update.message.reply_text(
        f"WarRoom Pro - @TurkiAlotaibi_bot\n\n"
        f"اهلا {name}\n\n"
        "انا مساعدك في التداول اليومي على السوق الامريكي\n\n"
        "المشهد الكلي - تقييم بيئة السوق\n"
        "تقييم الاسهم بالخطة أ وب\n"
        "بناء الصفقة مع Stop Loss والاهداف\n"
        "تسجيل الصفقات وتتبع الاداء\n\n"
        "اضغط على اي زر للبدء",
        reply_markup=MAIN_KB)

async def cmd_window(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = now_et()
    status = "السوق مفتوح" if market_open() else "السوق مغلق"
    await update.message.reply_text(
        f"النافذة الحالية\n{SEP}\n"
        f"الوقت ET: {t.strftime('%H:%M:%S')}\n"
        f"{status}\n"
        f"{entry_window()}")

async def cmd_macro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = now_et()
    status = "السوق مفتوح" if market_open() else "السوق مغلق"
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("بدء تقييم السوق", callback_data="macro_start")],
        [InlineKeyboardButton("نوافذ التوقيت", callback_data="windows")],
    ])
    await msg.reply_text(
        f"المشهد الكلي\n{SEP}\n"
        f"الوقت ET: {t.strftime('%H:%M:%S')}\n"
        f"{status}\n"
        f"{entry_window()}\n\n"
        "اضغط لبدء التقييم",
        reply_markup=kb)

async def macro_start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "تقييم السوق\n\nادخل قيمة VIX الحالية\nمثال: 18.5")
    return MACRO_VIX

async def macro_vix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        vix = float(update.message.text.replace(",", "."))
        ctx.user_data["m_vix"] = vix
        if vix < 20:   s = "ممتاز - بيئة هادئة"
        elif vix < 25: s = "مقبول - بعض الحذر"
        else:          s = "خطر - اسواق متقلبة"
        await update.message.reply_text(
            f"VIX = {vix} - {s}\n\nادخل سعر SPY الحالي\nمثال: 565.20")
        return MACRO_SPY
    except:
        await update.message.reply_text("ادخل رقما صحيحا")
        return MACRO_VIX

async def macro_spy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["m_spy"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text(
            "ادخل MA50 لـ SPY من TradingView\nمثال: 548.00")
        return MACRO_BREADTH
    except:
        await update.message.reply_text("ادخل رقما صحيحا")
        return MACRO_SPY

async def macro_breadth(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(",", "."))
        ctx.user_data["m_ma50"] = val
        spy = ctx.user_data.get("m_spy", 0)
        s = "فوق MA50 - جيد" if spy > val else "تحت MA50 - خطر"
        await update.message.reply_text(
            f"SPY {spy:.2f} vs MA50 {val:.2f} - {s}\n\n"
            "ادخل Market Breadth %\nمثال: 65")
        return MACRO_FED
    except:
        await update.message.reply_text("ادخل رقما صحيحا")
        return MACRO_BREADTH

async def macro_fed(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["m_breadth"] = float(update.message.text.replace(",", ".").replace("%", ""))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("لا يوجد Fed/NFP", callback_data="fed_no")],
            [InlineKeyboardButton("يوجد Fed او NFP", callback_data="fed_yes")],
        ])
        await update.message.reply_text(
            "هل يوجد Fed او NFP خلال 48 ساعة؟",
            reply_markup=kb)
        return MACRO_EVENTS
    except:
        await update.message.reply_text("ادخل رقما")
        return MACRO_FED

async def macro_events_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    fed = update.callback_query.data == "fed_yes"
    vix = ctx.user_data.get("m_vix", 0)
    spy = ctx.user_data.get("m_spy", 0)
    ma50 = ctx.user_data.get("m_ma50", 0)
    breadth = ctx.user_data.get("m_breadth", 0)
    spy_ok = spy > ma50
    score = 0
    if spy_ok:    score += 1
    if vix < 20:  score += 2
    elif vix < 25: score += 1
    if breadth > 65: score += 2
    elif breadth > 55: score += 1
    if not fed:   score += 1
    blocked = not spy_ok or vix >= 25 or fed
    if blocked:   v = "لا تداول اليوم - شرط الزامي مكسور"
    elif score >= 5: v = "بيئة ممتازة - تداول بثقة"
    elif score >= 3: v = "بيئة مقبولة - قلل الحجم"
    else:            v = "بيئة ضعيفة - تجنب"
    await update.callback_query.message.reply_text(
        f"نتيجة تقييم السوق\n{SEP}\n"
        f"{v}\n\n"
        f"SPY {spy:.2f} vs MA50 {ma50:.2f} - {'فوق' if spy_ok else 'تحت'}\n"
        f"VIX {vix} - {'ممتاز' if vix<20 else 'مقبول' if vix<25 else 'خطر'}\n"
        f"Breadth {breadth}% - {'قوي' if breadth>65 else 'مقبول' if breadth>55 else 'ضعيف'}\n"
        f"Fed/NFP - {'تجنب' if fed else 'لا يوجد'}\n\n"
        f"النافذة: {entry_window()}",
        reply_markup=MAIN_KB)
    return ConversationHandler.END

async def windows_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        f"نوافذ التداول اليومية\n{SEP}\n"
        "9:30-9:45  فوضى الافتتاح - تجنب\n"
        "9:45-10:30 افضل نافذة صباحية\n"
        "10:30-2:00 منتصف اليوم - لا دخول\n"
        "2:00-3:30  نافذة الظهر - قوية\n"
        "3:30-3:45  خروج تدريجي\n"
        "3:45-4:00  اخرج الان\n\n"
        f"الان ET: {now_et().strftime('%H:%M')}\n"
        f"{entry_window()}")

async def cmd_scanner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_user.id)
    stocks = user.get("stocks", [])
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    if not stocks:
        await msg.reply_text(
            "Scanner - قائمة المراقبة\n\nلا يوجد اسهم بعد\nاضف سهما بالضغط ادناه",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("اضافة سهم", callback_data="stock_add")]
            ]))
        return
    stocks_sorted = sorted(stocks, key=lambda x: x.get("score", 0), reverse=True)
    lines = [f"Scanner - {len(stocks)} سهم", SEP]
    for s in stocks_sorted:
        g, _ = grade(s.get("score", 0), s.get("plan", "a"))
        icon = "A" if s.get("plan") == "a" else "B"
        fav = "* " if s.get("fav") else ""
        lines.append(f"{fav}{icon} {s['sym']} - {g} ({s.get('score',0)}/{'78' if s.get('plan')=='a' else '80'})")
    await msg.reply_text("\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("اضافة سهم", callback_data="stock_add")],
        ]))

async def stock_add_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "ادخل رمز السهم\nمثال: AAPL")
    return STOCK_SYM

async def stock_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sym = update.message.text.strip().upper()
    if not sym.isalpha() or len(sym) > 6:
        await update.message.reply_text("رمز غير صحيح - ادخل مثل AAPL")
        return STOCK_SYM
    ctx.user_data["new_sym"] = sym
    await update.message.reply_text(
        f"{sym} - اختر الخطة",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("خطة أ - صياد القاع", callback_data="plan_a")],
            [InlineKeyboardButton("خطة ب - راكب الموجة", callback_data="plan_b")],
        ]))
    return STOCK_PLAN

async def stock_plan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    plan = "a" if "plan_a" in update.callback_query.data else "b"
    sym = ctx.user_data.get("new_sym", "")
    data = load_data()
    user = get_user(data, update.effective_user.id)
    if any(s["sym"] == sym for s in user["stocks"]):
        await update.callback_query.message.reply_text(f"{sym} موجود بالفعل", reply_markup=MAIN_KB)
        return ConversationHandler.END
    user["stocks"].append({"sym": sym, "plan": plan, "score": 0, "grade": "D", "fav": False, "notes": ""})
    save_data(data)
    await update.callback_query.message.reply_text(
        f"تم اضافة {sym} - خطة {'أ' if plan=='a' else 'ب'}",
        reply_markup=MAIN_KB)
    return ConversationHandler.END
PA_QUESTIONS = [
    ("S&P500 فوق MA50؟ - الزامي", 0, "m"),
    ("VIX تحت 25؟ - الزامي", 0, "m"),
    ("Market Breadth فوق 55%؟ - الزامي", 0, "m"),
    ("نسبة R/R 2:1 على الاقل؟ - الزامي", 0, "m"),
    ("MACD Histogram Divergence على 1D؟", 5, "s"),
    ("RSI Divergence - سعر ادنى RSI اعلى؟", 5, "s"),
    ("Selling Climax - حجم 3x مع Hammer؟", 4, "s"),
    ("كلاهما MACD و RSI Divergence معا؟", 12, "s"),
    ("نزول 7 ايام متتالية؟", 3, "s"),
    ("RSI عاد فوق 30؟", 3, "c"),
    ("MACD Crossover تحت الصفر؟", 3, "c"),
    ("Morning Star - 3 شموع؟", 4, "c"),
    ("Bullish Engulfing بحجم فوق المتوسط؟", 3, "c"),
    ("كسر خط اتجاه هابط؟", 3, "c"),
    ("MACD 1H يؤكد؟", 2, "c"),
    ("RSI 15 دقيقة صاعد؟", 2, "c"),
    ("دعم تاريخي 3 مرات؟", 4, "l"),
    ("Fibonacci 38.2 او 50 او 61.8؟", 3, "l"),
    ("لا Gap مفتوح تحت السعر؟", 3, "l"),
    ("تحت Lower Bollinger Band؟", 2, "l"),
    ("Round Number نفسي؟", 2, "l"),
    ("Volume Profile عند POC؟", 2, "l"),
    ("Anchored VWAP؟", 2, "l"),
    ("Earnings Beat و Guidance ايجابي؟", 4, "f"),
    ("Short Interest فوق 20؟", 4, "f"),
    ("Dark Pool او Institutional؟", 3, "f"),
    ("Options Flow - Call buying غير عادي؟", 4, "f"),
    ("Sector Rotation ايجابية؟", 2, "f"),
    ("Pre-Market ايجابي؟", 2, "f"),
    ("ATR فوق 3%؟", 3, "st"),
    ("Beta بين 1.3 و 2.5؟", 3, "st"),
    ("قريب من 52W Low؟", 2, "st"),
    ("Float 10-150M؟", 2, "st"),
    ("Relative Strength اقوى من القطاع؟", 2, "st"),
    ("سيولة فوق 50M دولار؟", 2, "st"),
]

PB_QUESTIONS = [
    ("S&P500 فوق MA20 وMA50؟ - الزامي", 0, "m"),
    ("VIX تحت 20؟ - الزامي", 0, "m"),
    ("السعر فوق MA200؟ - الزامي", 0, "m"),
    ("Higher Highs وHigher Lows 3 اشهر؟ - الزامي", 0, "m"),
    ("Perfect Alignment MA20/50/200؟", 5, "t"),
    ("MA20 اكبر MA50 اكبر MA200؟", 4, "t"),
    ("RS اقوى من SPY بـ 20%؟", 4, "t"),
    ("Stage 2؟", 3, "t"),
    ("حجم التراجع اقل 30%؟", 4, "p"),
    ("التراجع 5-15% من القمة؟", 3, "p"),
    ("لم يكسر MA50؟", 3, "p"),
    ("VCP Pattern؟", 4, "p"),
    ("MACD فوق الصفر يتصاعد؟", 4, "r"),
    ("RSI ارتد من 45-50؟", 3, "r"),
    ("حجم الارتداد فوق المتوسط 50%؟", 3, "r"),
    ("Breakout من Flag بحجم 150%؟", 5, "r"),
    ("ارتد من MA50 او MA20؟", 3, "r"),
    ("عاد فوق VWAP؟", 3, "r"),
    ("Earnings Acceleration؟", 4, "f"),
    ("Accumulation Days اكثر من Distribution؟", 3, "f"),
    ("Sector Rotation ايجابية؟", 3, "f"),
    ("Institutional buying؟", 3, "f"),
    ("قريب من 52W High؟", 3, "f"),
    ("Analyst Upgrade حديث؟", 2, "f"),
    ("Price Memory؟", 3, "st"),
    ("Beta 1.0-1.8؟", 2, "st"),
    ("ATR 2-4%؟", 2, "st"),
    ("سيولة فوق 100M دولار؟", 2, "st"),
]

CAT = {
    "m": "الزامي", "s": "اشارات انتهاء البيع",
    "c": "تاكيد الانعكاس", "l": "مستوى الدخول",
    "f": "الوقود", "t": "قوة الاتجاه",
    "p": "جودة التراجع", "r": "استئناف الصعود",
    "st": "خصائص السهم",
}

async def start_plan_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query: await update.callback_query.answer()
    ctx.user_data.update({"pa_idx": 0, "pa_score": 0, "pa_ok": True, "pa_sym": ""})
    await msg.reply_text("خطة أ - صياد القاع\n\nادخل رمز السهم\nمثال: AAPL")
    return SCORE_PA

async def pa_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["pa_sym"] = update.message.text.strip().upper()
    await _ask_pa(update.message, ctx)
    return SCORE_PA

async def _ask_pa(msg, ctx):
    idx = ctx.user_data.get("pa_idx", 0)
    if idx >= len(PA_QUESTIONS):
        await _finish_pa(msg, ctx)
        return
    q, pts, cat = PA_QUESTIONS[idx]
    sc = ctx.user_data.get("pa_score", 0)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("نعم", callback_data="pa_yes"),
         InlineKeyboardButton("لا",  callback_data="pa_no")],
        [InlineKeyboardButton("تخطى", callback_data="pa_skip"),
         InlineKeyboardButton("انهاء", callback_data="pa_done")],
    ])
    await msg.reply_text(
        f"خطة أ - {idx+1}/{len(PA_QUESTIONS)}\n"
        f"{CAT.get(cat,'')}\n\n{q}\n\n"
        f"النقاط: {sc}/78",
        reply_markup=kb)

async def pa_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data
    idx = ctx.user_data.get("pa_idx", 0)
    if action == "pa_done":
        await _finish_pa(update.callback_query.message, ctx)
        return ConversationHandler.END
    if idx < len(PA_QUESTIONS):
        q, pts, cat = PA_QUESTIONS[idx]
        if action == "pa_yes" and cat != "m":
            ctx.user_data["pa_score"] = ctx.user_data.get("pa_score", 0) + pts
        elif action == "pa_no" and cat == "m":
            ctx.user_data["pa_ok"] = False
    ctx.user_data["pa_idx"] = idx + 1
    await _ask_pa(update.callback_query.message, ctx)
    return SCORE_PA

async def _finish_pa(msg, ctx):
    score = ctx.user_data.get("pa_score", 0)
    ok = ctx.user_data.get("pa_ok", True)
    sym = ctx.user_data.get("pa_sym", "السهم")
    g, pct = grade(score, "a")
    if not ok:       v = "شروط الزامية مكسورة - لا تدخل"; sz = "صفر"
    elif pct >= 0.70: v = "A+ - اعداد استثنائي"; sz = "10%"
    elif pct >= 0.55: v = "A - اعداد قوي"; sz = "7%"
    elif pct >= 0.40: v = "B - مقبول"; sz = "4%"
    else:             v = "تجنب - نقاط غير كافية"; sz = "صفر"
    await msg.reply_text(
        f"نتيجة خطة أ - {sym}\n{SEP}\n"
        f"النقاط: {score}/78 ({pct*100:.0f}%)\n"
        f"التقييم: {g}\n{v}\n"
        f"حجم الصفقة: {sz}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("حفظ في Scanner", callback_data=f"save_pa_{sym}_{score}")],
            [InlineKeyboardButton("بناء الصفقة", callback_data="trade_build")],
        ]))

async def save_pa_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts = update.callback_query.data.split("_")
    sym, score = parts[2], int(parts[3])
    g, _ = grade(score, "a")
    data = load_data()
    user = get_user(data, update.effective_user.id)
    idx = next((i for i, s in enumerate(user["stocks"]) if s["sym"] == sym), None)
    if idx is not None:
        user["stocks"][idx]["score"] = score
        user["stocks"][idx]["grade"] = g
    else:
        user["stocks"].append({"sym": sym, "plan": "a", "score": score, "grade": g, "fav": False, "notes": ""})
    save_data(data)
    await update.callback_query.message.reply_text(f"تم حفظ {sym} - {g}", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def start_plan_b(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query: await update.callback_query.answer()
    ctx.user_data.update({"pb_idx": 0, "pb_score": 0, "pb_ok": True, "pb_sym": ""})
    await msg.reply_text("خطة ب - راكب الموجة\n\nادخل رمز السهم\nمثال: NVDA")
    return SCORE_PB

async def pb_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["pb_sym"] = update.message.text.strip().upper()
    await _ask_pb(update.message, ctx)
    return SCORE_PB

async def _ask_pb(msg, ctx):
    idx = ctx.user_data.get("pb_idx", 0)
    if idx >= len(PB_QUESTIONS):
        await _finish_pb(msg, ctx)
        return
    q, pts, cat = PB_QUESTIONS[idx]
    sc = ctx.user_data.get("pb_score", 0)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("نعم", callback_data="pb_yes"),
         InlineKeyboardButton("لا",  callback_data="pb_no")],
        [InlineKeyboardButton("تخطى", callback_data="pb_skip"),
         InlineKeyboardButton("انهاء", callback_data="pb_done")],
    ])
    await msg.reply_text(
        f"خطة ب - {idx+1}/{len(PB_QUESTIONS)}\n"
        f"{CAT.get(cat,'')}\n\n{q}\n\n"
        f"النقاط: {sc}/80",
        reply_markup=kb)

async def pb_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data
    idx = ctx.user_data.get("pb_idx", 0)
    if action == "pb_done":
        await _finish_pb(update.callback_query.message, ctx)
        return ConversationHandler.END
    if idx < len(PB_QUESTIONS):
        q, pts, cat = PB_QUESTIONS[idx]
        if action == "pb_yes" and cat != "m":
            ctx.user_data["pb_score"] = ctx.user_data.get("pb_score", 0) + pts
        elif action == "pb_no" and cat == "m":
            ctx.user_data["pb_ok"] = False
    ctx.user_data["pb_idx"] = idx + 1
    await _ask_pb(update.callback_query.message, ctx)
    return SCORE_PB

async def _finish_pb(msg, ctx):
    score = ctx.user_data.get("pb_score", 0)
    ok = ctx.user_data.get("pb_ok", True)
    sym = ctx.user_data.get("pb_sym", "السهم")
    g, pct = grade(score, "b")
    if not ok:        v = "شروط الزامية مكسورة - لا تدخل"; sz = "صفر"
    elif pct >= 0.70: v = "A+ - اعداد استثنائي"; sz = "10%"
    elif pct >= 0.55: v = "A - اعداد قوي"; sz = "7%"
    elif pct >= 0.40: v = "B - مقبول"; sz = "4%"
    else:             v = "تجنب"; sz = "صفر"
    await msg.reply_text(
        f"نتيجة خطة ب - {sym}\n{SEP}\n"
        f"النقاط: {score}/80 ({pct*100:.0f}%)\n"
        f"التقييم: {g}\n{v}\n"
        f"حجم الصفقة: {sz}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("حفظ في Scanner", callback_data=f"save_pb_{sym}_{score}")],
            [InlineKeyboardButton("بناء الصفقة", callback_data="trade_build")],
        ]))

async def save_pb_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts = update.callback_query.data.split("_")
    sym, score = parts[2], int(parts[3])
    g, _ = grade(score, "b")
    data = load_data()
    user = get_user(data, update.effective_user.id)
    idx = next((i for i, s in enumerate(user["stocks"]) if s["sym"] == sym), None)
    if idx is not None:
        user["stocks"][idx]["score"] = score
        user["stocks"][idx]["grade"] = g
    else:
        user["stocks"].append({"sym": sym, "plan": "b", "score": score, "grade": g, "fav": False, "notes": ""})
    save_data(data)
    await update.callback_query.message.reply_text(f"تم حفظ {sym} - {g}", reply_markup=MAIN_KB)
    return ConversationHandler.END
async def cmd_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query: await update.callback_query.answer()
    await msg.reply_text("بناء الصفقة\n\nادخل رمز السهم\nمثال: AAPL")
    return TRADE_SYM

async def trade_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["t_sym"] = update.message.text.strip().upper()
    await update.message.reply_text(
        f"{ctx.user_data['t_sym']} - اختر الخطة",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("خطة أ", callback_data="tplan_a"),
             InlineKeyboardButton("خطة ب", callback_data="tplan_b")],
        ]))
    return TRADE_PLAN

async def trade_plan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["t_plan"] = "a" if "tplan_a" in update.callback_query.data else "b"
    await update.callback_query.message.reply_text(
        "ادخل سعر الدخول\nمثال: 145.50")
    return TRADE_ENTRY

async def trade_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["t_entry"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text("ادخل Stop Loss\nمثال: 142.00")
        return TRADE_STOP
    except:
        await update.message.reply_text("ادخل رقما صحيحا")
        return TRADE_ENTRY

async def trade_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        sl = float(update.message.text.replace(",", "."))
        entry = ctx.user_data.get("t_entry", 0)
        if sl >= entry:
            await update.message.reply_text("Stop Loss يجب ان يكون اقل من سعر الدخول")
            return TRADE_STOP
        ctx.user_data["t_stop"] = sl
        await update.message.reply_text("ادخل راس المال\nمثال: 10000")
        return TRADE_CAP
    except:
        await update.message.reply_text("ادخل رقما")
        return TRADE_STOP

async def trade_cap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["t_cap"] = float(update.message.text.replace(",", ".").replace("$", ""))
        await update.message.reply_text("ادخل هدف الربح %\nمثال: 3")
        return TRADE_TGT
    except:
        await update.message.reply_text("ادخل رقما")
        return TRADE_CAP

async def trade_tgt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["t_tgt"] = float(update.message.text.replace(",", ".").replace("%", ""))
        await _show_trade(update.message, ctx)
        return ConversationHandler.END
    except:
        await update.message.reply_text("ادخل رقما")
        return TRADE_TGT

async def _show_trade(msg, ctx):
    sym   = ctx.user_data.get("t_sym", "")
    entry = ctx.user_data.get("t_entry", 0)
    sl    = ctx.user_data.get("t_stop", 0)
    cap   = ctx.user_data.get("t_cap", 10000)
    tgt   = ctx.user_data.get("t_tgt", 3)
    plan  = ctx.user_data.get("t_plan", "a")
    target = entry * (1 + tgt / 100)
    risk   = entry - sl
    reward = target - entry
    ratio  = reward / risk if risk > 0 else 0
    size   = int(cap * 0.10 / risk) if risk > 0 else 0
    t1 = entry * 1.02
    t2 = entry * 1.03
    t3 = entry * 1.05
    await msg.reply_text(
        f"خطة الصفقة - {sym}\n{SEP}\n"
        f"خطة {'أ' if plan=='a' else 'ب'}\n"
        f"دخول: {entry:.2f}\n"
        f"هدف: {target:.2f} (+{tgt}%)\n"
        f"Stop: {sl:.2f} (-{risk/entry*100:.1f}%)\n"
        f"R/R: {ratio:.2f}:1 {'ممتاز' if ratio>=2 else 'اقل من 2:1 - خطر'}\n\n"
        f"الحجم 10%: {size} سهم = ${size*entry:,.0f}\n"
        f"ربح متوقع: +${size*reward:.0f}\n"
        f"خسارة محتملة: -${size*risk:.0f}\n\n"
        f"{SEP}\n"
        f"خطة الخروج\n"
        f"الهدف 1: {t1:.2f} (+2%) - اخرج 50%\n"
        f"الهدف 2: {t2:.2f} (+3%) - اخرج 40%\n"
        f"الهدف 3: {t3:.2f} (+5%) - ابق 10%\n\n"
        f"{SEP}\n"
        f"Trailing Stop\n"
        f"عند {entry*1.015:.2f} (+1.5%) - SL الى الدخول\n"
        f"عند {entry*1.02:.2f} (+2%) - SL الى +0.75%\n"
        f"عند {entry*1.025:.2f} (+2.5%) - SL الى +1.5%\n\n"
        f"{SEP}\n"
        f"السيناريوهات\n"
        f"صعود: وصل {t1:.2f} - اخرج 50%\n"
        f"افقي: انتظر 3:30 ثم اخرج\n"
        f"هبوط: وصل {sl:.2f} - اخرج فورا",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("سجل هذه الصفقة", callback_data="journal_from_trade")],
        ]))

async def cmd_journal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query: await update.callback_query.answer()
    await msg.reply_text("تسجيل صفقة\n\nادخل رمز السهم\nمثال: AAPL")
    return JOURNAL_SYM

async def journal_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["j_sym"] = update.message.text.strip().upper()
    await update.message.reply_text("ادخل سعر الدخول")
    return JOURNAL_ENTRY

async def journal_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["j_entry"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text("ادخل سعر الخروج\nادخل 0 اذا الصفقة مفتوحة")
        return JOURNAL_EXIT
    except:
        await update.message.reply_text("ادخل رقما")
        return JOURNAL_ENTRY

async def journal_exit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.replace(",", "."))
        ctx.user_data["j_exit"] = val if val > 0 else None
        await update.message.reply_text("ادخل عدد الاسهم")
        return JOURNAL_QTY
    except:
        await update.message.reply_text("ادخل رقما")
        return JOURNAL_EXIT

async def journal_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["j_qty"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text("النتيجة",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ربح", callback_data="jres_win"),
                 InlineKeyboardButton("خسارة", callback_data="jres_loss")],
                [InlineKeyboardButton("مفتوحة", callback_data="jres_open")],
            ]))
        return JOURNAL_RES
    except:
        await update.message.reply_text("ادخل رقما")
        return JOURNAL_QTY

async def journal_res_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["j_res"] = update.callback_query.data.replace("jres_", "")
    await update.callback_query.message.reply_text("الحالة النفسية",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("مثالي - هادئ", callback_data="jm_optimal")],
            [InlineKeyboardButton("جيد - طبيعي",  callback_data="jm_good")],
            [InlineKeyboardButton("ضعيف - متوتر",  callback_data="jm_poor")],
        ]))
    return JOURNAL_MENTAL

async def journal_mental_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["j_mental"] = update.callback_query.data.replace("jm_", "")
    await update.callback_query.message.reply_text("هل اتبعت النظام؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("نعم - بالضبط", callback_data="jf_yes")],
            [InlineKeyboardButton("جزئيا",         callback_data="jf_partial")],
            [InlineKeyboardButton("لا - انحرفت",   callback_data="jf_no")],
        ]))
    return JOURNAL_FOLLOWED

async def journal_followed_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["j_followed"] = update.callback_query.data.replace("jf_", "")
    await update.callback_query.message.reply_text(
        "الدرس المستفاد\nاكتب ما تعلمته او ارسل - للتخطي")
    return JOURNAL_LESSON

async def journal_lesson(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lesson = update.message.text.strip()
    if lesson == "-": lesson = ""
    sym      = ctx.user_data.get("j_sym", "")
    entry    = ctx.user_data.get("j_entry", 0)
    exit_p   = ctx.user_data.get("j_exit")
    qty      = ctx.user_data.get("j_qty", 1)
    res      = ctx.user_data.get("j_res", "open")
    mental   = ctx.user_data.get("j_mental", "good")
    followed = ctx.user_data.get("j_followed", "yes")
    pnl = (exit_p - entry) * qty if exit_p else None
    pct = ((exit_p - entry) / entry * 100) if exit_p else None
    data = load_data()
    user = get_user(data, update.effective_user.id)
    user["trades"].insert(0, {
        "id": int(datetime.now().timestamp()),
        "sym": sym, "date": date.today().isoformat(),
        "entry": entry, "exit": exit_p, "qty": qty,
        "res": res, "pnl": pnl, "pct": pct,
        "plan": ctx.user_data.get("t_plan", "a"),
        "mental": mental, "followed": followed, "lesson": lesson,
    })
    save_data(data)
    ri = {"win": "ربح", "loss": "خسارة", "open": "مفتوحة"}
    mt = {"optimal": "مثالي", "good": "جيد", "poor": "ضعيف"}.get(mental, "")
    ft = {"yes": "نعم", "partial": "جزئي", "no": "لا"}.get(followed, "")
    lines = [f"تم التسجيل - {sym}", SEP,
             f"دخول: {entry:.2f} - خروج: {exit_p:.2f if exit_p else 0}",
             f"النتيجة: {ri.get(res,'')}"]
    if pnl is not None:
        lines.append(f"P&L: {'+' if pnl>=0 else ''}{pnl:.2f} ({'+' if pct>=0 else ''}{pct:.2f}%)")
    lines += [f"النفسية: {mt} - النظام: {ft}"]
    if lesson: lines.append(f"الدرس: {lesson}")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_KB)
    return ConversationHandler.END
async def cmd_perf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_user.id)
    trades = user.get("trades", [])
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    if len(trades) < 2:
        await msg.reply_text("سجل صفقتين على الاقل لعرض الاحصاءات", reply_markup=MAIN_KB)
        return
    wins   = [t for t in trades if t.get("res") == "win"]
    losses = [t for t in trades if t.get("res") == "loss"]
    closed = [t for t in trades if t.get("res") != "open"]
    total_pnl = sum(t.get("pnl") or 0 for t in trades)
    avg_win  = sum(abs(t.get("pct") or 0) for t in wins)   / len(wins)   if wins   else 0
    avg_loss = sum(abs(t.get("pct") or 0) for t in losses) / len(losses) if losses else 1
    wr = len(wins) / len(closed) * 100 if closed else 0
    pf = avg_win / avg_loss if avg_loss > 0 else 0
    pa = [t for t in trades if t.get("plan") == "a"]
    pb = [t for t in trades if t.get("plan") == "b"]
    def plan_wr(lst):
        cl = [t for t in lst if t.get("res") != "open"]
        w  = [t for t in lst if t.get("res") == "win"]
        return len(w)/len(cl)*100 if cl else 0
    opt  = [t for t in trades if t.get("mental") == "optimal"]
    poor = [t for t in trades if t.get("mental") == "poor"]
    with_pct = [t for t in trades if t.get("pct") is not None]
    best  = max(with_pct, key=lambda t: t["pct"]) if with_pct else None
    worst = min(with_pct, key=lambda t: t["pct"]) if with_pct else None
    lines = [
        f"تحليل الاداء\n{SEP}",
        f"اجمالي: {len(trades)} صفقة",
        f"نسبة الفوز: {wr:.0f}% ({len(wins)}W / {len(losses)}L)",
        f"Profit Factor: {pf:.2f}x",
        f"اجمالي P&L: {'+' if total_pnl>=0 else ''}{total_pnl:.2f}",
        f"متوسط الربح: +{avg_win:.2f}% - متوسط الخسارة: -{avg_loss:.2f}%",
        SEP,
        f"خطة أ: {len(pa)} صفقة - فوز {plan_wr(pa):.0f}%",
        f"خطة ب: {len(pb)} صفقة - فوز {plan_wr(pb):.0f}%",
    ]
    if opt and poor:
        oc = [t for t in opt  if t.get("res") != "open"]
        pc = [t for t in poor if t.get("res") != "open"]
        ow = len([t for t in opt  if t.get("res") == "win"])
        pw = len([t for t in poor if t.get("res") == "win"])
        lines += [SEP, "تاثير الحالة النفسية",
                  f"مثالي: {len(opt)} صفقة - فوز {ow/len(oc)*100 if oc else 0:.0f}%",
                  f"ضعيف: {len(poor)} صفقة - فوز {pw/len(pc)*100 if pc else 0:.0f}%"]
    if best and worst:
        lines += [SEP,
                  f"افضل صفقة: {best['sym']} +{best['pct']:.2f}%",
                  f"اسوا صفقة: {worst['sym']} {worst['pct']:.2f}%"]
    lines += [SEP,
              "نسبة الفوز ممتازة" if wr>=65 else "قابلة للتحسين" if wr>=50 else "راجع شروط الدخول",
              "Profit Factor ممتاز" if pf>=2 else "مقبول" if pf>=1.3 else "راجع Stop Loss"]
    await msg.reply_text("\n".join(lines), reply_markup=MAIN_KB)

async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    await msg.reply_text(
        f"القواعد الذهبية\n{SEP}\n"
        "ادارة راس المال\n"
        "- حجم الصفقة 10% كحد اقصى\n"
        "- حد الخسارة اليومي -3%\n"
        "- حد الخسارة الشهري -10%\n"
        "- اقصى صفقتين يوميا\n\n"
        "القواعد النفسية\n"
        "- 3 خسائر متتالية - اغلق وعد غدا\n"
        "- بعد خسارة - انتظر ساعتين\n"
        "- Revenge Trading = نهاية الحساب\n\n"
        "التوقيت\n"
        "- الدخول 9:45-10:30 او 2:00-3:30 ET\n"
        "- خروج الزامي قبل 3:45 PM\n\n"
        "قواعد الدخول\n"
        "- لا دخول بدون Stop Loss\n"
        "- R/R 2:1 على الاقل\n"
        "- SPY فوق MA50 شرط لا يكسر\n"
        "- VIX تحت 25 للخطة أ - تحت 20 للخطة ب\n\n"
        "الفلسفة\n"
        "- الصبر هو السلاح الاقوى\n"
        "- الحفاظ على راس المال اهم من الربح",
        reply_markup=MAIN_KB)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"دليل الاستخدام\n{SEP}\n"
        "/start - الرئيسية\n"
        "/macro - تقييم السوق\n"
        "/plana - تقييم خطة أ\n"
        "/planb - تقييم خطة ب\n"
        "/trade - بناء الصفقة\n"
        "/journal - تسجيل صفقة\n"
        "/scanner - قائمة المراقبة\n"
        "/perf - تحليل الاداء\n"
        "/rules - القواعد\n"
        "/window - النافذة الحالية\n\n"
        "يوميا\n"
        "1 - /macro تقييم السوق\n"
        "2 - /plana او /planb تقييم السهم\n"
        "3 - /trade بناء الصفقة\n"
        "4 - /journal تسجيل النتيجة\n"
        "5 - /perf مراجعة الاداء",
        reply_markup=MAIN_KB)

async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    routes = {
        "المشهد الكلي":    cmd_macro,
        "Scanner":         cmd_scanner,
        "تقييم خطة أ":    start_plan_a,
        "تقييم خطة ب":    start_plan_b,
        "بناء الصفقة":    cmd_trade,
        "سجل صفقة":       cmd_journal,
        "الاداء":          cmd_perf,
        "القواعد":         cmd_rules,
        "النافذة الحالية": cmd_window,
        "مساعدة":          cmd_help,
    }
    handler = routes.get(update.message.text)
    if handler:
        return await handler(update, ctx)

async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = update.callback_query.data
    if d == "macro_start":  return await macro_start_cb(update, ctx)
    elif d == "windows":    await windows_cb(update, ctx)
    elif d == "stock_add":  return await stock_add_cb(update, ctx)
    elif d == "trade_build": return await cmd_trade(update, ctx)
    elif d == "journal_from_trade": return await cmd_journal(update, ctx)

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN غير موجود")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    macro_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(macro_start_cb, pattern="^macro_start$")],
        states={
            MACRO_VIX:    [MessageHandler(filters.TEXT & ~filters.COMMAND, macro_vix)],
            MACRO_SPY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, macro_spy)],
            MACRO_BREADTH:[MessageHandler(filters.TEXT & ~filters.COMMAND, macro_breadth)],
            MACRO_FED:    [MessageHandler(filters.TEXT & ~filters.COMMAND, macro_fed)],
            MACRO_EVENTS: [CallbackQueryHandler(macro_events_cb, pattern="^fed_")],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )
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
                CallbackQueryHandler(pa_answer_cb, pattern="^pa_"),
                CallbackQueryHandler(save_pa_cb,   pattern="^save_pa_"),
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
                CallbackQueryHandler(pb_answer_cb, pattern="^pb_"),
                CallbackQueryHandler(save_pb_cb,   pattern="^save_pb_"),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )
    trade_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^بناء الصفقة$"), cmd_trade),
            CommandHandler("trade", cmd_trade),
            CallbackQueryHandler(cmd_trade, pattern="^trade_build$"),
        ],
        states={
            TRADE_SYM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_sym)],
            TRADE_PLAN:  [CallbackQueryHandler(trade_plan_cb, pattern="^tplan_")],
            TRADE_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_entry)],
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
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("macro",   cmd_macro))
    app.add_handler(CommandHandler("scanner", cmd_scanner))
    app.add_handler(CommandHandler("perf",    cmd_perf))
    app.add_handler(CommandHandler("rules",   cmd_rules))
    app.add_handler(CommandHandler("window",  cmd_window))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(macro_conv)
    app.add_handler(stock_conv)
    app.add_handler(pa_conv)
    app.add_handler(pb_conv)
    app.add_handler(trade_conv)
    app.add_handler(journal_conv)
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    print("@TurkiAlotaibi_bot - Running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
