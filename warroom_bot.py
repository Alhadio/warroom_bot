import os
import asyncio
import yfinance as yf
import pandas as pd
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. الإعدادات ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# قائمة الأسهم للمراقبة اللحظية
WATCHLIST = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "SPY", "QQQ", "ONDS"]

# --- 2. محرك الرادار مع نظام الحماية ---
async def fetch_radar_data():
    symbols_str = " ".join(WATCHLIST)
    try:
        # جلب البيانات بشكل آمن
        data = await asyncio.to_thread(yf.download, tickers=symbols_str, period="5d", interval="1m", group_by='ticker', progress=False)
        
        if data.empty:
            return "⚠️ لا توجد بيانات متاحة حالياً من المصدر."

        results = []
        for ticker in WATCHLIST:
            try:
                # التأكد من وجود بيانات للسهم قبل محاولة قراءتها
                s_data = data[ticker].dropna(subset=['Close'])
                if len(s_data) < 2:
                    results.append(f"⚪ **{ticker}**: بيانات غير كافية حالياً")
                    continue
                
                current_price = s_data['Close'].iloc[-1]
                prev_close = s_data['Close'].iloc[-2]
                change = ((current_price - prev_close) / prev_close) * 100
                
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                results.append(f"{emoji} **{ticker}**: ${current_price:.2f} ({change:+.2f}%)")
            except Exception:
                results.append(f"⚠️ **{ticker}**: خطأ في قراءة البيانات")
                
        return "\n".join(results)
    except Exception as e:
        return f"❌ خطأ تقني في المحرك: {str(e)}"

# --- 3. لوحة التحكم ---
MAIN_KB = ReplyKeyboardMarkup([
    ['🛰️ الرادار اللحظي'],
    ['المشهد الكلي', 'تقييم خطة أ'],
    ['بناء الصفقة', 'القواعد'],
], resize_keyboard=True)

# --- 4. معالجة الأوامر ---
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ **WarRoom Radar Pro**\nتم إصلاح المحرك ونظام الحماية يعمل الآن.",
        reply_markup=MAIN_KB, parse_mode='Markdown'
    )

async def handle_radar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📡 جاري فحص الرادار الشامل...")
    radar_content = await fetch_radar_data()
    
    response = (
        f"📊 **رادار الأسعار اللحظي** 📈\n"
        f"🕒 التوقيت: {datetime.now().strftime('%H:%M:%S')}\n"
        f"--- --- --- --- ---\n"
        f"{radar_content}\n"
        f"--- --- --- --- ---\n"
        f"💡 تم التحديث مع تفعيل نظام الحماية الذكي."
    )
    await status_msg.edit_text(response, parse_mode='Markdown')

async def global_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == 'القواعد':
        await update.message.reply_text("⚖️ **قواعد الحرب:**\n1. الالتزام بالوقف مقدس.\n2. لا تداول بدون خطة واضحة.")
    elif text == 'المشهد الكلي':
        await update.message.reply_text("🔍 سيتم تفعيل هذه الميزة في التحديث القادم.")
    else:
        await update.message.reply_text("يرجى اختيار أمر من القائمة بالأسفل 👇")

# --- 5. التشغيل ---
def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN variable not found.")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.Regex('^🛰️ الرادار اللحظي$'), handle_radar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_handler))
    
    print("✅ البوت المصلح يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
