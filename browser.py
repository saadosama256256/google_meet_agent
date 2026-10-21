import json
import os
import shutil
import time
import urllib.parse
from playwright.sync_api import sync_playwright
from config import (
    AUTH_STATE_PATH,
    BROWSERLESS_TIMEOUT_MS,
    BROWSERLESS_WS,
    LOGIN_WAIT_TIMEOUT_SEC,
)

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},
    "login_in_progress": False,
}


def _build_stealth_script(full_version="131.0.6778.85", major_version="131"):
    """
    سكربت متقدم لإخفاء كافة دلائل الأتمتة و HeadlessChrome من:
    1. Navigator.prototype.webdriver (بدون ترك أثر hasOwnProperty على الكائن)
    2. navigator.userAgentData (إزالة علامة HeadlessChrome تماماً واستبدالها بـ Google Chrome)
    3. window.chrome و WebGL Vendor/Renderer و Plugins
    """
    return f"""
(() => {{
    // 1. إخفاء webdriver من الـ Prototype بشكل أصيل لا يكشفه فحص BotGuard
    try {{
        Object.defineProperty(Navigator.prototype, 'webdriver', {{
            get: () => false,
            configurable: true,
            enumerable: true
        }});
    }} catch (e) {{}}

    // 2. استبدال HeadlessChrome في navigator.userAgentData بـ Google Chrome
    try {{
        const brands = [
            {{ brand: 'Google Chrome', version: '{major_version}' }},
            {{ brand: 'Chromium', version: '{major_version}' }},
            {{ brand: 'Not_A Brand', version: '24' }}
        ];
        const fullVersionList = [
            {{ brand: 'Google Chrome', version: '{full_version}' }},
            {{ brand: 'Chromium', version: '{full_version}' }},
            {{ brand: 'Not_A Brand', version: '24.0.0.0' }}
        ];
        const uaData = {{
            brands: brands,
            mobile: false,
            platform: 'Linux',
            getHighEntropyValues: async (hints) => ({{
                architecture: 'x86',
                bitness: '64',
                brands: brands,
                fullVersionList: fullVersionList,
                mobile: false,
                model: '',
                platform: 'Linux',
                platformVersion: '6.5.0',
                uaFullVersion: '{full_version}',
                wow64: false
            }}),
            toJSON: () => ({{ brands: brands, mobile: false, platform: 'Linux' }})
        }};
        Object.defineProperty(Navigator.prototype, 'userAgentData', {{
            get: () => uaData,
            configurable: true,
            enumerable: true
        }});
    }} catch (e) {{}}

    // 3. محاكاة كائن window.chrome الكامل للمتصفح العادي
    window.chrome = window.chrome || {{
        app: {{ isInstalled: false, InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }}, RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }} }},
        runtime: {{ OnInstalledReason: {{ CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }} }},
        loadTimes: function() {{ return {{}}; }},
        csi: function() {{ return {{}}; }}
    }};

    // 4. محاكاة اللغات والإضافات
    try {{
        Object.defineProperty(Navigator.prototype, 'languages', {{
            get: () => ['ar-EG', 'ar', 'en-US', 'en'],
            configurable: true
        }});
        Object.defineProperty(Navigator.prototype, 'plugins', {{
            get: () => [1, 2, 3, 4, 5],
            configurable: true
        }});
    }} catch (e) {{}}

    // 5. إخفاء بصمة WebGL الافتراضية (SwiftShader) التي تكشف السيرفر
    try {{
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {{
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameter.apply(this, arguments);
        }};
    }} catch (e) {{}}
}})();
"""


def _build_ws_candidates():
    """
    تجهيز روابط الاتصال بـ Browserless:
    الخيار الأول: تمرير --disable-blink-features=AutomationControlled لإيقاف كشف Google للأتمتة من جذور المتصفح
                  (بدون تمرير --user-data-dir الذي يسبب مشكلة الصفحة الفارغة).
    الخيار الثاني: الرابط المزود بمهلة timeout فقط كخيار احتياطي.
    """
    base_url = BROWSERLESS_WS.strip()
    sep = "&" if "?" in base_url else "?"
    candidates = []

    launch_payload = {
        "stealth": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1280,720",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
        ],
    }
    encoded_launch = urllib.parse.quote(json.dumps(launch_payload))

    candidates.append(
        f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}&stealth=true&launch={encoded_launch}"
    )
    candidates.append(
        f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}&launch={encoded_launch}"
    )
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
    ترسل نبضة حقيقية عبر WebSocket (Keep-Alive) دون التدخل في شاشة Inspect.
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
    """
    الاتصال بـ Browserless ومطابقة إصدار Chrome الفعلي في User-Agent وترويسات Sec-CH-UA
    لتخطي فحص الأمان في Google (This browser or app may not be secure).
    """
    disconnect_browser(save_state=False)

    state["playwright"] = sync_playwright().start()
    ws_candidates = _build_ws_candidates()

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        for ws_url in ws_candidates:
            try:
                print(f"⏳ جاري الاتصال بـ Browserless (محاولة {attempt}/{max_attempts})...")
                browser_obj = state["playwright"].chromium.connect_over_cdp(
                    ws_url, timeout=60000
                )
                state["browser"] = browser_obj

                # قراءة الإصدار الفعلي لمتصفح Chromium على السيرفر لمنع أي تضارب في البصمة
                raw_version = browser_obj.version or "131.0.6778.85"
                full_ver = raw_version.split("/")[-1].strip()
                major_ver = full_ver.split(".")[0] if "." in full_ver else "131"

                matched_ua = (
                    f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
                )
                # ترويسات Sec-CH-UA خالية تماماً من كلمة HeadlessChrome
                client_hints_headers = {
                    "sec-ch-ua": f'"Google Chrome";v="{major_ver}", "Chromium";v="{major_ver}", "Not_A Brand";v="24"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Linux"',
                }

                permissions = ["microphone", "camera", "notifications"]
                auth_file = _get_existing_auth_file()

                context_kwargs = {
                    "permissions": permissions,
                    "viewport": {"width": 1280, "height": 720},
                    "user_agent": matched_ua,
                    "extra_http_headers": client_hints_headers,
                    "locale": "ar-EG",
                    "timezone_id": "Africa/Cairo",
                }

                if auth_file:
                    print(f"🔑 تم العثور على {auth_file} - جاري تحميل الجلسة المحفوظة...")
                    context_kwargs["storage_state"] = auth_file

                context = browser_obj.new_context(**context_kwargs)

                try:
                    context.add_init_script(_build_stealth_script(full_ver, major_ver))
                except Exception:
                    pass

                state["context"] = context
                print(f"✅ تم الاتصال بنجاح بـ Browserless (إصدار المتصفح المطابق: Chrome/{full_ver})!")
                return
            except Exception as e:
                print(f"⚠️ تعذر الاتصال بالرابط المرشح: {e}")

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
    """إرسال نبضة خفيفة على مستوى المتصفح لإبقاء WebSocket نشطاً أثناء المحاضرات"""
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
    تهيئة كوكيز Google الأولية ثم فتح بوابة الدخول القياسية مع إخفاء كامل لبصمة الأتمتة،
    ومراقبة الكوكيز لمدة 10 دقائق لإعطاء وقت كافٍ لإدخال كود التحقق.
    """
    state["login_in_progress"] = True
    page = None
    try:
        ensure_connection()
        context = state["context"]
        page = context.new_page()

        # إغلاق التبويب الافتراضي الفارغ (about:blank) فوراً
        _close_blank_tabs(keep_page=page)

        print("🌐 خطوة 1: تهيئة كوكيز التصفح الطبيعية على google.com...")
        try:
            page.goto("https://www.google.com/?hl=ar", wait_until="domcontentloaded", timeout=30000)
            time.sleep(1.5)
        except Exception:
            pass

        print("🌐 خطوة 2: جاري فتح صفحة تسجيل الدخول لحساب Google...")
        page.goto(
            "https://accounts.google.com/ServiceLogin?hl=ar&passive=true&continue=https://www.google.com/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        time.sleep(2)

        _close_blank_tabs(keep_page=page)

        # التقاط صورة لتأكيد تحميل الصفحة وإرسالها للمستخدم في تليجرام
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

        iterations = max(12, LOGIN_WAIT_TIMEOUT_SEC // 5)  # الافتراضي: 120 × 5 ثوانٍ = 10 دقائق
        login_detected = False
        for i in range(iterations):
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
            if not state["pages"]:
                disconnect_browser(save_state=False)
            minutes = LOGIN_WAIT_TIMEOUT_SEC // 60
            return (
                f"⚠️ انتهت المهلة ({minutes} دقائق) دون رصد اكتمال تسجيل الدخول.\n"
                "أرسل /login في أي وقت للمحاولة مرة أخرى."
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
