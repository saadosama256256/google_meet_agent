#!/bin/bash
set -e

PROFILE_DIR="/app/chrome-profile"
DEBUG_PORT=9223
MODE="${MODE:-run}"   # run (افتراضي) أو login

# ============================================
# 1. تجهيز مجلد Chrome Profile وتنظيف الأقفال
# ============================================
mkdir -p "$PROFILE_DIR"

rm -f "$PROFILE_DIR/SingletonLock"
rm -f "$PROFILE_DIR/SingletonCookie"
rm -f "$PROFILE_DIR/SingletonSocket"

echo "✅ Chrome profile جاهز: $PROFILE_DIR"

# ============================================
# 2. تشغيل الشاشة الافتراضية وخادم noVNC للمشاهدة
# ============================================
echo "🖥️ جاري تجهيز الشاشة الافتراضية والبث الحي..."

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99
sleep 1

fluxbox &
sleep 1

# تشغيل x11vnc بدون كلمة سر محلياً
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 &
sleep 1

# تشغيل noVNC على المنفذ 6080 للمشاهدة من المتصفح مباشرة
websockify --web=/usr/share/novnc/ 6080 localhost:5900 &
sleep 1

echo "🌐 البث الحي متاح عبر: http://<SERVER_IP>:6080/vnc.html"

# ============================================
# 3. تشغيل وضع التسجيل المؤقت (MODE=login)
# ============================================
if [ "$MODE" = "login" ]; then
    echo "🔐 وضع Login مفعّل - افتح الرابط بالمتصفح وسجل دخولك يدوياً"

    google-chrome-stable \
        --user-data-dir="$PROFILE_DIR" \
        --profile-directory="Profile 1" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --window-size=1920,1080 \
        --start-maximized \
        "https://accounts.google.com" &

    tail -f /dev/null

# ============================================
# 4. وضع التشغيل الطبيعي (MODE=run) مع البث الحي
# ============================================
else
    echo "⏳ جاري تشغيل Chrome (بواجهة مرئية للشاشة الافتراضية) مع تفعيل CDP على بورت $DEBUG_PORT ..."

    # تشغيل كروم داخل DISPLAY=:99 ليمكنك رؤيته عبر noVNC
    google-chrome-stable \
        --remote-debugging-port=$DEBUG_PORT \
        --remote-debugging-address=0.0.0.0 \
        --user-data-dir="$PROFILE_DIR" \
        --profile-directory="Profile 1" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --disable-gpu \
        --no-first-run \
        --window-size=1920,1080 \
        --start-maximized \
        --use-fake-ui-for-media-stream &

    CHROME_PID=$!

    echo "⏳ في انتظار جاهزية Chrome..."
    CHROME_READY=false

    for i in $(seq 1 20); do
        if curl -s "http://localhost:$DEBUG_PORT/json/version" > /dev/null 2>&1; then
            echo "✅ Chrome جاهز ومتصل على بورت $DEBUG_PORT"
            CHROME_READY=true
            break
        fi
        sleep 1
    done

    if [ "$CHROME_READY" != "true" ]; then
        echo "❌ Chrome لم يبدأ بشكل صحيح."
        ps aux | grep -i chrome || true
        kill $CHROME_PID 2>/dev/null || true
        exit 1
    fi

    echo "🤖 جاري تشغيل البوت..."
    python3 bot1.py

    kill $CHROME_PID 2>/dev/null || true
fi
