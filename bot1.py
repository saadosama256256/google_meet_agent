import telebot
import threading
import queue
import time
import logging
from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
import browser

from fastapi import FastAPI
import uvicorn

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
cmd_queue = queue.Queue()

def is_allowed(message):
    if message.from_user.id != ALLOWED_USER_ID:
        logging.warning(f"محاولة وصول غير مصرح بها من ID: {message.from_user.id}")
        return False
    return True

def run_browser_command(func, *args):
    result = queue.Queue()
    cmd_queue.put((func, args, result))
    return result.get()

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(message,
        "👋 المساعد جاهز متصل بـ Browserless السحابي!\n\n"
        "الأوامر المتاحة:\n"
        "🔗 أرسل رابط المحاضرة للدخول مباشرة\n"
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
    
    bot.reply_to(message, "🏃 جاري مغادرة الاجتماع...")
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
    bot.reply_to(message, "🔗 جاري الدخول للاجتماع عبر Browserless...")
    result = run_browser_command(browser.join_meeting, link)
    bot.reply_to(message, result)

def browser_loop():
    try:
        logging.info("🌐 جاري الاتصال بمتصفح Browserless...")
        browser.connect_browser()
    except Exception as e:
        logging.error(f"❌ فشل الاتصال بالمتصفح: {e}")

    while True:
        func, args, result_queue = cmd_queue.get()
        try:
            res = func(*args)
            result_queue.put(res if res else "✅ تم الإجراء بنجاح!")
        except Exception as e:
            logging.error(f"⚠️ خطأ أثناء تنفيذ أمر المتصفح: {e}")
            result_queue.put(f"⚠️ حدث خطأ: {e}")

def run_telebot():
    while True:
        try:
            logging.info("🤖 جاري بدء استماع تليجرام (infinity_polling)...")
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            logging.error(f"⚠️ انقطع اتصال تليجرام: {e}")
            time.sleep(5)

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "The bot is connected to Browserless and running smoothly!"}

if __name__ == "__main__":
    t_browser = threading.Thread(target=browser_loop, daemon=True)
    t_browser.start()

    t_bot = threading.Thread(target=run_telebot, daemon=True)
    t_bot.start()

    logging.info("⚡ جاري تشغيل خادم الويب على المنفذ 7860...")
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")
