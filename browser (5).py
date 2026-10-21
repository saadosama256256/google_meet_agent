import os
import shutil
import time
from playwright.sync_api import sync_playwright
from config import (
    AUTH_STATE_PATH,
    BROWSERLESS_TIMEOUT_MS,
    BROWSERLESS_WS,
    DEFAULT_USER_AGENT,
)

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},
    "login_in_progress": False,
}

# سكربت إخفاء بصمة الأتمتة (يحقن عبر Playwright دون فتح جلسة CDP إضافية تتعارض مع شاشة Inspect)
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
    إضافة معامل timeout فقط إلى رابط Browserless الأساسي لمنع الإغلاق بعد 30 ثانية،
    دون تمرير معاملات launch التي قد تفتح تبويبات فارغة أو تتعارض مع صلاحيات المجلدات في الحاوية.
    """
    base_url = BROWSERLESS_WS.strip()
    sep = "&" if "?" in base_url else "?"
    candidates = []

    if "timeout=" not in base_url:
        candidates.append(f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}")

    candidates.append(base_url)
    return candidates


def _get_existing_auth_file():
    """البحث عن ملف الجلسة المحفوظ سواء في المسار الدائم /app/data/auth.json أو المجلد الحالي"""
    if os.path.exists(AUTH_STATE_PATH) and os.path.getsize(AUTH_STATE_PATH) > 10:
        return AUTH_STATE_PATH
    if os.path.exists("auth.json") and os.path.getsize("auth.json") > 10:
        return "auth.json"
    return None


def _close_blank_tabs(keep_page=None):
    """
    إغلاق أي تبويب فارغ (about:blank) ينشئه Browserless افتراضياً عند الإقلاع،
    حتى لا يظهر التبويب الفارغ للمستخدم عند الضغط على Inspect في قائمة Sessions.
    """
    browser_obj = state.get("browser")
    if not browser_obj:
        return
    try:
        for ctx in list(browser_obj.contexts):
            for p in list(ctx.pages):
                if keep_page is not None and p == keep_page:
                    continue
                try:
                    url = p.url
                    if not url or url == "about:blank" or url.startswith("chrome://"):
                        p.close()
                except Exception:
                    pass
    except Exception:
        pass


def is_google_logged_in(context=None):
    """
    فحص كوكيز التوثيق الخاصة بـ Google على مستوى المتصفح (Storage.getCookies).
    هذه الدالة ترسل نبضة حقيقية عبر WebSocket (Keep-Alive) دون التدخل في شاشة Inspect أو DOM الصفحة.
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
                "https://www.google.com",
            ]
        )
        cookie_names = {c.get("name") for c in cookies}
        has_sid = (
            "SID" in cookie_names
            or "__Secure-1PSID" in cookie_names
            or "__Secure-3PSID" in cookie_names
        )
        has_hsid = (
            "HSID" in cookie_names
            or "SSID" in cookie_names
            or "LSID" in cookie_names
        )
        return has_sid and has_hsid
    except Exception:
        return False


def save_session_state():
    """حفظ الجلسة (الكوكيز و LocalStorage) في المسار الدائم /app/data/auth.json وفي auth.json"""
    ctx = state.get("context")
    if not ctx:
        return False
    try:
        ctx.storage_state(path=AUTH_STATE_PATH)
        if os.path.abspath(AUTH_STATE_PATH) != os.path.abspath("auth.json"):
            shutil.copyfile(AUTH_STATE_PATH, "auth.json")
        print(f"💾 تم حفظ ملف الجلسة بنجاح في: {AUTH_STATE_PATH}")
        return True
    except Exception as e:
        print(f"⚠️ تعذر حفظ ملف الجلسة auth.json: {e}")
        return False


def connect_browser():
    """الاتصال بـ Browserless وتطبيق البصمة الموحدة والجلسة المحفوظة"""
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

                permissions = ["microphone", "camera", "notifications"]
                auth_file = _get_existing_auth_file()

                context_kwargs = {
                    "permissions": permissions,
                    "viewport": {"width": 1280, "height": 720},
                    "user_agent": DEFAULT_USER_AGENT,
                    "locale": "ar-EG",
                    "timezone_id": "Africa/Cairo",
                }

                if auth_file:
                    print(f"🔑 تم العثور على {auth_file} - جاري تحميل الجلسة المحفوظة...")
                    context_kwargs["storage_state"] = auth_file

                context = state["browser"].new_context(**context_kwargs)

                try:
                    context.add_init_script(STEALTH_INIT_SCRIPT)
                except Exception:
                    pass

                state["context"] = context
                print("✅ تم الاتصال بنجاح بسيرفر Browserless!")
                return
            except Exception as e:
                print(f"⚠️ محاولة الاتصال فشلت: {e}")

        time.sleep(2)

    raise Exception("❌ فشل الاتصال بـ Browserless. تأكد من عمل السيرفر وصحة الرابط.")


def disconnect_browser(save_state=True):
    """إغلاق الاتصال بـ Browserless بأمان وتفريغ الذاكرة عند عدم وجود محاضرات نشطة"""
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
    try:
        if not state["browser"] or not state["browser"].is_connected():
            connect_browser()
        else:
            _ = state["context"].cookies("https://meet.google.com")
    except Exception:
        connect_browser()


def keep_alive():
    """
    إرسال نبضة خفيفة على مستوى المتصفح (Storage.getCookies) لإبقاء WebSocket نشطاً
    أثناء المحاضرات دون التداخل مع عرض الصفحة.
    """
    if not state.get("browser") or not state["browser"].is_connected():
        return
    if not state["pages"] and not state.get("login_in_progress"):
        return
    try:
        _ = state["context"].cookies("https://meet.google.com")
    except Exception as e:
        print(f"⚠️ تنبيه Keep-Alive: {e}")


def get_page(num="1"):
    return state["pages"].get(str(num))


def manual_login(on_ready_callback=None):
    """
    فتح صفحة تسجيل دخول Google، وإغلاق أي تبويب about:blank فارغ حتى لا يظهر في Sessions،
    وإرسال لقطة شاشة لتليجرام فور جاهزية الصفحة، ثم مراقبة الكوكيز بدون قطع اتصال Inspector.
    """
    state["login_in_progress"] = True
    page = None
    try:
        ensure_connection()
        context = state["context"]
        page = context.new_page()

        # إغلاق التبويب الافتراضي الفارغ (about:blank) حتى يكون تبويب Google هو الوحيد في Sessions
        _close_blank_tabs(keep_page=page)

        print("🌐 جاري فتح صفحة تسجيل الدخول لحساب Google...")
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)

        # التأكد مرة أخرى من إغلاق أي تبويب فارغ
        _close_blank_tabs(keep_page=page)

        # التقاط صورة لتأكيد تحميل الصفحة وإرسالها للمستخدم في تليجرام قبل أن يضغط Inspect
        preview_path = "login_ready.png"
        try:
            page.screenshot(path=preview_path)
        except Exception:
            preview_path = None

        if on_ready_callback:
            try:
                on_ready_callback(preview_path, page.url)
            except Exception as cb_err:
                print(f"⚠️ خطأ أثناء إرسال إشعار الجاهزية: {cb_err}")

        print("⏰ الشاشة جاهزة. قم بتسجيل الدخول الآن من قائمة Sessions > Inspect...")

        # حلقة انتظار (5 دقائق) تستخدم فحص الكوكيز فقط كنبضة Keep-Alive
        # بدون استدعاء page.evaluate أو new_cdp_session لكي لا تتعارض مع شاشة Inspect!
        login_detected = False
        for i in range(60):  # 60 × 5 ثوانٍ = 5 دقائق
            time.sleep(5)
            try:
                if is_google_logged_in(context):
                    print("🎉 تم رصد كوكيز تسجيل الدخول بنجاح! جاري الانتظار 5 ثوانٍ لاستقرار التوجيه...")
                    time.sleep(5)
                    save_session_state()
                    login_detected = True
                    break
            except Exception as loop_err:
                print(f"ℹ️ انتظار استكمال الدخول... ({loop_err})")

        # محاولة أخيرة لحفظ الجلسة
        save_session_state()

        if login_detected or is_google_logged_in(context):
            try:
                page.close()
            except Exception:
                pass
            if not state["pages"]:
                disconnect_browser(save_state=False)
            return (
                "✅ تم تسجيل الدخول وحفظ الجلسة (auth.json) داخل السيرفر بنجاح!\n"
                "يمكنك الآن إرسال روابط محاضرات Google Meet مباشرة."
            )
        else:
            try:
                page.close()
            except Exception:
                pass
            return (
                "⚠️ انتهت المهلة (5 دقائق) دون رصد اكتمال تسجيل الدخول.\n"
                "أرسل /login للمحاولة مرة أخرى."
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
    _close_blank_tabs(keep_page=page)
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
        raise Exception("⚠️ الحساب يطلب تسجيل الدخول! أرسل أمر /login لتوثيق الجلسة أولاً.")

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

    # إغلاق المايك والكاميرا
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

        save_session_state()
        return "✅ تم الضغط على زر الانضمام وتم الدخول بنجاح!"
    except Exception:
        try:
            page.screenshot(path="error_screen.png")
        except Exception:
            pass
        raise Exception(f"لم يتم العثور على زر الانضمام. (عنوان الصفحة: {page.title()})")


def start_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة")

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
    return "✅ بدأ التسجيل!"


def stop_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة")

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

    page.click(
        '[jsname="ahMSA"], [aria-label="Stop recording"], [aria-label="إيقاف التسجيل"]',
        timeout=15000,
    )
    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")
    return "✅ تم إيقاف التسجيل!"


def leave_meeting(num="1"):
    ensure_connection()
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    try:
        page.click('[aria-label="Leave call"], [aria-label="مغادرة المكالمة"]', timeout=10000)
        page.click('[data-mdc-dialog-action="rbwiRc"]', timeout=8000)
    except Exception:
        pass

    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(num, None)

    save_session_state()
    if not state["pages"]:
        disconnect_browser(save_state=False)

    print(f"✅ [محاضرة {num}] تمت المغادرة")
    return "✅ تمت المغادرة بنجاح!"


def refresh_and_rejoin(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    page.reload(wait_until="domcontentloaded", timeout=60000)
    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    return "✅ تم التحديث وإعادة الدخول بنجاح"