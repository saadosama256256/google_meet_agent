import telebot
import threading
import queue
from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
import browser

# استيراد مكتبات الويب الخاصة بتثبيت بيئة Hugging Face Spaces
from fastapi import FastAPI
import uvicorn

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# قناة التواصل بين البوت و Playwright
cmd_queue = queue.Queue()

def is_allowed(message):
    return message.from_user.id == ALLOWED_USER_ID

# ===== إرسال أمر وانتظار النتيجة =====
def run_browser_command(func, *args):
    result = queue.Queue()
    cmd_queue.put((func, args, result))
    return result.get()  # انتظار النتيجة

# ===== الأوامر =====

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(message,
        "👋 المساعد جاهز!\n\n"
        "الأوامر المتاحة:\n"
        "🔗 أرسل رابط المحاضرة للدخول\n"
        "/record — بدء التسجيل\n"
        "/stop — إيقاف التسجيل والمغادرة\n"
        "/refresh — تحديث عند التجمّد"
    )

@bot.message_handler(commands=['record'])
def cmd_record(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🔴 جاري بدء التسجيل...")
    result = run_browser_command(browser.start_recording)
    bot.reply_to(message, result)

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🛑 جاري إيقاف التسجيل...")
    result = run_browser_command(browser.stop_recording)
    bot.reply_to(message, result)
    result2 = run_browser_command(browser.leave_meeting)
    bot.reply_to(message, result2)

@bot.message_handler(commands=['refresh'])
def cmd_refresh(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🔄 جاري التحديث...")
    result = run_browser_command(browser.refresh_and_rejoin)
    bot.reply_to(message, result)

@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("https://meet.google.com/"))
def cmd_join(message):
    if not is_allowed(message):
        return
    link = message.text.strip()
    bot.reply_to(message, "🔗 جاري الدخول للاجتماع...")
    result = run_browser_command(browser.join_meeting, link)
    bot.reply_to(message, result)

# ===== الـ Loop الرئيسي لـ Playwright =====
def browser_loop():
    browser.connect_browser()
    while True:
        func, args, result = cmd_queue.get()
        try:
            func(*args)
            result.put("✅ تم بنجاح!")
        except Exception as e:
            result.put(f"⚠️ خطأ: {e}")

# ===== إعداد خادم الويب الوهمي لإرضاء منصة Hugging Face =====
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "The bot and browser are running perfectly in the background!"}

# ===== التشغيل النهائي وتنظيم الـ Threads =====
if __name__ == "__main__":
    # 1. تشغيل خيط المتصفح (Playwright Loop)
    t_browser = threading.Thread(target=browser_loop, daemon=True)
    t_browser.start()

    # 2. تشغيل خيط البوت (Telegram Polling) في الخلفية
    print("🤖 جاري تشغيل بوت تليجرام...")
    t_bot = threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True)
    t_bot.start()

    # 3. تشغيل خادم الويب في الـ Main Thread (الخيط الأساسي) لمنع إغلاق الحاوية
    print("🌐 جاري تشغيل خادم الويب على المنفذ الإجباري 7860...")
    uvicorn.run(app, host="0.0.0.0", port=7860)
