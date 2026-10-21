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
# اربط المسار /app/data بـ Persistent Volume في Coolify لكي لا يُحذف عند إعادة تشغيل البوت
BOT_DATA_DIR = os.environ.get("BOT_DATA_DIR", "/app/data")
os.makedirs(BOT_DATA_DIR, exist_ok=True)
AUTH_STATE_PATH = os.path.join(BOT_DATA_DIR, "auth.json")

# بصمة متصفح قياسية ثابتة (Linux x86_64 بدون كلمة HeadlessChrome) لتوحيد البصمة في جميع الجلسات
DEFAULT_USER_AGENT = os.environ.get(
    "DEFAULT_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

# مهلة الجلسة بالملي ثانية (الافتراضي: 3 ساعات = 10800000 مللي ثانية لمنع الإغلاق بعد 30 ثانية)
BROWSERLESS_TIMEOUT_MS = int(os.environ.get("BROWSERLESS_TIMEOUT_MS", "10800000"))

# الفاصل الزمني لإرسال نبضات إبقاء الاتصال نشطاً (Keep-Alive Heartbeat) بالثواني
KEEPALIVE_INTERVAL_SEC = int(os.environ.get("KEEPALIVE_INTERVAL_SEC", "15"))