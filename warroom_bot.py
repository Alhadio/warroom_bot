#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import asyncio
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

# --- 1. الإعدادات الأساسية ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "warroom_data.json"

logging.basicConfig(level=logging.INFO)

# تعريف حالات المحادثة
(
    SCORE_PA, 
    TRADE_SYM, TRADE_ENTRY, TRADE_STOP, TRADE_CAP,
) = range(5)

SEP = '=' * 28

# --- 2. القاموس (هنا تضع كلماتك الـ 472) ---
DICTIONARY = {
    "RSI": "مؤشر القوة النسبية: يقيس الزخم، فوق 70 تشبع شراء وتحت 30 تشبع بيع.",
    "MACD": "مؤشر تقارب وتباعد المتوسطات: يستخدم لتأكيد اتجاه الزخم والانعكاسات.",
    "ATR": "متوسط المدى الحقيقي: يقيس مدى تذبذب السهم ويستخدم لتحديد وقف الخسارة.",
    "BULLISH": "صعودي: توقع ارتفاع الأسعار.",
    "BEARISH": "هبوطي: توقع انخفاض الأسعار.",
}

# --- 3. محرك البيانات الفنية ---
def _get_data_sync(sym):
    try:
        t = yf.Ticker(sym)
        h = t.history(period="6mo")
        if h.empty: return None
        cl = h['Close']
        p = float(cl.iloc[-1])
        pv = float(cl.iloc[-2]) if len(cl) > 1 else p
        pct = round((p - pv) / pv * 100, 2)
        ma50 = float(cl.rolling(50).mean().iloc[-1]) if len(cl) >= 50 else None
        
        # حساب RSI مبسط
        dlt = cl.diff()
        gain = dlt.clip(lower=0).rolling(14).mean()
        loss = (-dlt.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if len(cl) >= 14 else None
        
        return {'sym': sym, 'price': p, 'pct': pct, 'ma50': ma50, 'rsi': rsi}
    except: return None

async def fetch_quote(sym):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_data_sync, sym)

def now_et():
    return datetime.now(timezone(timedelta(hours=-4)))

def entry_window():
    t = now_et()
    h = t.hour + t.minute / 60
    if t.weekday() >= 5: return "السوق مغلق (عطلة)"
    if 9.75 <= h < 10.5: return "نافذة الصباح 🟢"
    if 14.0 <= h < 15.5: return "نافذة الظهر 🟢"
    return "خارج نوافذ الدخول المثالية"

# --- 4. معايير التقييم (خطة أ) ---
PA_QUESTIONS = [
    ('S&P500 فوق MA50؟ - إلزامي', 0, 'm'),
    ('VIX تحت 25؟ - إلزامي', 0, 'm'),
    ('هل السعر عند دعم تاريخي قوي؟', 5, 'l'),
    ('RSI Divergence - سعر أدنى و RSI أعلى؟', 5, 's'),
    ('نسبة R/R 2:1 على الأقل؟', 0, 'm'),
]

# --- 5. لوحات المفاتيح ---
MAIN_KB = ReplyKeyboardMarkup([
    ['المشهد الكلي', 'Scanner'],
    ['تقييم خطة أ', 'تقييم خطة ب'],
    ['بناء الصفقة', 'سجل صفقة'],
    ['الاداء', 'القواعد'],
    ['النافذة الحالية', 'تنبيهات'],
], resize_keyboard=True)

# --- 6. وظائف الأوامر ---
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ WarRoom Pro Auto جاهز للعمل.", reply_markup=MAIN_KB)

async def cmd_macro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    s_msg = await msg.reply_text('🔍 جاري التحليل...')
    spy = await fetch_quote("SPY")
    vix = await fetch_quote("^VIX")
    
    if not spy:
        await s_msg.edit_text("❌ خطأ في جلب البيانات")
        return

    verdict = "🟢 ممتاز" if spy['price'] > spy['ma50'] and vix['price'] < 20 else "🔴 حذر"
    res = (f"📊 **المشهد الكلي**\n{SEP}\n"
           f"📈 SPY: ${spy['price']:.2f} ({spy['pct']}%)\n"
           f"📉 VIX: {vix['price']:.2f}\n"
           f"📍 الحالة: {entry_window()}\n"
           f"⚖️ القرار: {verdict}")
    await s_msg.edit_text(res, parse_mode='Markdown')

# --- 7. محادثة تقييم الخطة أ ---
async def start_plan_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.update({'pa_idx': 0, 'pa_score': 0, 'pa_ok': True, 'pa_sym': ''})
    await update.message.reply_text('📥 أدخل رمز السهم للفحص (خطة أ):')
    return SCORE_PA

async def pa_logic_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if 'pa_sym' not in ctx.user_data or not ctx.user_data['pa_sym']:
        ctx.user_data['pa_sym'] = update.message.text.upper()
    
    idx = ctx.user_data['pa_idx']
    if idx < len(PA_QUESTIONS):
        q_text = PA_QUESTIONS[idx][0]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("نعم ✅", callback_data='pa_y'),
            InlineKeyboardButton("لا ❌", callback_data='pa_n')
        ]])
        await update.message.reply_text(f"❓ {q_text}", reply_markup=kb)
        return SCORE_PA
    else:
        await finish_pa(update, ctx)
        return ConversationHandler.END

async def pa_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = ctx.user_data['pa_idx']
    
    if query.data == 'pa_y':
        ctx.user_data['pa_score'] += PA_QUESTIONS[idx][1]
    elif query.data == 'pa_n' and PA_QUESTIONS[idx][2] == 'm':
        ctx.user_data['pa_ok'] = False
        
    ctx.user_data['pa_idx'] += 1
    if ctx.user_data['pa_idx'] < len(PA_QUESTIONS):
        q_text = PA_QUESTIONS[ctx.user_data['pa_idx']][0]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("نعم ✅", callback_data='pa_y'),
            InlineKeyboardButton("لا ❌", callback_data='pa_n')
        ]])
        await query.edit_message_text(f"❓ {q_text}", reply_markup=kb)
    else:
        await finish_pa(query, ctx)

async def finish_pa(target, ctx):
    txt = f"🏁 نتيجة {ctx.user_data['pa_sym']}: {'✅ مقبول' if ctx.user_data['pa_ok'] else '❌ مرفوض'}"
    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(txt)
    else:
        await target.reply_text(txt)

# --- 8. بناء الصفقة ---
async def start_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📐 أدخل رمز السهم لحساب المخاطرة:")
    return TRADE_SYM

async def trade_sym(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['t_sym'] = update.message.text.upper()
    await update.message.reply_text("سعر الدخول؟")
    return TRADE_ENTRY

async def trade_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['t_e'] = float(update.message.text)
    await update.message.reply_text("سعر الوقف؟")
    return TRADE_STOP

async def trade_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['t_s'] = float(update.message.text)
    await update.message.reply_text("مبلغ المخاطرة ($)؟")
    return TRADE_CAP

async def trade_cap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    risk = float(update.message.text)
    diff = abs(ctx.user_data['t_e'] - ctx.user_data['t_s'])
    qty = int(risk / diff) if diff > 0 else 0
    await update.message.reply_text(f"📊 الكمية: {qty} سهم\nالتكلفة: ${qty * ctx.user_data['t_e']:.2f}")
    return ConversationHandler.END

# --- 9. معالج النصوص الذكي (حل المشكلة السابقة) ---
async def global_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    
    # أولوية 1: أزرار القائمة
    if txt == 'المشهد الكلي': await cmd_macro(update, ctx); return
    if txt == 'النافذة الحالية': await update.message.reply_text(entry_window()); return
    if txt == 'القواعد': await update.message.reply_text("1. الوقف مقدس\n2. لا تعاند السوق"); return
    
    # أولوية 2: القاموس
    if txt.upper() in DICTIONARY:
        await update.message.reply_text(f"📖 {txt.upper()}: {DICTIONARY[txt.upper()]}")
        return
        
    # أولوية 3: فحص سهم سريع
    if len(txt) <= 5 and txt.isalpha():
        q = await fetch_quote(txt.upper())
        if q:
            await update.message.reply_text(f"📈 {q['sym']}: ${q['price']} ({q['pct']}%)")
            return

    await update.message.reply_text("أمر غير معروف، استخدم القائمة.")

# --- 10. تشغيل البوت ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # المحادثات
    pa_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^تقييم خطة أ$'), start_plan_a)],
        states={SCORE_PA: [MessageHandler(filters.TEXT & ~filters.COMMAND, pa_logic_handler)]},
        fallbacks=[CommandHandler('start', cmd_start)]
    )
    
    tr_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^بناء الصفقة$'), start_trade)],
        states={
            TRADE_SYM: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_sym)],
            TRADE_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_entry)],
            TRADE_STOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_stop)],
            TRADE_CAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_cap)],
        },
        fallbacks=[CommandHandler('start', cmd_start)]
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(pa_conv)
    app.add_handler(tr_conv)
    app.add_handler(CallbackQueryHandler(pa_callback, pattern='^pa_'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))
    
    app.run_polling()

if __name__ == '__main__':
    main()
