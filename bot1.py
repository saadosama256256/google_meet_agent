import telebot
from telebot import types
import threading
import queue
import time
import logging
import re
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

def get_lecture_keyboard(target_id: str):
    """إنشاء أزرار تفاعلية للتحكم في جلسة معينة بمفردها"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    rec_btn = types.InlineKeyboardButton("🔴 بدء التسجيل", callback_data=f"rec_{target_id}")
    stop_btn = types.InlineKeyboardButton("🛑 مغادرة وإيقاف", callback_data=f"stop_{target_id}")
    refresh_btn = types.InlineKeyboardButton("🔄 تحديث", callback_data=f"ref_{target_id}")
    kb.add(rec_btn, stop_btn)
    kb.add(refresh_btn)
    return kb

# ===== الأوامر العامة =====

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(message,
        "👋 البوت جاهز لإدارة حتى 3 محاضرات متزامنة!\n\n"
        "للدخول، اكتب رقم المحاضرة فقط:\n"
        "1️⃣ أرسل 1 أو (الأولى) ⬅️ تحليل البيانات\n"
        "2️⃣ أرسل 2 أو (الثانية) ⬅️ شبكات\n"
        "3️⃣ أرسل 3 أو (الثالثة) ⬅️ المحاضرة الثالثة\n\n"
        "أو أرسل أي رابط Google Meet جديد مباشرة.\n\n"
        "أوامر التحكم اليدوية:\n"
        "/record [الرقم] — بدء التسجيل (مثال: /record 1)\n"
        "/stop [الرقم] — إيقاف ومغادرة (مثال: /stop 2)\n"
        "/list — عرض المحاضرات المفتوحة حالياً"
    )

@bot.message_handler(commands=['list'])
def cmd_list(message):
    if not is_allowed(message):
        return
    active = run_browser_command(browser.list_open_meetings)
    if not active:
        bot.reply_to(message, "📭 لا توجد محاضرات مفتوحة حالياً.")
        return
    bot.reply_to(message, f"🟢 المحاضرات النشطة حالياً: {', '.join(active)}")

@bot.message_handler(commands=['record'])
def cmd_record(message):
    if not is_allowed(message):
        return
    parts = message.text.split()
    target_id = parts[1] if len(parts) > 1 else "1"
    bot.reply_to(message, f"🔴 جاري بدء التسجيل للمحاضرة {target_id}...")
    result = run_browser_command(browser.start_recording, target_id)
    bot.reply_to(message, result)

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    if not is_allowed(message):
        return
    parts = message.text.split()
    target_id = parts[1] if len(parts) > 1 else "1"
    bot.reply_to(message, f"🛑 جاري إيقاف المحاضرة {target_id} والمغادرة...")
    run_browser_command(browser.stop_recording, target_id)
    result = run_browser_command(browser.leave_meeting, target_id)
    bot.reply_to(message, result)

@bot.message_handler(commands=['refresh'])
def cmd_refresh(message):
    if not is_allowed(message):
        return
    parts = message.text.split()
    target_id = parts[1] if len(parts) > 1 else "1"
    bot.reply_to(message, f"🔄 جاري تحديث المحاضرة {target_id}...")
    result = run_browser_command(browser.refresh_and_rejoin, target_id)
    bot.reply_to(message, result)

# ===== معالجة الأزرار التفاعلية (Inline Callbacks) =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.from_user.id != ALLOWED_USER_ID:
        return

    data = call.data
    action, target_id = data.split("_", 1)

    if action == "rec":
        bot.answer_callback_query(call.id, "جاري بدء التسجيل...")
        res = run_browser_command(browser.start_recording, target_id)
        bot.send_message(call.message.chat.id, f"[{target_id}] {res}")

    elif action == "stop":
        bot.answer_callback_query(call.id, "جاري الإيقاف والمغادرة...")
        run_browser_command(browser.stop_recording, target_id)
        res = run_browser_command(browser.leave_meeting, target_id)
        bot.send_message(call.message.chat.id, f"[{target_id}] {res}")

    elif action == "ref":
        bot.answer_callback_query(call.id, "جاري التحديث...")
        res = run_browser_command(browser.refresh_and_rejoin, target_id)
        bot.send_message(call.message.chat.id, f"[{target_id}] {res}")

# ===== استقبال أرقام وأسماء المحاضرات الثابتة =====
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
        bot.reply_to(message, f"🔗 جاري الانضمام إلى محاضرة ({name})...")
        # نمرر target_key كمعرف مستقل لكل محاضرة (1، 2، 3)
        result = run_browser_command(browser.join_meeting, target_key, link)
        bot.reply_to(message, f"✅ تم الانضمام إلى ({name})!\nتحكم بالجلسة من هنا:", reply_markup=get_lecture_keyboard(target_key))

# ===== استقبال أي رابط خارجي فوري =====
@bot.message_handler(func=lambda msg: msg.text and ("meet.google.com/" in msg.text))
def cmd_join_direct(message):
    if not is_allowed(message):
        return
    link = message.text.strip()
    # استخراج كود الاجتماع ليكون معرفاً للجلسة
    match = re.search(r"([a-z]{3}-[a-z]{4}-[a-z]{3})", link)
    session_id = match.group(1) if match else "temp"
    
    bot.reply_to(message, f"🔗 جاري الانضمام إلى الرابط (جلسة: {session_id})...")
    result = run_browser_command(browser.join_meeting, session_id, link)
    bot.reply_to(message, f"✅ تم الدخول للاجتماع!\nتحكم بالجلسة من هنا:", reply_markup=get_lecture_keyboard(session_id))

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
