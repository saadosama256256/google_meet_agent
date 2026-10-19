import telebot
import threading
import queue
import time
import logging
import os
from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
import browser
from fastapi import FastAPI
import uvicorn

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
cmd_queue = queue.Queue()

def is_allowed(message):
    return message.from_user.id == ALLOWED_USER_ID

def run_browser_command(func, *args):
    result = queue.Queue()
    cmd_queue.put((func, args, result))
    return result.get()

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_allowed(message): return
    bot.reply_to(message, "👋 المساعد جاهز متصل بـ Browserless!\n🔑 /login — لتسجيل الدخول\n🔴 /record — بدء التسجيل\n🛑 /stop — إيقاف ومغادرة")

@bot.message_handler(commands=['login'])
def cmd_login(message):
    if not is_allowed(message): return
    bot.reply_to(message, "🌐 تم فتح المتصفح! اذهب فوراً إلى لوحة Browserless > **Sessions** واضغط **Inspect**. أمامك 5 دقائق لإنهاء الدخول.")
    result = run_browser_command(browser.manual_login)
    bot.reply_to(message, result)

@bot.message_handler(commands=['record'])
def cmd_record(message):
    if not is_allowed(message): return
    bot.reply_to(message, run_browser_command(browser.start_recording))

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    if not is_allowed(message): return
    bot.reply_to(message, run_browser_command(browser.stop_recording))
    bot.reply_to(message, run_browser_command(browser.leave_meeting))

@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("https://meet.google.com/"))
def cmd_join(message):
    if not is_allowed(message): return
    bot.reply_to(message, "🔗 جاري الدخول للاجتماع...")
    
    result = run_browser_command(browser.join_meeting, message.text.strip())
    
    if "⚠️" in result or "فشل" in result:
        if os.path.exists("error_screen.png"):
            with open("error_screen.png", "rb") as photo:
                bot.send_photo(message.chat.id, photo, caption="📸 المشكلة الحالية:")
            os.remove("error_screen.png")
            
    if "✅" in result and os.path.exists("success_screen.png"):
        with open("success_screen.png", "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption="📸 تم الدخول بنجاح:")
        os.remove("success_screen.png")

    bot.reply_to(message, result)

def browser_loop():
    try: browser.connect_browser()
    except: pass
    while True:
        func, args, result_queue = cmd_queue.get()
        try:
            res = func(*args)
            result_queue.put(res if res else "✅ تم الإجراء!")
        except Exception as e:
            result_queue.put(f"⚠️ حدث خطأ: {e}")

def run_telebot():
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except: time.sleep(5)

app = FastAPI()
@app.get("/")
def health_check(): return {"status": "Running smoothly!"}

if __name__ == "__main__":
    threading.Thread(target=browser_loop, daemon=True).start()
    threading.Thread(target=run_telebot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")
