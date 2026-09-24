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

# قائمة المحاضرات وروابطها الثابتة
LECTURES_MAP = {
    "1": ("تحليل البيانات", "https://meet.google.com/nsn-qdqi-azh"),
    "2": ("شبكات", "https://meet.google.com/zaz-wvjk-sfb"),
    "3": ("المحاضرة الثالثة", "https://meet.google.com/fpo-umkb-nxf"),
}

def is_allowed(message):
    return message.from_user.id == ALLOWED_USER_ID

def run_browser_command(func, *args):
    result = queue.Queue()
    cmd_queue.put((func, args, result))
    return result.get()

# ===== الأوامر =====

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(message,
        "👋 البوت جاهز!\n\n"
        "للدخول، اكتب رقم المحاضرة فقط:\n"
        "1️⃣ أرسل 1 أو (الأولى) ⬅️ تحليل البيانات\n"
        "2️⃣ أرسل 2 أو (الثانية) ⬅️ شبكات\n"
        "3️⃣ أرسل 3 أو (الثالثة) ⬅️ المحاضرة الثالثة\n\n"
        "أو أرسل أي رابط Google Meet مباشرة.\n\n"
        "أوامر التحكم:\n"
        "/record — بدء التسجيل\n"
        "/stop — إيقاف ومغادرة\n"
        "/refresh — تحديث الصفحة"
    )

@bot.message_handler(commands=['record'])
def cmd_record(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🔴 جاري بدء التسجيل...")
    result = run_browser_command(browser.start_recording, "1")
    bot.reply_to(message, result)

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🛑 جاري إيقاف التسجيل ومغادرة الاجتماع...")
    run_browser_command(browser.stop_recording, "1")
    result = run_browser_command(browser.leave_meeting, "1")
    bot.reply_to(message, result)

@bot.message_handler(commands=['refresh'])
def cmd_refresh(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🔄 جاري التحديث...")
    result = run_browser_command(browser.refresh_and_rejoin, "1")
    bot.reply_to(message, result)

# استقبال رقم المحاضرة أو اسمها (1، الأولى، ادخل الاولى...)
@bot.message_handler(func=lambda msg: msg.text and any(k in msg.text for k in ["1", "2", "3", "الأولى", "الاولى", "الثانية", "التانية", "الثالثة", "التالتة"]))
def cmd_join_by_alias(message):
    if not is_allowed(message):
        return

    text = message.text.strip()
    target_key = None

    if "1" in text or "الاولى" in text or "الأولى" in text:
        target_key = "1"
    elif "2" in text or "الثانية" in text or "التانية" in text:
        target_key = "2"
    elif "3" in text or "الثالثة" in text or "التالتة" in text:
        target_key = "3"

    if target_key:
        name, link = LECTURES_MAP[target_key]
        bot.reply_to(message, f"🔗 جاري الدخول إلى محاضرة ({name})...")
        result = run_browser_command(browser.join_meeting, "1", link)
        bot.reply_to(message, result)

# استقبال الروابط المباشرة في حال وجود رابط خارجي
@bot.message_handler(func=lambda msg: msg.text and msg.text.strip().startswith("https://meet.google.com/"))
def cmd_join_direct(message):
    if not is_allowed(message):
        return
    link = message.text.strip()
    bot.reply_to(message, "🔗 جاري الدخول للرابط...")
    result = run_browser_command(browser.join_meeting, "1", link)
    bot.reply_to(message, result)

# ===== الـ Loops والخادم =====
def browser_loop():
    try:
        browser.connect_browser()
    except Exception as e:
        logging.error(f"❌ فشل الاتصال بالمتصفح: {e}")

    while True:
        func, args, result_queue = cmd_queue.get()
        try:
            res = func(*args)
            result_queue.put(res if res else "✅ تم بنجاح!")
        except Exception as e:
            logging.error(f"⚠️ خطأ بالمتصفح: {e}")
            result_queue.put(f"⚠️ خطأ: {e}")

def run_telebot():
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            time.sleep(4)

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "running"}

if __name__ == "__main__":
    threading.Thread(target=browser_loop, daemon=True).start()
    threading.Thread(target=run_telebot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")
