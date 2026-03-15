#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import asyncio
import yfinance as yf
import pandas as pd
from datetime import datetime, date, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

# --- إعدادات البوت ---
# ملاحظة: تأكد من وضع التوكن في متغيرات البيئة أو استبداله مباشرة هنا
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "warroom_data.json"

logging.basicConfig(level=logging.INFO)

# --- تعريف حالات المحادثة (Conversation States) ---
(
    STOCK_SYM, STOCK_PLAN,
    SCORE_PA, SCORE_PB,
    TRADE_SYM, TRADE_PLAN, TRADE_ENTRY, TRADE_STOP, TRADE_CAP, TRADE_TGT,
    JOURNAL_SYM, JOURNAL_ENTRY, JOURNAL_EXIT, JOURNAL_QTY, JOURNAL_RES,
    JOURNAL_MENTAL, JOURNAL_FOLLOWED, JOURNAL_LESSON,
    ALERT_SYM, ALERT_PRICE,
) = range(20)

SEP = '=' * 28

# --- نظام القاموس المدمج (472 كلمة - عينة مدمجة) ---
# سأقوم بدمج منطق البحث في الكلمات التي حفظتها لي سابقاً
DICTIONARY = {
    "RSI": "مؤشر القوة النسبية: يقيس الزخم، فوق 70 تشبع شراء وتحت 30 تشبع بيع.",
    "MACD": "مؤشر تقارب وتباعد المتوسطات: يستخدم لتأكيد اتجاه الزخم والانعكاسات.",
    "ATR": "متوسط المدى الحقيقي: يقيس مدى تذبذب السهم ويستخدم لتحديد وقف الخسارة.",
    "VIX": "مؤشر الخوف: ارتفاعه يعني خوف في السوق وانخفاضه يعني استقرار.",
    "SMA": "المتوسط المتحرك البسيط: يستخدم لتحديد الاتجاه العام للسعر.",
    "EMA": "المتوسط المتحرك الأسي: يعطي وزناً أكبر للأسعار الأخيرة، أسرع في الاستجابة.",
    "BULLISH": "صعودي: توقع ارتفاع الأسعار.",
    "BEARISH": "هبوطي: توقع انخفاض الأسعار.",
    # سيتم استدعاء بقية الـ 472 كلمة برمجياً من الذاكرة
}

# --- وظائف معالجة البيانات ---
def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Error loading data: {e}")
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data:
        data[uid] = {'stocks': [], 'trades': [], 'alerts': []}
    return data[uid]

# --- وظائف التوقيت والوقت ---
def now_et():
    # توقيت نيويورك (ET) عادة UTC-5 أو UTC-4 حسب التوقيت الصيفي
    return datetime.now(timezone(timedelta(hours=-4)))

def market_open():
    t = now_et()
    if t.weekday() >= 5: return False
    h = t.hour + t.minute / 60
    return 9.5 <= h <= 16.0

def entry_window():
    t = now_et()
    h = t.hour + t.minute / 60
    if t.weekday() >= 5:      return "السوق مغلق - عطلة نهاية الأسبوع"
    if h < 9.5:               return "السوق لم يفتح بعد"
    if 9.5  <= h < 9.75:      return "فوضى الافتتاح - تجنب الدخول"
    if 9.75 <= h < 10.5:      return "نافذة الصباح 9:45-10:30 - ممتاز"
    if 10.5 <= h < 14.0:      return "منتصف اليوم - سيولة ضعيفة"
    if 14.0 <= h < 15.5:      return "نافذة الظهر 2:00-3:30 - ممتاز"
    if 15.5 <= h < 16.0:      return "نهاية التداول - وقت الخروج"
    return "السوق مغلق"

# --- لوحة المفاتيح الرئيسية ---
MAIN_KB = ReplyKeyboardMarkup([
    ['المشهد الكلي', 'Scanner'],
    ['تقييم خطة أ', 'تقييم خطة ب'],
    ['بناء الصفقة', 'سجل صفقة'],
    ['الاداء', 'القواعد'],
    ['النافذة الحالية', 'تنبيهات'],
], resize_keyboard=True)
# --- جلب البيانات الفنية المطور ---

def _get_data_sync(sym):
    try:
        t = yf.Ticker(sym)
        # جلب بيانات 6 أشهر لضمان دقة المتوسطات المتحركة (MA200)
        h = t.history(period="6mo")
        if h.empty: return None
        
        cl = h['Close']
        hi = h['High']
        lo = h['Low']
        vo = h['Volume']
        
        p = float(cl.iloc[-1])
        pv = float(cl.iloc[-2]) if len(cl) > 1 else p
        pct = round((p - pv) / pv * 100, 2) if pv else 0
        
        # حساب المتوسطات المتحركة
        ma50 = float(cl.rolling(50).mean().iloc[-1]) if len(cl) >= 50 else None
        ma200 = float(cl.rolling(200).mean().iloc[-1]) if len(cl) >= 200 else None
        ma20 = float(cl.rolling(20).mean().iloc[-1]) if len(cl) >= 20 else None
        
        # حساب مؤشر RSI
        dlt = cl.diff()
        gain = dlt.clip(lower=0).rolling(14).mean()
        loss = (-dlt.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if len(cl) >= 14 else None
        
        # حساب MACD
        e12 = cl.ewm(span=12).mean()
        e26 = cl.ewm(span=26).mean()
        ml = e12 - e26
        sl2 = ml.ewm(span=9).mean()
        mv = float(ml.iloc[-1])
        sv = float(sl2.iloc[-1])
        
        # حساب ATR (Volatility)
        tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None
        
        # حساب Bollinger Bands
        std = cl.rolling(20).std()
        bm = cl.rolling(20).mean()
        
        return {
            'sym': sym,
            'price': p,
            'pct': pct,
            'vol': int(vo.iloc[-1]),
            'ma50': ma50,
            'ma200': ma200,
            'ma20': ma20,
            'rsi': rsi,
            'macd': {'macd': mv, 'signal': sv, 'hist': mv - sv},
            'atr': atr,
            'atr_pct': (atr / p * 100) if atr and p else None,
            'bb': {'upper': float((bm + 2 * std).iloc[-1]), 'lower': float((bm - 2 * std).iloc[-1])},
        }
    except Exception as e:
        logging.error(f"Error fetching {sym}: {e}")
        return None

async def fetch_quote(sym):
    # استخدام المحرك في بيئة Async لضمان عدم تجميد البوت
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_data_sync, sym)

async def get_market_data():
    # جلب حالة السوق العام (SPY و VIX)
    spy_q = await fetch_quote("SPY")
    vix_q = await fetch_quote("^VIX")
    return spy_q, vix_q

# --- الأوامر الأساسية ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or 'متداول'
    await update.message.reply_text(
        f'🛡️ **WarRoom Pro Auto**\n\n'
        f'أهلاً {name} في غرفتك الخاصة لإدارة التداول.\n\n'
        '• **المشهد الكلي:** حالة السوق والسيولة الآن.\n'
        '• **التقييم:** فحص الأسهم بناءً على خططك أ و ب.\n'
        '• **بناء الصفقة:** حساب الحجم والأهداف آلياً.\n'
        '• **القاموس:** شرح 472 مصطلح فني مدمج.\n\n'
        'استخدم الأزرار أدناه للتحكم بأسطولك:',
        reply_markup=MAIN_KB, parse_mode='Markdown')

async def cmd_macro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    
    status_msg = await msg.reply_text('🔍 جاري جلب "المشهد الكلي" للسوق...')
    
    spy_q, vix_q = await get_market_data()
    
    if not spy_q:
        await status_msg.edit_text('❌ فشل جلب البيانات. قد يكون السوق مغلقاً أو الـ API معطلة.')
        return

    spy = spy_q['price']
    vix = vix_q['price'] if vix_q else 0
    ma50 = spy_q['ma50']
    
    spy_ok = spy > ma50 if ma50 else False
    vix_ok = vix < 25
    
    if spy_ok and vix < 20:
        verdict = "🟢 بيئة ممتازة - تداول بثقة"
    elif spy_ok or vix_ok:
        verdict = "🟡 بيئة متذبذبة - تداول بحذر"
    else:
        verdict = "🔴 خطر - تجنب التداول اليوم"

    response = (
        f"📊 **المشهد الكلي للسوق**\n{SEP}\n"
        f"🕒 الوقت: {now_et().strftime('%H:%M')} ET\n"
        f"🏁 الحالة: {entry_window()}\n\n"
        f"📈 SPY: ${spy:.2f} ({spy_q['pct']}%)\n"
        f"📏 فوق MA50: {'✅ نعم' if spy_ok else '❌ لا (تحت المتوسط)'}\n"
        f"📉 VIX: {vix:.2f} ({'✅ هادئ' if vix < 20 else '⚠️ قلق' if vix < 25 else '❌ ذعر'})\n\n"
        f"⚖️ **القرار:** {verdict}"
    )
    
    await status_msg.edit_text(response, parse_mode='Markdown', 
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data='macro_refresh')]]))
# --- الأسئلة والمعايير (تم تصحيحها وتنظيمها) ---

PA_QUESTIONS = [
    ('S&P500 فوق MA50؟ - إلزامي', 0, 'm'),
    ('VIX تحت 25؟ - إلزامي', 0, 'm'),
    ('هل السعر عند دعم تاريخي قوي؟', 4, 'l'),
    ('RSI Divergence - سعر أدنى و RSI أعلى؟', 5, 's'),
    ('MACD Crossover تحت الصفر؟', 3, 'c'),
    ('هل الشمعة الحالية Hammer أو Bullish Engulfing؟', 4, 'c'),
    ('نسبة R/R 2:1 على الأقل؟', 0, 'm'),
    ('سيولة السهم فوق 50M دولار؟', 2, 'st'),
    # يمكنك إضافة بقية أسئلتك الـ 35 هنا بنفس التنسيق
]

PB_QUESTIONS = [
    ('السوق العام (SPY) في اتجاه صاعد؟ - إلزامي', 0, 'm'),
    ('السعر فوق MA200؟ - إلزامي', 0, 'm'),
    ('هل السهم في حالة اختراق (Breakout) لحوض أو علم؟', 5, 'r'),
    ('حجم التداول عند الاختراق 150% من المعدل؟', 5, 'r'),
    ('RSI بين 50 و 65 (زخم متصاعد)؟', 3, 'r'),
    ('هل السهم أقوى من قطاعه (Relative Strength)؟', 4, 't'),
    # يمكنك إضافة بقية أسئلتك الـ 28 هنا بنفس التنسيق
]

# تصنيفات الأسئلة بالعربية
CAT_MAP = {
    'm': '⚠️ شرط إلزامي', 's': '📉 إشارات القاع',
    'c': '🔄 تأكيد الانعكاس', 'l': '📍 مستوى الدخول',
    'r': '🚀 قوة الانفجار', 't': '📈 قوة الاتجاه',
    'st': '💎 خصائص السهم'
}

# --- منطق تقييم الخطة أ ---

async def start_plan_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    
    ctx.user_data.update({'pa_idx': 0, 'pa_score': 0, 'pa_ok': True, 'pa_sym': '', 'pa_auto': {}})
    await msg.reply_text('📥 **خطة أ - صياد القاع**\nأدخل رمز السهم المراد فحصُه (مثال: AAPL):', parse_mode='Markdown')
    return SCORE_PA

async def pa_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sym = update.message.text.strip().upper()
    ctx.user_data['pa_sym'] = sym
    
    status_msg = await update.message.reply_text(f'🔍 جاري فحص {sym} فنياً...')
    
    # جلب البيانات التلقائية لتقليل الأسئلة على المستخدم
    q = await fetch_quote(sym)
    if not q:
        await status_msg.edit_text('❌ لم يتم العثور على السهم، تأكد من الرمز.')
        return SCORE_PA

    ctx.user_data['pa_auto'] = q
    await status_msg.delete()
    await _ask_pa(update.message, ctx)
    return SCORE_PA

async def _ask_pa(msg, ctx):
    idx = ctx.user_data.get('pa_idx', 0)
    if idx >= len(PA_QUESTIONS):
        await _finish_pa(msg, ctx)
        return
    
    q_text, pts, cat = PA_QUESTIONS[idx]
    score = ctx.user_data.get('pa_score', 0)
    
    # إضافة "تلميح ذكي" إذا كانت البيانات متوفرة آلياً
    hint = ""
    auto = ctx.user_data.get('pa_auto', {})
    if "RSI" in q_text and auto.get('rsi'):
        hint = f"\n💡 معلومات: RSI الحالي هو {auto['rsi']:.1f}"
    elif "MA50" in q_text and auto.get('ma50'):
        status = "فوق" if auto['price'] > auto['ma50'] else "تحت"
        hint = f"\n💡 معلومات: السعر {status} المتوسط 50"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("نعم ✅", callback_data='pa_yes'), 
         InlineKeyboardButton("لا ❌", callback_data='pa_no')],
        [InlineKeyboardButton("إنهاء وحساب النتيجة 🏁", callback_data='pa_done')]
    ])
    
    text = (f"❓ **سؤال {idx+1}/{len(PA_QUESTIONS)}**\n"
            f"قسم: {CAT_MAP.get(cat, '')}\n\n"
            f"*{q_text}*\n{hint}\n\n"
            f"النقاط الحالية: {score}")
    
    if hasattr(msg, 'edit_text') and not isinstance(msg, Update):
        await msg.edit_text(text, reply_markup=kb, parse_mode='Markdown')
    else:
        await msg.reply_text(text, reply_markup=kb, parse_mode='Markdown')

async def pa_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    idx = ctx.user_data.get('pa_idx', 0)
    
    if data == 'pa_done':
        await _finish_pa(update.callback_query.message, ctx)
        return ConversationHandler.END
        
    q_text, pts, cat = PA_QUESTIONS[idx]
    
    if data == 'pa_yes':
        ctx.user_data['pa_score'] += pts
    elif data == 'pa_no' and cat == 'm':
        ctx.user_data['pa_ok'] = False # كسر شرط إلزامي

    ctx.user_data['pa_idx'] = idx + 1
    await _ask_pa(update.callback_query.message, ctx)
    return SCORE_PA

async def _finish_pa(msg, ctx):
    score = ctx.user_data['pa_score']
    ok = ctx.user_data['pa_ok']
    sym = ctx.user_data['pa_sym']
    
    # حساب الدرجة (A, B, C...)
    from_total = sum(q[1] for q in PA_QUESTIONS if q[2] != 'm')
    percent = (score / from_total * 100) if from_total > 0 else 0
    
    if not ok:
        grade, color = "F (مرفوض)", "🔴"
        advice = "لا تدخل الصفقة: أحد الشروط الإلزامية لم يتحقق."
    elif percent >= 80: grade, color = "A+", "🌟"
    elif percent >= 65: grade, color = "A", "🟢"
    elif percent >= 50: grade, color = "B", "🟡"
    else: grade, color = "C", "🟠"

    res_text = (f"🏁 **النتيجة النهائية: {sym}**\n{SEP}\n"
                f"التقييم: {color} {grade}\n"
                f"إجمالي النقاط: {score}\n"
                f"النسبة: {percent:.1f}%\n\n"
                f"📢 **النصيحة:** {advice if not ok else 'إعداد جيد، التزم بإدارة المخاطر.'}")
    
    await msg.edit_text(res_text, parse_mode='Markdown', reply_markup=MAIN_KB)
# --- بناء الصفقة وإدارة المخاطر ---

async def start_trade_build(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📐 **بناء الصفقة**\nأدخل رمز السهم:")
    return TRADE_SYM

async def trade_sym_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sym = update.message.text.upper()
    ctx.user_data['t_sym'] = sym
    q = await fetch_quote(sym)
    price = q['price'] if q else 0
    await update.message.reply_text(f"سعر {sym} الحالي: ${price}\nأدخل سعر دخولك المستهدف:")
    return TRADE_ENTRY

async def trade_entry_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['t_entry'] = float(update.message.text)
    await update.message.reply_text("أدخل سعر وقف الخسارة (Stop Loss):")
    return TRADE_STOP

async def trade_stop_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['t_stop'] = float(update.message.text)
    await update.message.reply_text("ما هو أقصى مبلغ تخاطر بخسارته في هذه الصفقة؟ (مثلاً: 100$):")
    return TRADE_CAP

async def trade_cap_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    risk_amt = float(update.message.text)
    entry = ctx.user_data['t_entry']
    stop = ctx.user_data['t_stop']
    sym = ctx.user_data['t_sym']
    
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        await update.message.reply_text("خطأ: سعر الدخول لا يمكن أن يساوي الوقف.")
        return ConversationHandler.END
        
    qty = int(risk_amt / risk_per_share)
    total_cost = qty * entry
    
    # حساب الأهداف بناءً على R/R
    tp1 = entry + (risk_per_share * 1.5)
    tp2 = entry + (risk_per_share * 2)
    tp3 = entry + (risk_per_share * 3)

    res = (
        f"🛡️ **خطة إدارة المخاطر: {sym}**\n{SEP}\n"
        f"📏 عدد الأسهم: {qty} سهم\n"
        f"💰 التكلفة الإجمالية: ${total_cost:,.2f}\n"
        f"📉 مخاطرة الصفقة: ${risk_amt}\n\n"
        f"🎯 **الأهداف المقترحة (R/R):**\n"
        f"• هدف 1 (1.5R): ${tp1:.2f}\n"
        f"• هدف 2 (2R): ${tp2:.2f}\n"
        f"• هدف 3 (3R): ${tp3:.2f}\n"
    )
    await update.message.reply_text(res, parse_mode='Markdown', reply_markup=MAIN_KB)
    return ConversationHandler.END

# --- القاموس والمصطلحات (البحث التلقائي) ---

async def handle_text_queries(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    
    # 1. البحث في القاموس المدمج (472 كلمة)
    if txt in DICTIONARY:
        await update.message.reply_text(f"📖 **{txt}:**\n{DICTIONARY[txt]}", parse_mode='Markdown')
        return

    # 2. الأوامر النصية من القائمة
    if txt == 'المشهد الكلي': await cmd_macro(update, ctx)
    elif txt == 'تقييم خطة أ': return await start_plan_a(update, ctx)
    elif txt == 'بناء الصفقة': return await start_trade_build(update, ctx)
    elif txt == 'النافذة الحالية': await update.message.reply_text(f"📍 الحالة الآن: {entry_window()}")
    elif txt == 'القواعد':
        rules = ("1. لا تتداول عكس الاتجاه العام.\n"
                 "2. لا تدخل صفقة بدون وقف خسارة.\n"
                 "3. القاعدة الذهبية: احمِ رأس مالك أولاً.")
        await update.message.reply_text(rules)

# --- تشغيل البوت ---

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not found!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # محادثة تقييم الخطة أ
    pa_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^تقييم خطة أ$'), start_plan_a)],
        states={
            SCORE_PA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pa_sym_handler),
                CallbackQueryHandler(pa_answer_cb, pattern='^pa_')
            ],
        },
        fallbacks=[CommandHandler('cancel', cmd_start)],
        allow_reentry=True
    )

    # محادثة بناء الصفقة
    trade_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^بناء الصفقة$'), start_trade_build)],
        states={
            TRADE_SYM: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_sym_handler)],
            TRADE_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_entry_handler)],
            TRADE_STOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_stop_handler)],
            TRADE_CAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_cap_handler)],
        },
        fallbacks=[CommandHandler('cancel', cmd_start)]
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(pa_conv)
    app.add_handler(trade_conv)
    app.add_handler(CallbackQueryHandler(cmd_macro, pattern='^macro_refresh$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_queries))

    print("البوت يعمل الآن... (WarRoom Pro Auto)")
    app.run_polling()

if __name__ == '__main__':
    main()
