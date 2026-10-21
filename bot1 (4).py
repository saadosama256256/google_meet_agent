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
    LOGIN_WAIT_TIMEOUT_SEC,
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


@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not is_allowed(message):
        return
    bot.reply_to(
        message,
        "👋 المساعد جاهز للاتصال بـ Browserless!\n"
        "🔑 /login — لتسجيل الدخول وحفظ الجلسة الدائمة على السيرفر\n"
        "🔴 /record — بدء تسجيل المحاضرة\n"
        "🛑 /stop — إيقاف التسجيل ومغادرة الاجتماع\n"
        "🔄 /rejoin — تحديث الصفحة وإعادة الانضمام\n"
        "📎 أو أرسل ملف `auth.json` مباشرة في المحادثة لاستيراده.",
    )


@bot.message_handler(commands=["login"])
def cmd_login(message):
    if not is_allowed(message):
        return
    minutes = LOGIN_WAIT_TIMEOUT_SEC // 60
    bot.reply_to(
        message,
        "⏳ جاري الاتصال بـ Browserless وتفعيل وضع التخفي (Stealth) وفتح صفحة دخول Google...\n"
        "انتظر ثواني حتى تصلك صورة الصفحة هنا قبل الضغط على Inspect.",
    )

    def notify_page_ready(preview_path, current_url):
        caption = (
            f"🟢 **صفحة تسجيل الدخول جاهزة الآن (المهلة: {minutes} دقائق)!**\n"
            "1️⃣ افتح لوحة **Browserless > Sessions** واضغط على الجلسة (**Inspect**).\n"
            "2️⃣ أدخل البريد الإلكتروني وكلمة المرور وكود التحقق.\n"
            "💡 **حيلة إضافية إذا ظهرت رسالة المتصفح غير الآمن**: افتح موقع `https://stackoverflow.com/users/login` من شريط العنوان أعلى شاشة Inspect واضغط **Log in with Google** وسيقبل الدخول فوراً!\n"
            "3️⃣ لا تغلق المتصفح؛ البوت سيرصد نجاح الدخول ويحفظ الجلسة تلقائياً."
        )
        if preview_path and os.path.exists(preview_path):
            try:
                with open(preview_path, "rb") as photo:
                    bot.send_photo(message.chat.id, photo, caption=caption)
                os.remove(preview_path)
                return
            except Exception:
                pass
        bot.send_message(message.chat.id, caption)

    result = run_browser_command(browser.manual_login, notify_page_ready)
    bot.reply_to(message, result)


@bot.message_handler(content_types=["document"])
def handle_auth_file_upload(message):
    """استقبال ملف auth.json مباشرة عبر تليجرام وحفظه في المسار الدائم"""
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
            bot.reply_to(message, "⚠️ الملف المرفوع لا يحتوي على حقل `cookies` صالح لـ Playwright.")
            return

        with open(AUTH_STATE_PATH, "wb") as f:
            f.write(downloaded)
        if os.path.abspath(AUTH_STATE_PATH) != os.path.abspath("auth.json"):
            shutil.copyfile(AUTH_STATE_PATH, "auth.json")

        # إعادة تهيئة المتصفح في المرة القادمة ليقرأ الملف الجديد
        run_browser_command(browser.disconnect_browser, False)
        bot.reply_to(
            message,
            f"✅ تم استيراد وحفظ ملف الجلسة ({len(parsed['cookies'])} كوكي) بنجاح في `{AUTH_STATE_PATH}`!\n"
            "جرب الآن إرسال رابط اجتماع Google Meet.",
        )
    except Exception as e:
        bot.reply_to(message, f"⚠️ فشل استيراد ملف الجلسة: {e}")


@bot.message_handler(commands=["record"])
def cmd_record(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, run_browser_command(browser.start_recording))


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, run_browser_command(browser.stop_recording))
    bot.reply_to(message, run_browser_command(browser.leave_meeting))


@bot.message_handler(commands=["rejoin"])
def cmd_rejoin(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, run_browser_command(browser.refresh_and_rejoin))


@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("https://meet.google.com/"))
def cmd_join(message):
    if not is_allowed(message):
        return
    bot.reply_to(message, "🔗 جاري الاتصال بالمتصفح والدخول للاجتماع...")

    result = run_browser_command(browser.join_meeting, message.text.strip())

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
    """
    حلقة معالجة أوامر المتصفح في Thread واحد،
    مع إرسال نبضات Keep-Alive دورية كل 15 ثانية أثناء المحاضرات النشطة لمنع انقطاع WebSocket.
    """
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