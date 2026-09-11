#!/bin/bash
set -e

PROFILE_DIR="/app/chrome-profile"
DEBUG_PORT=9223
MODE="${MODE:-run}"   # run (افتراضي) أو login

# ============================================
# تجهيز Chrome Profile
# ============================================
mkdir -p "$PROFILE_DIR"

# Chrome يترك أحيانًا ملفات Lock قديمة بعد توقف
# الـ container أو Chrome بشكل غير نظيف.
# نحذف ملفات القفل فقط، ولا نحذف بيانات البروفايل.
rm -f "$PROFILE_DIR/SingletonLock"
rm -f "$PROFILE_DIR/SingletonCookie"
rm -f "$PROFILE_DIR/SingletonSocket"

echo "✅ Chrome profile جاهز: $PROFILE_DIR"


if [ "$MODE" = "login" ]; then
    # ============================================
    # وضع الـ Login المؤقت:
    # شاشة افتراضية + VNC + Chrome بواجهة رسومية
    # ============================================

    echo "🔐 وضع Login مؤقت - هيفضل شغال لحد ما توقف الـ container يدويًا"

    Xvfb :99 -screen 0 1280x800x16 -nolisten tcp &
    sleep 1

    fluxbox &
    sleep 1

    # كلمة سر VNC من متغير البيئة VNC_PASSWORD
    x11vnc \
        -display :99 \
        -passwd "${VNC_PASSWORD:-changeme}" \
        -forever \
        -shared \
        -rfbport 5900 &

    export DISPLAY=:99

    echo "🌐 بنفتح Chrome (headed) على البروفايل..."
    echo "🔌 اتصل بـ VNC على 127.0.0.1:5900 عن طريق SSH tunnel"

    google-chrome-stable \
        --user-data-dir="$PROFILE_DIR" \
        --profile-directory="Profile 1" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --window-size=1280,800 \
        --start-maximized \
        "https://accounts.google.com" &

    CHROME_PID=$!

    echo "✅ Chrome بدأ. PID: $CHROME_PID"
    echo "✅ جاهز. اتصل بـ VNC وسجّل دخول Google."
    echo "⚠️ بعد انتهاء Login، أوقف الـ container ثم شغّل MODE=run."

    # نسيب الـ container شغال لحد ما توقفه إنت يدويًا
    tail -f /dev/null

else
    # ============================================
    # وضع التشغيل العادي:
    # Chrome Headless + البوت
    # ============================================

    echo "⏳ بنشغّل Chrome (headless) على بورت CDP $DEBUG_PORT ..."

    google-chrome-stable \
        --headless=new \
        --remote-debugging-port=$DEBUG_PORT \
        --remote-debugging-address=0.0.0.0 \
        --user-data-dir="$PROFILE_DIR" \
        --profile-directory="Profile 1" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --disable-gpu \
        --disable-extensions \
        --disable-background-networking \
        --disable-default-apps \
        --disable-sync \
        --no-first-run \
        --window-size=1280,720 \
        --use-fake-ui-for-media-stream \
        --mute-audio &

    CHROME_PID=$!

    echo "⏳ بننتظر Chrome يجهز..."

    CHROME_READY=false

    for i in $(seq 1 20); do
        if curl -s "http://localhost:$DEBUG_PORT/json/version" > /dev/null 2>&1; then
            echo "✅ Chrome جاهز على بورت $DEBUG_PORT"
            CHROME_READY=true
            break
        fi

        sleep 1
    done

    if [ "$CHROME_READY" != "true" ]; then
        echo "❌ Chrome لم يبدأ بشكل صحيح."
        echo "📋 آخر حالة للـ Chrome:"
        ps aux | grep -i chrome || true

        kill $CHROME_PID 2>/dev/null || true
        exit 1
    fi

    echo "✅ بندي البوت..."
    python3 bot1.py

    kill $CHROME_PID 2>/dev/null || true
fi
