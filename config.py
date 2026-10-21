import os

# 1. إعدادات بوت تليجرام الأساسية
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

try:
    ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))
except ValueError:
    ALLOWED_USER_ID = 0

# 2. رابط الاتصال بخادم Browserless عبر WebSocket
BROWSERLESS_WS = os.environ.get(
    "BROWSERLESS_WS",
    "wss://browserless.africanhouse.org?token=ZH9MFsE5RgM2KYrz9ELSz5VIOSgYDqJE"
)

# 3. مسار البيانات الدائم ومسار ملف auth.json
BOT_DATA_DIR = os.environ.get("BOT_DATA_DIR", "/app/data")

try:
    os.makedirs(BOT_DATA_DIR, exist_ok=True)
except Exception as e:
    print(f"⚠️ تنبيه: تعذر إنشاء مجلد البيانات {BOT_DATA_DIR}: {e}")

AUTH_STATE_PATH = os.path.join(BOT_DATA_DIR, "auth.json")

# 4. مسار البروفايل الدائم داخل حاوية Browserless
BROWSERLESS_PROFILE_DIR = os.environ.get("BROWSERLESS_PROFILE_DIR", "/data/google_profile")

# 5. إعدادات المهلة ونبضات إبقاء الاتصال نشطاً (Keep-Alive)
USE_LAUNCH_ARGS = os.environ.get("USE_LAUNCH_ARGS", "true").lower() == "true"

try:
    BROWSERLESS_TIMEOUT_MS = int(os.environ.get("BROWSERLESS_TIMEOUT_MS", "10800000"))
except ValueError:
    BROWSERLESS_TIMEOUT_MS = 10800000

try:
    KEEPALIVE_INTERVAL_SEC = int(os.environ.get("KEEPALIVE_INTERVAL_SEC", "15"))
except ValueError:
    KEEPALIVE_INTERVAL_SEC = 15
