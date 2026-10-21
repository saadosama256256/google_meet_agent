import os

# إعدادات بوت تليجرام الأساسية
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

# رابط الاتصال بخادم Browserless عبر WebSocket
BROWSERLESS_WS = os.environ.get(
    "BROWSERLESS_WS",
    "wss://browserless.africanhouse.org?token=ZH9MFsE5RgM2KYrz9ELSz5VIOSgYDqJE",
)

# مجلد البيانات الدائم داخل حاوية البوت لحفظ ملف الجلسة (auth.json)
BOT_DATA_DIR = os.environ.get("BOT_DATA_DIR", "/app/data")
os.makedirs(BOT_DATA_DIR, exist_ok=True)
AUTH_STATE_PATH = os.path.join(BOT_DATA_DIR, "auth.json")

# مهلة الجلسة بالملي ثانية (الافتراضي: 3 ساعات = 10800000 مللي ثانية)
BROWSERLESS_TIMEOUT_MS = int(os.environ.get("BROWSERLESS_TIMEOUT_MS", "10800000"))

# مهلة انتظار تسجيل الدخول بالثواني (الافتراضي: 10 دقائق = 600 ثانية لإعطاء وقت كافٍ لكود التحقق)
LOGIN_WAIT_TIMEOUT_SEC = int(os.environ.get("LOGIN_WAIT_TIMEOUT_SEC", "600"))

# الفاصل الزمني لإرسال نبضات إبقاء الاتصال نشطاً (Keep-Alive Heartbeat) بالثواني
KEEPALIVE_INTERVAL_SEC = int(os.environ.get("KEEPALIVE_INTERVAL_SEC", "15"))
