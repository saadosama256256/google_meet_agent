import json
import logging
import os
import queue
import shutil
import threading
import time
import telebot
import uvicorn
from fastapi import FastAPI
import browser
from config import (
    ALLOWED_USER_ID,
    AUTH_STATE_PATH,
    KEEPALIVE_INTERVAL_SEC,
    TELEGRAM_TOKEN,
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
cmd_queue = queue.Queue()


def is_allowed(message):
    return message.from_user.id == ALLOWED_USER_ID


def run_browser_command(func, *args):
    result = queue.Queue()
    cmd_queue.put((func, args, result))
    return result.get()


def _extract_arg(message_text, default=""):
    parts = (message_text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) >= 2 else default


def _extract_lecture_num(message_text, default="1"):
    parts = (message_text or "").strip().split()
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[1]
    return default


def _send_step_result(chat_id, res):
    """إرسال نتيجة خطوات الدخول (صورة + نص) للمستخدم في تليجرام"""
    if isinstance(res, tuple) and len(res) == 2:
        path, caption = res
        if path and os.path.exists(path):
            with open(path, "rb") as photo:
                bot.send_photo(chat_id, photo, caption=caption)
            os.remove(path)
            return
        bot.send_message(chat_id, caption)
    else:
        bot.send_message(chat_id, str(res))


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(
        message,
        "👋 **المساعد جاهز ومتصل بـ Browserless!**\n\n"
        "🔐 **أوامر تسجيل الدخول المباشر من تليجرام (بدون فتح Inspect):**\n"
        "1. `/login` — فتح صفحة دخول Google على السيرفر\n"
        "2. `/email your@gmail.com` — إدخال البريد الإلكتروني\n"
        "3. `/pass your_password` — إدخال كلمة المرور\n"
        "4. `/code 123456` — إدخال كود التحقق النصي (إن طُلب)\n"
        "5. `/save` — حفظ الجلسة بعد الموافقة من الهاتف\n\n"
        "📹 **أوامر المحاضرات (تدعم المحاضرات المتعددة):**\n"
        "• أرسل رابط `https://meet.google.com/...` للانضمام\n"
        "• `/status` — عرض حالة الكوكيز والمحاضرات المفتوحة\n"
        "• `/screen` أو `/screen 2` — لقطة شاشة حية للمحاضرة\n"
        "• `/record` أو `/record 2` — بدء التسجيل\n"
        "• `/stop` أو `/stop 2` — إيقاف التسجيل والمغادرة",
    )


@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, run_browser_command(browser.get_active_meetings_summary))


@bot.message_handler(commands=["screen"])
def cmd_screen(message):
    if not is_allowed(message):
        return
    num = _extract_lecture_num(message.text, default=None)
    res = run_browser_command(browser.capture_screenshot, num)
    if isinstance(res, tuple) and len(res) == 3:
        path, target_num, url = res
        if os.path.exists(path):
            with open(path, "rb") as photo:
                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption=f"📸 لقطة شاشة حية — **{target_num}**\n🔗 {url}",
                )
            os.remove(path)
            return
    bot.reply_to(message, str(res))


@bot.message_handler(commands=["login"])
def cmd_login(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "⏳ جاري فتح صفحة تسجيل دخول Google على السيرفر...")
    res = run_browser_command(browser.start_telegram_login)
    _send_step_result(message.chat.id, res)


@bot.message_handler(commands=["email"])
def cmd_email(message):
    if not is_allowed(message):
        return
    email_text = _extract_arg(message.text)
    if not email_text:
        bot.reply_to(message, "⚠️ اكتب البريد بعد الأمر هكذا:\n`/email your_email@gmail.com`")
        return
    bot.reply_to(message, "⏳ جاري كتابة البريد الإلكتروني والضغط على التالي...")
    res = run_browser_command(browser.submit_login_email, email_text)
    _send_step_result(message.chat.id, res)


@bot.message_handler(commands=["pass"])
def cmd_pass(message):
    if not is_allowed(message):
        return
    pwd_text = _extract_arg(message.text)
    if not pwd_text:
        bot.reply_to(message, "⚠️ اكتب كلمة المرور بعد الأمر هكذا:\n`/pass كلمة_المرور`")
        return
    bot.reply_to(message, "⏳ جاري كتابة كلمة المرور والضغط على التالي...")
    res = run_browser_command(browser.submit_login_password, pwd_text)
    _send_step_result(message.chat.id, res)


@bot.message_handler(commands=["code"])
def cmd_code(message):
    if not is_allowed(message):
        return
    code_text = _extract_arg(message.text)
    if not code_text:
        bot.reply_to(message, "⚠️ اكتب الكود بعد الأمر هكذا:\n`/code 123456`")
        return
    bot.reply_to(message, "⏳ جاري إدخال كود التحقق...")
    res = run_browser_command(browser.submit_login_code, code_text)
    _send_step_result(message.chat.id, res)


@bot.message_handler(commands=["save"])
def cmd_save(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "⏳ جاري فحص الكوكيز وحفظ الجلسة...")
    res = run_browser_command(browser.finish_and_save_login)
    _send_step_result(message.chat.id, res)


@bot.message_handler(content_types=["document"])
def handle_auth_file_upload(message):
    """استقبال ملف auth.json مباشرة عبر تليجرام وحقنه في السياق الأساسي"""
    if not is_allowed(message):
        return
    doc = message.document
    if not doc or not doc.file_name.endswith(".json"):
        return

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        parsed = json.loads(downloaded.decode("utf-8"))
        if "cookies" not in parsed:
            bot.reply_to(message, "⚠️ الملف المرفوع لا يحتوي على حقل `cookies` صالح.")
            return

        with open(AUTH_STATE_PATH, "wb") as f:
            f.write(downloaded)
        if os.path.abspath(AUTH_STATE_PATH) != os.path.abspath("auth.json"):
            shutil.copyfile(AUTH_STATE_PATH, "auth.json")

        run_browser_command(browser.disconnect_browser, False)
        bot.reply_to(
            message,
            f"✅ تم استيراد وحفظ ملف الجلسة ({len(parsed['cookies'])} كوكي) بنجاح في `{AUTH_STATE_PATH}`!\n"
            "سيتم حقنها مباشرة في السياق الأساسي (`contexts[0]`). جرب الآن إرسال رابط اجتماع Google Meet.",
        )
    except Exception as e:
        bot.reply_to(message, f"⚠️ فشل استيراد ملف الجلسة: {e}")


@bot.message_handler(commands=["record"])
def cmd_record(message):
    if not is_allowed(message):
        return
    num = _extract_lecture_num(message.text, default="1")
    bot.reply_to(message, run_browser_command(browser.start_recording, num))


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    if not is_allowed(message):
        return
    num = _extract_lecture_num(message.text, default="1")
    bot.reply_to(message, run_browser_command(browser.stop_recording, num))
    bot.reply_to(message, run_browser_command(browser.leave_meeting, num))


@bot.message_handler(commands=["leave"])
def cmd_leave(message):
    if not is_allowed(message):
        return
    num = _extract_lecture_num(message.text, default="1")
    bot.reply_to(message, run_browser_command(browser.leave_meeting, num))


@bot.message_handler(commands=["rejoin"])
def cmd_rejoin(message):
    if not is_allowed(message):
        return
    num = _extract_lecture_num(message.text, default="1")
    bot.reply_to(message, run_browser_command(browser.refresh_and_rejoin, num))


@bot.message_handler(func=lambda msg: msg.text and "https://meet.google.com/" in msg.text)
def cmd_join(message):
    if not is_allowed(message):
        return
    parts = message.text.strip().split()
    num = None
    link = None
    for part in parts:
        if part.startswith("https://meet.google.com/"):
            link = part
        elif part.isdigit():
            num = part

    if not link:
        return

    bot.reply_to(message, "🔗 جاري الدخول للاجتماع عبر السياق الأساسي...")

    result = run_browser_command(browser.join_meeting, link, num)

    if "⚠️" in result or "فشل" in result:
        if os.path.exists("error_screen.png"):
            with open("error_screen.png", "rb") as photo:
                bot.send_photo(message.chat.id, photo, caption="📸 لقطة شاشة للمشكلة الحالية:")
            os.remove("error_screen.png")

    if "✅" in result and os.path.exists("success_screen.png"):
        with open("success_screen.png", "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption="📸 تم الدخول للاجتماع بنجاح:")
        os.remove("success_screen.png")

    bot.reply_to(message, result)


def browser_loop():
    while True:
        try:
            func, args, result_queue = cmd_queue.get(timeout=KEEPALIVE_INTERVAL_SEC)
        except queue.Empty:
            try:
                browser.keep_alive()
            except Exception as e:
                logging.warning(f"Keep-alive warning: {e}")
            continue

        try:
            res = func(*args)
            result_queue.put(res if res else "✅ تم الإجراء!")
        except Exception as e:
            logging.error(f"Browser command error: {e}")
            result_queue.put(f"⚠️ حدث خطأ: {e}")


def run_telebot():
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            logging.error(f"Telegram polling error: {e}")
            time.sleep(5)


app = FastAPI()


@app.get("/")
def health_check():
    return {
        "status": "Running smoothly!",
        "active_meetings": list(browser.state["pages"].keys()),
        "browser_connected": bool(
            browser.state["browser"] and browser.state["browser"].is_connected()
        ),
    }


if __name__ == "__main__":
    threading.Thread(target=browser_loop, daemon=True).start()
    threading.Thread(target=run_telebot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")
