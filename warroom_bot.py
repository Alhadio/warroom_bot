import os
import asyncio
import yfinance as yf
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. إعدادات الرادار ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# قائمة الأسهم التي سيراقبها الرادار آلياً
WATCHLIST = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "SPY", "QQQ", "ONDS"]

# --- 2. محرك جلب البيانات اللحظي ---
async def fetch_radar_data():
    symbols_str = " ".join(WATCHLIST)
    # جلب بيانات يومين بفاصل دقيقة واحدة لضمان دقة التغيير اللحظي
    try:
        data = await asyncio.to_thread(yf.download, tickers=symbols_str, period="2d", interval="1m", group_by='ticker', progress=False)
        results = []
        for ticker in WATCHLIST:
            s_data = data[ticker]
            current_price = s_data['Close'].iloc[-1]
            prev_close = s_data['Close'].iloc[-2]
            change = ((current_price - prev_close) / prev_close) * 100
            
            emoji = "🟢" if change > 0 else "🔴"
            results.append(f"{emoji} **{ticker}**: ${current_price:.2f} ({change:+.2f}%)")
        return "\n".join(results)
    except Exception as e:
        return f"⚠️ عذراً، تعذر جلب بيانات الرادار حالياً: {e}"

# --- 3. لوحة التحكم الرئيسية ---
MAIN_KB = ReplyKeyboardMarkup([
    ['🛰️ الرادار اللحظي'],
    ['المشهد الكلي', 'تقييم خطة أ'],
    ['بناء الصفقة', 'القواعد'],
], resize_keyboard=True)

# --- 4. وظائف البوت ---
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ **WarRoom Radar Pro**\nتم تفعيل الرادار الشامل. يمكنك الآن متابعة الأسعار لحظياً.",
        reply_markup=MAIN_KB, parse_mode='Markdown'
    )

async def handle_radar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("📡 جاري الاتصال بالأقمار الصناعية وجلب الأسعار...")
    radar_content = await fetch_radar_data()
    
    response = (
        f"📊 **رادار الأسعار اللحظي**\n"
        f"🕒 التوقيت: {datetime.now().strftime('%H:%M:%S')}\n"
        f"--- --- --- --- ---\n"
        f"{radar_content}\n"
        f"--- --- --- --- ---\n"
        f"💡 يتم التحديث عند الطلب لضمان سرعة الأداء."
    )
    await status_msg.edit_text(response, parse_mode='Markdown')

async def global_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '🛰️ الرادار اللحظي':
        await handle_radar(update, ctx)
    elif text == 'القواعد':
        await update.message.reply_text("1. الالتزام بالوقف\n2. عدم الدخول وقت الفوضى")
    else:
        await update.message.reply_text("يرجى اختيار أمر من القائمة بالأسفل.")

# --- 5. التشغيل النهائي ---
def main():
    if not BOT_TOKEN:
        print("خطأ: لم يتم العثور على BOT_TOKEN")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.Regex('^🛰️ الرادار اللحظي$'), handle_radar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_handler))
    
    print("🚀 الرادار يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
