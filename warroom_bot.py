import yfinance as yf
import pandas as pd
import asyncio
from datetime import datetime

# --- قائمة الرادار (أضف أي عدد من الأسهم هنا) ---
# يمكنك وضع أسهم القياديات، المؤشرات، أو أي سهم تتابعه
WATCHLIST = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "META", "GOOGL", "AMZN", "SPY", "QQQ"]

async def run_radar():
    print(f"🚀 بدء تشغيل الرادار الشامل... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 يراقب حالياً: {len(WATCHLIST)} سهم\n")
    
    while True:
        try:
            # جلب البيانات لكل القائمة دفعة واحدة لتحسين السرعة
            tickers = " ".join(WATCHLIST)
            data = yf.download(tickers, period="2d", interval="1m", group_by='ticker', progress=False)
            
            print(f"\n🔄 تحديث اللحظة: {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'السهم':<8} | {'السعر':<10} | {'التغيير':<8} | {'الحالة الفنية'}")
            print("-" * 55)

            for ticker in WATCHLIST:
                # استخراج بيانات السهم
                s_data = data[ticker]
                current_price = s_data['Close'].iloc[-1]
                prev_close = s_data['Close'].iloc[-2]
                
                # حساب التغيير بالنسبة المئوية
                change = ((current_price - prev_close) / prev_close) * 100
                
                # منطق الرادار للتقييم الآلي (قوة الاتجاه)
                # نستخدم المتوسط المتحرك البسيط لآخر 20 دقيقة كمؤشر لحظي
                sma_20 = s_data['Close'].rolling(window=20).mean().iloc[-1]
                
                if current_price > sma_20 and change > 0:
                    status = "✅ صعود قوي (Momentum)"
                elif current_price < sma_20 and change < 0:
                    status = "🔻 هبوط (Pressure)"
                else:
                    status = "🟡 تذبذب عرضي (Side)"

                color_emoji = "🟢" if change > 0 else "🔴"
                print(f"{ticker:<8} | ${current_price:<9.2f} | {color_emoji} {change:>6.2f}% | {status}")

        except Exception as e:
            print(f"⚠️ تنبيه: حدث خطأ أثناء جلب البيانات: {e}")

        # التوقف لمدة 60 ثانية قبل المسح التالي
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(run_radar())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الرادار.")
