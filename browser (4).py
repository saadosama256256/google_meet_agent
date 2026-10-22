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
    1. Navigator.prototype.webdriver
    2. navigator.userAgentData
    3. window.chrome و WebGL Vendor/Renderer و Plugins
    """
    return f"""
(() => {{
    try {{
        Object.defineProperty(Navigator.prototype, 'webdriver', {{
            get: () => false,
            configurable: true,
            enumerable: true
        }});
    }} catch (e) {{}}

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

    window.chrome = window.chrome || {{
        app: {{ isInstalled: false, InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }}, RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }} }},
        runtime: {{ OnInstalledReason: {{ CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }} }},
        loadTimes: function() {{ return {{}}; }},
        csi: function() {{ return {{}}; }}
    }};

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
    if os.path.exists(AUTH_STATE_PATH) and os.path.getsize(AUTH_STATE_PATH) > 10:
        return AUTH_STATE_PATH
    if os.path.exists("auth.json") and os.path.getsize("auth.json") > 10:
        return "auth.json"
    return None


def _close_blank_tabs(keep_page=None):
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

                raw_version = browser_obj.version or "131.0.6778.85"
                full_ver = raw_version.split("/")[-1].strip()
                major_ver = full_ver.split(".")[0] if "." in full_ver else "131"

                matched_ua = (
                    f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
                )
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
    """إرسال نبضة خفيفة على مستوى المتصفح لإبقاء WebSocket نشطاً وتنظيف التبويبات المغلقة"""
    if not state.get("browser") or not state["browser"].is_connected():
        return
    # إزالة أي محاضرة أُغلق تبويبها
    for num, p in list(state["pages"].items()):
        try:
            if p.is_closed():
                state["pages"].pop(num, None)
        except Exception:
            state["pages"].pop(num, None)

    if not state["pages"] and not state.get("login_in_progress"):
        return
    try:
        _ = state["context"].cookies("https://meet.google.com")
    except Exception as e:
        print(f"⚠️ تنبيه Keep-Alive: {e}")


def get_next_lecture_num():
    """تحديد رقم المحاضرة المتاح تلقائياً (1، 2، 3...) لفتح عدة محاضرات في نفس الوقت دون إغلاق السابقة"""
    i = 1
    while str(i) in state["pages"]:
        page = state["pages"][str(i)]
        try:
            if page.is_closed():
                state["pages"].pop(str(i), None)
                return str(i)
        except Exception:
            state["pages"].pop(str(i), None)
            return str(i)
        i += 1
    return str(i)


def get_page(num=None):
    """جلب تبويب المحاضرة المطلوبة (أو المحاضرة الوحيدة المفتوحة إذا لم يحدد الرقم)"""
    if num is not None:
        return state["pages"].get(str(num))
    if "1" in state["pages"]:
        return state["pages"]["1"]
    if state["pages"]:
        first_key = sorted(state["pages"].keys())[0]
        return state["pages"][first_key]
    return None


def capture_screenshot(num=None):
    """التقاط صورة فورية لشاشة المحاضرة لمتابعتها مباشرة عبر تليجرام"""
    ensure_connection()
    target_num = str(num) if num else ("1" if "1" in state["pages"] else (sorted(state["pages"].keys())[0] if state["pages"] else "1"))
    page = state["pages"].get(target_num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة رقم {target_num} غير مفتوحة حالياً.")

    path = f"screen_{target_num}.png"
    page.screenshot(path=path)
    return path, target_num, page.url


def get_active_meetings_summary():
    """إرجاع ملخص بجميع المحاضرات المفتوحة حالياً"""
    if not state["pages"]:
        return "📭 لا توجد أي محاضرات مفتوحة حالياً."
    lines = ["📊 **المحاضرات النشطة حالياً:**"]
    for num, page in sorted(state["pages"].items()):
        try:
            status = "🟢 متصلة" if not page.is_closed() else "🔴 مغلقة"
            lines.append(f"• **محاضرة `{num}`** ({status}): {page.url}")
        except Exception:
            lines.append(f"• **محاضرة `{num}`**: غير معروف")
    return "\n".join(lines)


def manual_login(on_ready_callback=None):
    state["login_in_progress"] = True
    page = None
    try:
        ensure_connection()
        context = state["context"]
        page = context.new_page()

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

        iterations = max(12, LOGIN_WAIT_TIMEOUT_SEC // 5)
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


def join_meeting(link, num=None):
    ensure_connection()
    num = str(num) if num else get_next_lecture_num()
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
        try:
            page.close()
        except Exception:
            pass
        state["pages"].pop(num, None)
        raise Exception("⚠️ الحساب يطلب تسجيل الدخول! أرسل ملف auth.json أو أمر /login لتوثيق الجلسة أولاً.")

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
        return (
            f"✅ **[محاضرة {num}]** تم الضغط على زر الانضمام والدخول بنجاح!\n"
            f"🔴 لبدء التسجيل: `/record {num}`\n"
            f"📸 لمتابعة الشاشة: `/screen {num}`\n"
            f"🛑 للإيقاف والمغادرة: `/stop {num}`"
        )
    except Exception:
        try:
            page.screenshot(path="error_screen.png")
        except Exception:
            pass
        raise Exception(f"[محاضرة {num}] لم يتم العثور على زر الانضمام. (عنوان الصفحة: {page.title()})")


def start_recording(num="1"):
    ensure_connection()
    num = str(num)
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
    return f"✅ **[محاضرة {num}]** بدأ التسجيل السحابي في Google Drive بنجاح!"


def stop_recording(num="1"):
    ensure_connection()
    num = str(num)
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

    page.click(
        '[jsname="ahMSA"], [aria-label="Stop recording"], [aria-label="إيقاف التسجيل"]',
        timeout=15000,
    )
    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")
    return f"✅ **[محاضرة {num}]** تم إيقاف التسجيل وحفظه في Google Drive!"


def leave_meeting(num="1"):
    ensure_connection()
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة حالياً.")

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
    return f"✅ **[محاضرة {num}]** تمت المغادرة وإغلاق التبويب بنجاح!"


def refresh_and_rejoin(num="1"):
    ensure_connection()
    num = str(num)
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
    return f"✅ **[محاضرة {num}]** تم تحديث الصفحة وإعادة الدخول بنجاح!"