import json
import os
import shutil
import time
import urllib.parse
from playwright.sync_api import sync_playwright
from config import (
    AUTH_STATE_PATH,
    BROWSERLESS_PROFILE_DIR,
    BROWSERLESS_TIMEOUT_MS,
    BROWSERLESS_WS,
    USE_LAUNCH_ARGS,
)

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},
    "login_in_progress": False,
}

# سكربت إخفاء بصمة الأتمتة (Stealth Init Script) لمنع Google من كشف المتصفح الآلي
STEALTH_INIT_SCRIPT = """
(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = window.chrome || { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['ar-EG', 'ar', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
})();
"""


def _build_ws_candidates():
    """
    بناء قائمة بروابط الاتصال بـ Browserless:
    1. الرابط المحسّن مع معاملات منع كشف الأتمتة، المايك/الكاميرا الافتراضية، ومجلد البروفايل الدائم.
    2. الرابط المزود بمهلة زمنية ممتدة فقط.
    3. الرابط الأساسي النظيف كخيار احتياطي مضمون.
    """
    base_url = BROWSERLESS_WS.strip()
    sep = "&" if "?" in base_url else "?"
    candidates = []

    if USE_LAUNCH_ARGS:
        launch_args = [
            "--window-size=1280,720",
            "--disable-blink-features=AutomationControlled",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--lang=ar,en-US",
        ]
        if BROWSERLESS_PROFILE_DIR:
            launch_args.append(f"--user-data-dir={BROWSERLESS_PROFILE_DIR}")

        launch_payload = {
            "stealth": True,
            "args": launch_args,
        }
        encoded_launch = urllib.parse.quote(json.dumps(launch_payload))
        candidates.append(
            f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}&stealth=true&launch={encoded_launch}"
        )

    if "timeout=" not in base_url:
        candidates.append(f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}")

    candidates.append(base_url)
    return candidates


def _prepare_page(page):
    """
    تهيئة التبويب عبر بروتوكول CDP لإزالة كلمة HeadlessChrome من الـ User-Agent
    وتوحيد بصمة المتصفح مع نظام السيرفر الفعلي (Linux x86_64) لمنع حظر Google.
    """
    try:
        page.set_viewport_size({"width": 1280, "height": 720})
    except Exception:
        pass

    try:
        cdp = state["context"].new_cdp_session(page)
        cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_INIT_SCRIPT})

        current_ua = page.evaluate("navigator.userAgent")
        if "HeadlessChrome/" in current_ua:
            clean_ua = current_ua.replace("HeadlessChrome/", "Chrome/")
            cdp.send(
                "Network.setUserAgentOverride",
                {
                    "userAgent": clean_ua,
                    "acceptLanguage": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
                    "platform": "Linux x86_64",
                },
            )
    except Exception as e:
        print(f"ℹ️ ملاحظة أثناء تهيئة بصمة التبويب: {e}")


def is_google_logged_in(context=None):
    """
    التحقق الموثوق من وجود كوكيز جلسة Google الفعالة (SID / __Secure-1PSID)
    عبر بروتوكول CDP مباشرة، مما يعمل كنبضة اتصال (Keep-Alive) وفحص دقيق في آن واحد.
    """
    ctx = context or state.get("context")
    if not ctx:
        return False
    try:
        cookies = ctx.cookies(
            [
                "https://accounts.google.com",
                "https://meet.google.com",
                "https://myaccount.google.com",
            ]
        )
        cookie_names = {c.get("name") for c in cookies}
        has_sid = "SID" in cookie_names or "__Secure-1PSID" in cookie_names or "__Secure-3PSID" in cookie_names
        has_hsid = "HSID" in cookie_names or "SSID" in cookie_names or "LSID" in cookie_names
        return has_sid and has_hsid
    except Exception:
        return False


def save_session_state():
    """حفظ حالة الجلسة (الكوكيز و LocalStorage) في المسار الدائم /app/data/auth.json"""
    ctx = state.get("context")
    if not ctx:
        return False
    try:
        ctx.storage_state(path=AUTH_STATE_PATH)
        # حفظ نسخة إضافية في المجلد الحالي للتوافق
        if os.path.abspath(AUTH_STATE_PATH) != os.path.abspath("auth.json"):
            shutil.copyfile(AUTH_STATE_PATH, "auth.json")
        print(f"💾 تم حفظ الجلسة بنجاح في المسار الدائم: {AUTH_STATE_PATH}")
        return True
    except Exception as e:
        print(f"⚠️ تعذر حفظ ملف الجلسة auth.json: {e}")
        return False


def _restore_cookies_if_needed(context):
    """
    استعادة الكوكيز المحفوظة من السيرفر إلى السياق الافتراضي (contexts[0])
    في حال أعيد تشغيل حاوية Browserless بدون بروفايل محلي.
    """
    if is_google_logged_in(context):
        print("✅ الجلسة نشطة بالفعل داخل البروفايل الدائم لـ Browserless!")
        return

    auth_file = AUTH_STATE_PATH if os.path.exists(AUTH_STATE_PATH) else ("auth.json" if os.path.exists("auth.json") else None)
    if not auth_file:
        return

    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
            print(f"🔑 تمت استعادة {len(cookies)} كوكي من {auth_file} إلى السياق الافتراضي.")
    except Exception as e:
        print(f"⚠️ فشل استرجاع الكوكيز من {auth_file}: {e}")


def connect_browser():
    """الاتصال بخادم Browserless واستخدام السياق الافتراضي الدائم contexts[0]"""
    disconnect_browser(save_state=False)

    state["playwright"] = sync_playwright().start()
    ws_candidates = _build_ws_candidates()

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        for ws_url in ws_candidates:
            try:
                print(f"⏳ جاري الاتصال بـ Browserless (محاولة {attempt}/{max_attempts})...")
                state["browser"] = state["playwright"].chromium.connect_over_cdp(
                    ws_url, timeout=60000
                )

                # استخدام السياق الافتراضي (contexts[0]) لأنه الوحيد الذي يرث --user-data-dir و DATA_DIR
                if state["browser"].contexts:
                    context = state["browser"].contexts[0]
                    print("📂 تم الربط مع السياق الدائم للمتصفح (browser.contexts[0]).")
                else:
                    context = state["browser"].new_context(
                        viewport={"width": 1280, "height": 720}
                    )

                try:
                    context.add_init_script(STEALTH_INIT_SCRIPT)
                except Exception:
                    pass

                try:
                    context.grant_permissions(
                        ["microphone", "camera", "notifications"],
                        origin="https://meet.google.com",
                    )
                except Exception:
                    pass

                _restore_cookies_if_needed(context)

                state["context"] = context
                print("✅ تم الاتصال بنجاح بسيرفر Browserless!")
                return
            except Exception as e:
                print(f"⚠️ تعذر الاتصال بالرابط المرشح: {e}")

        time.sleep(2)

    raise Exception("❌ فشل الاتصال بـ Browserless بعد عدة محاولات. تأكد من عمل الحاوية وصحة الرابط.")


def disconnect_browser(save_state=True):
    """إغلاق الاتصال بـ Browserless بشكل آمن لحفظ البروفايل على القرص وتحرير الذاكرة"""
    if save_state and state.get("context"):
        save_session_state()

    state["pages"].clear()

    if state.get("browser"):
        try:
            state["browser"].close()
        except Exception:
            pass
        state["browser"] = None
        state["context"] = None

    if state.get("playwright"):
        try:
            state["playwright"].stop()
        except Exception:
            pass
        state["playwright"] = None


def ensure_connection():
    """التأكد من فعالية اتصال WebSocket وإعادة الاتصال تلقائياً عند الحاجة"""
    try:
        if not state["browser"] or not state["browser"].is_connected():
            connect_browser()
        else:
            # إرسال طلب حقيقي عبر CDP للتأكد من عدم انقطاع الجلسة
            _ = state["context"].cookies("https://meet.google.com")
    except Exception:
        connect_browser()


def keep_alive():
    """
    إرسال نبضة حقيقية (CDP Ping) عبر WebSocket لمنع Traefik / Cloudflare / Browserless
    من قطع الاتصال أثناء المحاضرات الطويلة.
    """
    if not state.get("browser") or not state["browser"].is_connected():
        return

    # إذا لم يكن هناك تسجيل دخول جاري ولا محاضرات مفتوحة، لا داعي لإبقاء جلسة فارغة
    if not state["pages"] and not state.get("login_in_progress"):
        return

    try:
        _ = state["context"].cookies("https://meet.google.com")
        for num, page in list(state["pages"].items()):
            try:
                if not page.is_closed():
                    page.evaluate("1")
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ تنبيه Keep-Alive (تم رصد خمول أو انقطاع بالاتصال): {e}")


def get_page(num="1"):
    return state["pages"].get(str(num))


def manual_login():
    """
    فتح صفحة تسجيل دخول Google داخل السيرفر مباشرة لتطابق الـ IP والبصمة 100%،
    مع إرسال نبضات CDP حقيقية كل 5 ثوانٍ وحفظ الجلسة فور رصد كوكيز الدخول.
    """
    state["login_in_progress"] = True
    try:
        ensure_connection()
        context = state["context"]

        # استخدام التبويب المفتوح افتراضياً إن وجد ليظهر فوراً في شاشة Inspect الخاصة بـ Browserless
        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        _prepare_page(page)

        print("🌐 جاري فتح صفحة تسجيل الدخول لحساب Google...")
        page.goto(
            "https://accounts.google.com/ServiceLogin?hl=ar&continue=https://meet.google.com/",
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # إذا كان الحساب مسجلاً بالفعل في البروفايل الدائم
        if is_google_logged_in(context) and "accounts.google.com" not in page.url:
            save_session_state()
            return "✅ الحساب مسجل الدخول بالفعل داخل البروفايل الدائم وتم تحديث الجلسة بنجاح!"

        print("⏰ الشاشة جاهزة. قم بتسجيل الدخول الآن من قائمة Sessions > Inspect في Browserless...")

        login_detected = False
        for i in range(60):  # 60 × 5 ثوانٍ = 5 دقائق
            time.sleep(5)
            try:
                # فحص جميع التبويبات المفتوحة وإرسال نبضة CDP حقيقية لمنع قطع WebSocket
                active_urls = []
                for p in list(context.pages):
                    try:
                        if not p.is_closed():
                            p.evaluate("1")  # نبضة حقيقية عبر الشبكة (تمنع Idle Timeout)
                            active_urls.append(p.url)
                    except Exception:
                        pass

                # فحص كوكيز التوثيق الفعلي من Google
                if is_google_logged_in(context):
                    # التأكد من تخطي شاشات إدخال كلمة المرور والتحقق الثنائي
                    still_on_challenge = any(
                        ("accounts.google.com/v3/signin" in u or "accounts.google.com/signin" in u)
                        for u in active_urls
                    )
                    reached_target = any(
                        (
                            "meet.google.com" in u
                            or "myaccount.google.com" in u
                            or "myactivity.google.com" in u
                            or "google.com" in u and "accounts.google.com" not in u
                        )
                        for u in active_urls
                    )

                    if reached_target or not still_on_challenge:
                        print("🎉 تم رصد كوكيز تسجيل الدخول بنجاح!")
                        save_session_state()
                        login_detected = True
                        break
            except Exception as loop_err:
                print(f"ℹ️ جاري انتظار استكمال الدخول... ({loop_err})")

        # حفظ الجلسة النهائية قبل إغلاق الاتصال المؤقت
        save_session_state()

        if login_detected or is_google_logged_in(context):
            # إغلاق الجلسة بأمان بعد انتهاء الدخول إذا لم تكن هناك محاضرات جارية، لكي يحفظ Chromium البروفايل على القرص
            if not state["pages"]:
                disconnect_browser(save_state=False)
            return (
                "✅ تم تسجيل الدخول وحفظ الجلسة الدائمة بنجاح!\n"
                "🔒 تم ربط الجلسة بـ IP وبصمة السيرفر، ويمكنك الآن إرسال روابط Google Meet مباشرة."
            )
        else:
            return (
                "⚠️ انتهت المهلة (5 دقائق) دون رصد اكتمال تسجيل الدخول.\n"
                "تأكد من ضبط المتغير TIMEOUT=-1 في إعدادات حاوية Browserless على Coolify ثم أعد المحاولة."
            )
    finally:
        state["login_in_progress"] = False


def join_meeting(link, num="1"):
    ensure_connection()
    num = str(num)
    context = state["context"]

    if num in state["pages"]:
        try:
            state["pages"][num].close()
        except Exception:
            pass

    page = context.new_page()
    _prepare_page(page)
    state["pages"][num] = page

    print(f"🔗 [محاضرة {num}] جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    current_url = page.url
    if "accounts.google.com" in current_url:
        try:
            page.screenshot(path="error_screen.png")
        except Exception:
            pass
        state["pages"].pop(num, None)
        raise Exception("⚠️ الحساب غير مسجل الدخول! أرسل الأمر /login لتسجيل الدخول من داخل السيرفر أولاً.")

    # إغلاق النوافذ المنبثقة الخاصة بالتنبيهات أو الأذونات إن ظهرت
    dismiss_selectors = [
        "button:has-text('Dismiss')",
        "button:has-text('تجاهل')",
        "button:has-text('Continue without microphone and camera')",
        "button:has-text('المتابعة بدون ميكروفون وكاميرا')",
        "button:has-text('Got it')",
        "button:has-text('حسناً')",
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

    # إغلاق المايك والكاميرا عبر الاختصارات والأزرار
    try:
        page.keyboard.down("Control")
        page.keyboard.press("d")
        page.keyboard.press("e")
        page.keyboard.up("Control")
    except Exception:
        pass

    join_selector = (
        "button:has-text('Join now'), "
        "button:has-text('Ask to join'), "
        "button:has-text('الانضمام الآن'), "
        "button:has-text('طلب الانضمام'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('Switch here'), "
        "button:has-text('الانضمام من هنا')"
    )

    try:
        join_button = page.locator(join_selector).first
        join_button.wait_for(timeout=25000)
        join_button.click()
        print(f"✅ [محاضرة {num}] تم الضغط على زر الانضمام!")

        page.wait_for_timeout(4000)
        page.screenshot(path="success_screen.png")

        # تحديث الجلسة المحفوظة بعد الدخول الناجح
        save_session_state()
        return "✅ تم الضغط على زر الانضمام وتم الدخول للاجتماع بنجاح!"
    except Exception:
        try:
            page.screenshot(path="error_screen.png")
        except Exception:
            pass
        raise Exception(f"لم يتم العثور على زر الانضمام. (عنوان الصفحة الحالي: {page.title()})")


def start_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة حالياً.")

    more_btn = page.get_by_role("button", name="More options", exact=True)
    if not more_btn.is_visible():
        more_btn = page.locator(
            'button[aria-label="More options"], button[aria-label="خيارات إضافية"]'
        ).first

    more_btn.wait_for(timeout=15000)
    more_btn.click()

    manage_item = page.get_by_role("menuitem", name="Manage recording")
    if not manage_item.is_visible():
        manage_item = page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first

    manage_item.wait_for(timeout=15000)
    manage_item.click()

    try:
        page.click('[aria-label="Start recording"], [aria-label="بدء التسجيل"]', timeout=8000)
    except Exception:
        page.click('[jsname="A0ONe"]', timeout=8000)

    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] بدأ التسجيل!")
    return "✅ بدأ تسجيل المحاضرة بنجاح!"


def stop_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة حالياً.")

    more_btn = page.get_by_role("button", name="More options", exact=True)
    if not more_btn.is_visible():
        more_btn = page.locator(
            'button[aria-label="More options"], button[aria-label="خيارات إضافية"]'
        ).first

    more_btn.wait_for(timeout=15000)
    more_btn.click()

    manage_item = page.get_by_role("menuitem", name="Manage recording")
    if not manage_item.is_visible():
        manage_item = page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first

    manage_item.wait_for(timeout=15000)
    manage_item.click()

    page.click('[jsname="ahMSA"], [aria-label="Stop recording"], [aria-label="إيقاف التسجيل"]', timeout=15000)
    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")
    return "✅ تم إيقاف التسجيل بنجاح!"


def leave_meeting(num="1"):
    ensure_connection()
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة حالياً.")

    try:
        page.click('[aria-label="Leave call"], [aria-label="مغادرة المكالمة"]', timeout=10000)
        page.click('[data-mdc-dialog-action="rbwiRc"]', timeout=5000)
    except Exception:
        pass

    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(num, None)

    # حفظ الجلسة وإغلاق المتصفح إذا لم تعد هناك محاضرات نشطة لتفريغ الرام وحفظ البروفايل
    save_session_state()
    if not state["pages"]:
        disconnect_browser(save_state=False)

    print(f"✅ [محاضرة {num}] تمت المغادرة")
    return "✅ تمت مغادرة الاجتماع وحفظ الجلسة بنجاح!"


def refresh_and_rejoin(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة حالياً.")

    page.reload(wait_until="domcontentloaded", timeout=60000)
    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    return "✅ تم التحديث وإعادة الدخول بنجاح!"
