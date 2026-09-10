#!/bin/bash
set -e

PROFILE_DIR="/app/chrome-profile"
DEBUG_PORT=9223
MODE="${MODE:-run}"   # run (افتراضي) أو login

if [ "$MODE" = "login" ]; then
    # ============================================
    # وضع الـ Login المؤقت: بنشغّل شاشة افتراضية + VNC
    # عشان تقدر تدخل من جهازك، تعمل Google login، وتحل أي كود تحقق
    # ============================================
    echo "🔐 وضع Login مؤقت - هيفضل شغال لحد ما توقف الـ container يدويًا"

    Xvfb :99 -screen 0 1280x800x16 -nolisten tcp &
    sleep 1

    fluxbox &
    sleep 1

    # كلمة سر VNC بتتحدد من متغير بيئة VNC_PASSWORD (شوف docker-compose.yml)
    x11vnc -display :99 -passwd "${VNC_PASSWORD:-changeme}" -forever -shared -rfbport 5900 &

    export DISPLAY=:99
    echo "🌐 بنفتح Chrome (headed) على البروفايل... اتصل بـ VNC على بورت 5900"

    google-chrome-stable \
        --user-data-dir="$PROFILE_DIR" \
        --profile-directory="Profile 1" \
        --no-sandbox \
        --disable-dev-shm-usage \
        --window-size=1280,800 \
        --start-maximized \
        "https://accounts.google.com" &

    echo "✅ جاهز. اتصل بـ VNC (127.0.0.1:5900 عن طريق SSH tunnel) وسجّل دخول."
    echo "⚠️ لما تخلص Login، وقف الـ container ده وشغّل الوضع العادي (MODE=run)."

    # نسيب الـ container شغال لحد ما توقفه إنت يدويًا
    tail -f /dev/null

else
    # ============================================
    # وضع التشغيل العادي: Chrome headless + البوت
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
    for i in $(seq 1 20); do
        if curl -s "http://localhost:$DEBUG_PORT/json/version" > /dev/null 2>&1; then
            echo "✅ Chrome جاهز على بورت $DEBUG_PORT"
            break
        fi
        sleep 1
    done

    echo "✅ بندي البوت..."
    python3 bot1.py

    kill $CHROME_PID 2>/dev/null || true
fi
