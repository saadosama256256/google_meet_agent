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
    "login_page": None,
    "login_in_progress": False,
}


def _build_stealth_script(full_version="131.0.6778.85", major_version="131"):
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
}})();
"""


def _build_ws_candidates():
    base_url = BROWSERLESS_WS.strip()
    sep = "&" if "?" in base_url else "?"
    candidates = []

    direct_flags = (
        f"{base_url}{sep}timeout={BROWSERLESS_TIMEOUT_MS}"
        "&stealth=true"
        "&--disable-blink-features=AutomationControlled"
        "&--no-sandbox"
        "&--disable-dev-shm-usage"
        "&--use-fake-ui-for-media-stream"
        "&--use-fake-device-for-media-stream"
        "&--window-size=1280,720"
    )
    candidates.append(direct_flags)

    launch_payload = {
        "stealth": True,
        "ignoreDefaultArgs": ["--enable-automation"],
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


def _inject_cookies_into_context(context, auth_file):
    if not auth_file or not os.path.exists(auth_file):
        return 0
    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_cookies = data.get("cookies", [])
        if not raw_cookies:
            return 0

        allowed_keys = {
            "name",
            "value",
            "domain",
            "path",
            "expires",
            "httpOnly",
            "secure",
            "sameSite",
        }
        cleaned_cookies = []
        for c in raw_cookies:
            clean_c = {k: v for k, v in c.items() if k in allowed_keys and v is not None}
            if "sameSite" in clean_c and clean_c["sameSite"] not in ("Strict", "Lax", "None"):
                clean_c.pop("sameSite", None)
            if "name" in clean_c and "value" in clean_c and "domain" in clean_c:
                cleaned_cookies.append(clean_c)

        context.add_cookies(cleaned_cookies)
        print(f"🔑 تم حقن {len(cleaned_cookies)} كوكي بنجاح داخل السياق الأساسي (contexts[0])!")
        return len(cleaned_cookies)
    except Exception as e:
        print(f"⚠️ خطأ أثناء حقن الكوكيز في السياق الأساسي: {e}")
        return 0


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

                if browser_obj.contexts:
                    context = browser_obj.contexts[0]
                    print("📂 تم الربط مع السياق الأساسي للمتصفح (browser.contexts[0]).")
                else:
                    context = browser_obj.new_context(viewport={"width": 1280, "height": 720})

                try:
                    context.grant_permissions(
                        ["microphone", "camera", "notifications"],
                        origin="https://meet.google.com",
                    )
                except Exception:
                    pass

                try:
                    context.add_init_script(_build_stealth_script(full_ver, major_ver))
                except Exception:
                    pass

                auth_file = _get_existing_auth_file()
                if auth_file:
                    _inject_cookies_into_context(context, auth_file)

                state["context"] = context
                print(f"✅ تم الاتصال بنجاح بـ Browserless (Chrome/{full_ver})!")
                return
            except Exception as e:
                print(f"⚠️ تعذر الاتصال بالرابط المرشح: {e}")

        time.sleep(2)

    raise Exception("❌ فشل الاتصال بـ Browserless. تأكد من عمل السيرفر وصحة الرابط.")


def disconnect_browser(save_state=True):
    if save_state and state.get("context"):
        save_session_state()

    state["pages"].clear()
    state["login_page"] = None

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
    if not state.get("browser") or not state["browser"].is_connected():
        return
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


def _acquire_page_in_default_context():
    context = state["context"]
    used_pages = set(state["pages"].values())
    if state.get("login_page") and not state["login_page"].is_closed():
        used_pages.add(state["login_page"])

    for p in list(context.pages):
        try:
            if not p.is_closed() and p not in used_pages:
                if not p.url or p.url == "about:blank" or "workspace.google.com" in p.url:
                    p.set_viewport_size({"width": 1280, "height": 720})
                    return p
        except Exception:
            pass

    page = context.new_page()
    try:
        page.set_viewport_size({"width": 1280, "height": 720})
    except Exception:
        pass
    return page


def get_next_lecture_num():
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
    if num is not None:
        return state["pages"].get(str(num))
    if "1" in state["pages"]:
        return state["pages"]["1"]
    if state["pages"]:
        first_key = sorted(state["pages"].keys())[0]
        return state["pages"][first_key]
    return None


def capture_screenshot(num=None):
    ensure_connection()
    if state.get("login_in_progress") and state.get("login_page") and not state["login_page"].is_closed():
        path = "screen_login.png"
        state["login_page"].screenshot(path=path)
        return path, "تسجيل الدخول", state["login_page"].url

    target_num = (
        str(num)
        if num
        else ("1" if "1" in state["pages"] else (sorted(state["pages"].keys())[0] if state["pages"] else "1"))
    )
    page = state["pages"].get(target_num)
    if not page or page.is_closed():
        raise Exception(f"المحاضرة رقم {target_num} غير مفتوحة حالياً.")

    path = f"screen_{target_num}.png"
    page.screenshot(path=path)
    return path, target_num, page.url


def get_active_meetings_summary():
    auth_file = _get_existing_auth_file()
    if auth_file:
        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                c_count = len(json.load(f).get("cookies", []))
            auth_status = f"🔑 **ملف الجلسة (`auth.json`):** موجود ✅ ({c_count} كوكي)"
        except Exception:
            auth_status = "🔑 **ملف الجلسة (`auth.json`):** موجود ✅"
    else:
        auth_status = "🔑 **ملف الجلسة (`auth.json`):** ❌ غير موجود"

    if not state["pages"]:
        return f"{auth_status}\n\n📭 لا توجد أي محاضرات مفتوحة حالياً."

    lines = [auth_status, "", "📊 **المحاضرات النشطة حالياً:**"]
    for num, page in sorted(state["pages"].items()):
        try:
            status = "🟢 متصلة" if not page.is_closed() else "🔴 مغلقة"
            lines.append(f"• **محاضرة `{num}`** ({status}): {page.url}")
        except Exception:
            lines.append(f"• **محاضرة `{num}`**: غير معروف")
    return "\n".join(lines)


# ==============================================================================
# نظام الدخول التفاعلي عبر تليجرام
# ==============================================================================

def start_telegram_login():
    state["login_in_progress"] = True
    ensure_connection()
    page = _acquire_page_in_default_context()
    state["login_page"] = page

    print("🌐 فتح صفحة تسجيل دخول Google عبر تليجرام...")
    page.goto(
        "https://accounts.google.com/ServiceLogin?hl=ar&continue=https://meet.google.com/landing",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(3000)

    path = "login_step.png"
    page.screenshot(path=path)

    if is_google_logged_in(state["context"]) and "accounts.google.com" not in page.url:
        save_session_state()
        state["login_in_progress"] = False
        return path, "✅ الحساب مسجل الدخول بالفعل على السيرفر وتم حفظ `auth.json`!"

    caption = (
        "🔐 **تم فتح بوابة الدخول على السيرفر بنجاح (وضع التخفي الكامل بدون Inspect)!**\n\n"
        "1️⃣ **أرسل بريدك الإلكتروني الآن بهذا الأمر:**\n"
        "`/email your_email@gmail.com`\n\n"
        "*(ملاحظة: لا تفتح شاشة Inspect في Browserless حتى لا ترصد Google وجود أداة الفحص)*."
    )
    return path, caption


def submit_login_email(email_text):
    page = state.get("login_page")
    if not page or page.is_closed():
        raise Exception("⚠️ جلسة الدخول غير مفتوحة! أرسل `/login` أولاً.")

    email_input = page.locator('input[type="email"], input[name="identifier"]').first
    email_input.wait_for(timeout=15000)
    email_input.click()
    email_input.fill("")
    email_input.type(email_text.strip(), delay=60)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")

    page.wait_for_timeout(5000)
    path = "login_step.png"
    page.screenshot(path=path)

    caption = (
        "📧 **تم إرسال البريد الإلكتروني!**\n\n"
        "2️⃣ إذا ظهرت خانة كلمة المرور في الصورة أعلاه، **أرسل كلمة المرور الآن بهذا الأمر:**\n"
        "`/pass كلمة_المرور`"
    )
    return path, caption


def submit_login_password(password_text):
    page = state.get("login_page")
    if not page or page.is_closed():
        raise Exception("⚠️ جلسة الدخول غير مفتوحة! أرسل `/login` أولاً.")

    pwd_input = page.locator('input[type="password"], input[name="Passwd"]').first
    pwd_input.wait_for(timeout=15000)
    pwd_input.click()
    pwd_input.fill("")
    pwd_input.type(password_text.strip(), delay=60)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")

    page.wait_for_timeout(6000)
    path = "login_step.png"
    page.screenshot(path=path)

    if is_google_logged_in(state["context"]) and "signin" not in page.url:
        save_session_state()
        state["login_in_progress"] = False
        return (
            path,
            "🎉 **تم تسجيل الدخول وحفظ الجلسة (`auth.json`) من داخل السيرفر بنجاح!**\n"
            "يمكنك الآن إرسال رابط أي محاضرة Google Meet مباشرة.",
        )

    caption = (
        "🔑 **تم إرسال كلمة المرور!** انظر للصورة أعلاه:\n\n"
        "• إذا طلب Google **الموافقة أو اختيار رقم على هاتفك**، وافق من هاتفك ثم أرسل:\n"
        "`/save`\n"
        "• وإذا طلب **كود تحقق نصي**، أرسله بهذا الأمر:\n"
        "`/code 123456`"
    )
    return path, caption


def submit_login_code(code_text):
    page = state.get("login_page")
    if not page or page.is_closed():
        raise Exception("⚠️ جلسة الدخول غير مفتوحة! أرسل `/login` أولاً.")

    code_input = page.locator(
        'input[type="tel"], input[name="totpPin"], input[name="idvPin"], input[name="Pin"], input[type="text"]'
    ).first
    code_input.wait_for(timeout=15000)
    code_input.click()
    code_input.fill("")
    code_input.type(code_text.strip(), delay=60)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")

    page.wait_for_timeout(6000)
    return finish_and_save_login()


def finish_and_save_login():
    page = state.get("login_page")
    if not page or page.is_closed():
        raise Exception("⚠️ جلسة الدخول غير مفتوحة! أرسل `/login` أولاً.")

    page.wait_for_timeout(3000)
    if is_google_logged_in(state["context"]):
        try:
            if "meet.google.com" not in page.url:
                page.goto("https://meet.google.com/landing", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
        except Exception:
            pass

        save_session_state()
        path = "login_step.png"
        page.screenshot(path=path)
        state["login_in_progress"] = False
        return (
            path,
            "🎉 **تم توثيق الحساب على السيرفر وحفظ الجلسة (`auth.json`) بنجاح 100%!**\n"
            "الجلسة الآن مربوطة بـ IP السيرفر نفسه ولن تنتهي صلاحيتها. أرسل رابط Google Meet للتجربة!",
        )
    else:
        path = "login_step.png"
        page.screenshot(path=path)
        return (
            path,
            "⏳ لم يرصد المتصفح اكتمال الكوكيز بعد. إذا وافقت من هاتفك للتو، انتظر 5 ثوانٍ وأرسل `/save` مرة أخرى.",
        )


def join_meeting(link, num=None):
    auth_file = _get_existing_auth_file()
    if not auth_file and not is_google_logged_in():
        raise Exception(
            "⚠️ ملف الجلسة `auth.json` غير موجود على السيرفر!\n"
            "أرسل `/login` لتسجيل الدخول مباشرة من تليجرام، أو أرسل ملف `auth.json` في المحادثة."
        )

    ensure_connection()
    context = state["context"]

    if not is_google_logged_in(context) and auth_file:
        _inject_cookies_into_context(context, auth_file)

    num = str(num) if num else get_next_lecture_num()

    if num in state["pages"]:
        try:
            state["pages"][num].close()
        except Exception:
            pass

    page = _acquire_page_in_default_context()
    state["pages"][num] = page

    try:
        print(f"🔗 [محاضرة {num}] جاري الدخول: {link}")
        page.goto(link, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # فحص مباشر لما إذا كانت قاعة الاجتماع مقيدة أو مغلقة من قبل المضيف
        blocked_locator = page.locator(
            "text=/لا يُمكنك الانضمام|لا يمكنك الانضمام|You can't join this video call/i"
        )
        if blocked_locator.count() > 0 and blocked_locator.first.is_visible():
            try:
                page.screenshot(path="error_screen.png")
            except Exception:
                pass
            raise Exception(
                "🔒 **الاجتماع مقيّد أو لم يبدأه المضيف بعد!**\n"
                "(Your meeting is safe: لا يُسمح بالانضمام إلا بدعوة من المضيف أو قبول الدخول يدويًا).\n"
                "👉 **جرب الآن إرسال رابط اجتماع مفتوح أو فوري من هاتفك للتأكد من نجاح الدخول الفوري.**"
            )

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

        # البحث بالمعرّف الداخلي الرسمي button[jsname='Qx7uuf'] أولاً ثم بالنصوص
        join_selector = (
            "button[jsname='Qx7uuf'], "
            "button:has-text('Join now'), "
            "button:has-text('Ask to join'), "
            "button:has-text('الانضمام الآن'), "
            "button:has-text('طلب الانضمام'), "
            "button:has-text('Join now without microphone'), "
            "button:has-text('Switch here'), "
            "button:has-text('الانضمام من هنا')"
        )

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
    except Exception as e:
        try:
            if not os.path.exists("error_screen.png"):
                page.screenshot(path="error_screen.png")
        except Exception:
            pass
        state["pages"].pop(num, None)
        raise Exception(str(e))


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
        "button[jsname='Qx7uuf'], "
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    return f"✅ **[محاضرة {num}]** تم تحديث الصفحة وإعادة الدخول بنجاح!"
