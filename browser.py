import functools
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

# ============================================================
# الإعدادات
# ============================================================

# عنوان بورت التحكم في كروم (CDP)
CDP_URL = os.environ.get("MEET_CDP_URL", "http://localhost:9223")

# حظر الصور فقط لتوفير الموارد. (الخطوط والميديا ممنوع حظرها: الخطوط تحمل أيقونات Meet)
BLOCK_IMAGES = True

# مجلد حفظ لقطات الشاشة عند الفشل (للتشخيص)
DEBUG_DIR = "debug"

# حفظ لقطة شاشة بعد كل بدء/إيقاف تسجيل (للتشخيص، عطّله لاحقاً)
ALWAYS_DEBUG = True

# ملف حفظ الجلسة (يحتوي كوكيز الحساب: لا ترفعه لأي مستودع!)
AUTH_FILE = "auth.json"

# المحاضرات الافتراضية الثلاث الثابتة (عدّلها بروابطك الأساسية)
DEFAULT_MEETINGS = {
    "1": "https://meet.google.com/xxx-yyyy-zzz",
    "2": "https://meet.google.com/aaa-bbbb-ccc",
    "3": "https://meet.google.com/mmm-nnnn-ooo",
}

# ============================================================
# نصوص الواجهة (إنجليزي + عربي)
# ============================================================
JOIN_RE = re.compile(
    r"join now|ask to join|الانضمام الآن|انضم الآن|طلب الانضمام|اطلب الانضمام", re.I
)
CONTINUE_WITHOUT_RE = re.compile(
    r"continue without|المتابعة بدون|متابعة بدون|المتابعة دون", re.I
)
POPUP_DISMISS_RE = re.compile(r"^(got it|dismiss|ok|حسنًا|حسناً|فهمت|إغلاق)$", re.I)

RECORD_ITEM_RE = re.compile(r"record|تسجيل", re.I)
ACTIVITIES_RE = re.compile(r"activities|الأنشطة|أنشطة", re.I)

START_REC_RE = re.compile(r"start recording|بدء التسجيل|ابدأ التسجيل", re.I)
START_CONFIRM_RE = re.compile(r"start|بدء|ابدأ", re.I)
STOP_REC_RE = re.compile(r"stop recording|إيقاف التسجيل|أوقف التسجيل|إنهاء التسجيل", re.I)
STOP_CONFIRM_RE = re.compile(r"stop|إيقاف|أوقف|إنهاء", re.I)
END_FOR_ALL_RE = re.compile(
    r"end call for everyone|إنهاء المكالمة للجميع|إنهاء الاجتماع للجميع", re.I
)

MORE_OPTIONS_SEL = (
    'button[aria-label="More options"], '
    'button[aria-label="المزيد من الخيارات"]'
)
LEAVE_SEL = '[aria-label="Leave call"], [aria-label="مغادرة المكالمة"]'
MENU_SEL = '[role="menu"]'
DIALOG_SEL = '[role="dialog"], [role="alertdialog"]'

# محددات jsname القديمة: تُستخدم كخيار احتياطي أخير فقط (Google قد تغيّرها)
JS_START_REC = '[jsname="A0ONe"]'
JS_STOP_REC = '[jsname="ahMSA"]'
JS_DIALOG_CONFIRM = '[data-mdc-dialog-action="A9Emjd"]'
JS_END_FOR_ALL = '[data-mdc-dialog-action="rbwiRc"]'


class MeetBotError(Exception):
    """خطأ مخصص للبوت (رسالته جاهزة للعرض للمستخدم)."""


state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},
}

# ============================================================
# تشغيل كل أوامر Playwright في Thread واحد مخصص
# (يحل greenlet.error و "Sync API inside asyncio loop")
# ============================================================
_worker_ident = None


def _set_worker_ident():
    global _worker_ident
    _worker_ident = threading.get_ident()


_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="playwright", initializer=_set_worker_ident
)


def pw_thread(fn):
    """يضمن تنفيذ الدالة داخل الـ thread الوحيد الذي يملك Playwright،
    ويمكن استدعاؤها بأمان من أي thread (مثل بوت تيليجرام)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if threading.get_ident() == _worker_ident:
            return fn(*args, **kwargs)
        return _executor.submit(fn, *args, **kwargs).result()

    return wrapper


# ============================================================
# أدوات مساعدة
# ============================================================
def extract_meet_info(target: str) -> tuple[str, str]:
    """استخراج كود ورابط الاجتماع سواء أكان رقماً (1-3) أو رابطاً كاملاً"""
    target = str(target).strip()
    if target in DEFAULT_MEETINGS:
        return target, DEFAULT_MEETINGS[target]

    match = re.search(r"([a-z]{3}-[a-z]{4}-[a-z]{3})", target.lower())
    if match:
        code = match.group(1)
        return code, f"https://meet.google.com/{code}"

    if target.startswith("http"):
        clean = target.split("?")[0].rstrip("/")
        return clean.rsplit("/", 1)[-1], target

    return target, f"https://meet.google.com/{target}"


def get_page(num):
    key = str(num)
    page = state["pages"].get(key)
    if page is not None:
        try:
            if page.is_closed():
                state["pages"].pop(key, None)
                return None
        except Exception:
            return None
    return page


def list_open_meetings():
    return [k for k in list(state["pages"].keys()) if get_page(k) is not None]


def _require_page(num):
    page = get_page(num)
    if not page:
        raise MeetBotError(f"المحاضرة {num} غير مفتوحة")
    return page


def dump_debug(page, tag):
    """حفظ لقطة شاشة وقائمة العناصر الظاهرة لتسهيل التشخيص."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        path = os.path.join(DEBUG_DIR, f"{tag}_{int(time.time())}.png")
        page.screenshot(path=path)
        print(f"   🧪 لقطة تشخيصية: {path}")
    except Exception:
        pass
    try:
        items = page.evaluate(
            """() => Array.from(document.querySelectorAll(
                '[role="menuitem"], [role="menu"] li, [role="dialog"] button'))
                .filter(e => e.getBoundingClientRect().width > 0)
                .map(e => (e.innerText || '').trim())
                .filter(Boolean)"""
        )
        print(f"   🧪 العناصر الظاهرة: {items}")
    except Exception:
        pass


def real_click(page, x, y):
    """ضغطة ماوس حقيقية بإحداثيات الشاشة (احتياطية، غير مستخدمة افتراضياً)"""
    page.mouse.move(x, y)
    page.wait_for_timeout(150)
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.up()


_VISIBLE_CLICK_JS = """(sel) => {
    const els = Array.from(document.querySelectorAll(sel));
    const el = els.find(e => {
        const r = e.getBoundingClientRect();
        const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 &&
               s.visibility !== 'hidden' && s.display !== 'none';
    });
    if (el) { el.click(); return true; }
    return false;
}"""


def wait_and_click(page, selector, timeout_ms=15000, label=""):
    """انتظار ظهور عنصر (أول عنصر مرئي يطابق المحدد) ثم النقر عبر جافاسكربت.
    المحدد يُمرَّر كوسيط (آمن حتى لو احتوى على علامات اقتباس)."""
    waited = 0
    interval = 300
    while waited < timeout_ms:
        try:
            clicked = page.evaluate(_VISIBLE_CLICK_JS, selector)
        except Exception:
            # قد تتغير الصفحة أثناء التنقل (مثلاً بعد مغادرة الاجتماع)
            clicked = False
        if clicked:
            print(f"   {label} ✅ (بعد {waited}ms)")
            return True
        page.wait_for_timeout(interval)
        waited += interval
    print(f"   ❌ {label} لم يظهر خلال {timeout_ms}ms")
    return False


def click_any(page, locators, timeout_ms=10000, label=""):
    """ينتظر ظهور أي Locator من القائمة (بالترتيب) وينقر عليه عبر JS."""
    waited = 0
    interval = 300
    while waited <= timeout_ms:
        for loc in locators:
            try:
                target = loc.first
                if target.count() and target.is_visible():
                    target.evaluate("el => el.click()")
                    print(f"   {label} ✅ (بعد {waited}ms)")
                    return True
            except Exception:
                continue
        page.wait_for_timeout(interval)
        waited += interval
    print(f"   ❌ {label} لم يظهر خلال {timeout_ms}ms")
    return False


def dialog_button(page, name_re):
    return page.locator(DIALOG_SEL).get_by_role("button", name=name_re)


def apply_resource_limits(page):
    """ترشيد الاستهلاك بحظر الصور فقط.
    لا نحظر font (أيقونات Meet) ولا media."""
    if not BLOCK_IMAGES:
        return

    def route_filter(route):
        try:
            if route.request.resource_type == "image":
                route.abort()
            else:
                route.continue_()
        except Exception:
            pass

    page.route("**/*", route_filter)


def wake_up_controls(page):
    """تحريك الماوس لإجبار الشريط السفلي على الظهور (بإحداثيات تناسب حجم النافذة)"""
    try:
        w, h = page.evaluate("() => [window.innerWidth, window.innerHeight]")
    except Exception:
        w, h = 1280, 720
    page.mouse.move(w // 2, h // 2)
    page.wait_for_timeout(150)
    page.mouse.move(w // 2, h - 60)
    page.wait_for_timeout(250)


def dismiss_popups(page):
    """إغلاق النوافذ المنبثقة المزعجة (Got it ...) بدون فشل إن لم توجد."""
    try:
        btn = page.get_by_role("button", name=POPUP_DISMISS_RE).first
        if btn.count() and btn.is_visible():
            btn.evaluate("el => el.click()")
    except Exception:
        pass


def _bottom_more_options_button(page):
    """زر More options الخاص بالشريط السفلي (أدنى زر على الشاشة)،
    لتجنّب أزرار القوائم الخاصة ببلاطات المشتركين."""
    best, best_y = None, -1
    buttons = page.locator(MORE_OPTIONS_SEL).all()
    for b in buttons:
        try:
            box = b.bounding_box()
        except Exception:
            continue
        if box and box["y"] > best_y:
            best, best_y = b, box["y"]
    return best


def _menu_visible(page):
    try:
        return page.locator(MENU_SEL).first.is_visible()
    except Exception:
        return False


def open_more_options(page):
    """فتح قائمة (المزيد من الخيارات) السفلية والتأكد فعلاً من ظهور القائمة."""
    wake_up_controls(page)

    # إن كانت هناك قائمة مفتوحة (قد تكون لمشترك) نغلقها أولاً لنبدأ من حالة نظيفة
    if _menu_visible(page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    for attempt in range(1, 4):
        wake_up_controls(page)
        btn = _bottom_more_options_button(page)
        if btn is None:
            page.wait_for_timeout(1000)
            continue
        try:
            btn.evaluate("el => el.click()")
            page.locator(MENU_SEL).first.wait_for(state="visible", timeout=3000)
            return
        except PWTimeout:
            print(f"   ⏳ القائمة لم تظهر (محاولة {attempt}/3)")
        except Exception as e:
            print(f"   ⚠️ تعذر النقر على More options (محاولة {attempt}/3): {e}")
        page.wait_for_timeout(500)

    dump_debug(page, "more_options")
    raise MeetBotError("❌ تعذر فتح قائمة (المزيد من الخيارات)")


def _click_menu_item(page, name_re, timeout_ms=3000, label=""):
    candidates = [
        page.locator('[role="menuitem"]').filter(has_text=name_re),
        page.locator('[role="menu"] li').filter(has_text=name_re),
    ]
    return click_any(page, candidates, timeout_ms, label)


def open_recording_panel(page):
    """يفتح لوحة التسجيل: من القائمة مباشرة، أو عبر Activities في الإصدارات الأحدث."""
    open_more_options(page)

    if _click_menu_item(page, RECORD_ITEM_RE, 3000, "خيار Recording"):
        page.wait_for_timeout(1200)
        return

    # بعض الإصدارات تضع التسجيل داخل Activities
    print("   ↪️ لم يظهر Recording في القائمة، جاري تجربة Activities...")
    if _click_menu_item(page, ACTIVITIES_RE, 3000, "خيار Activities"):
        page.wait_for_timeout(1200)
        inner = [
            page.get_by_role("button", name=RECORD_ITEM_RE),
            page.get_by_role("menuitem", name=RECORD_ITEM_RE),
            page.get_by_role("listitem").filter(has_text=RECORD_ITEM_RE),
            page.get_by_text(RECORD_ITEM_RE),
        ]
        if click_any(page, inner, 5000, "Recording داخل Activities"):
            page.wait_for_timeout(1200)
            return

    dump_debug(page, "no_recording_option")
    raise MeetBotError("❌ لم يتم العثور على خيار التسجيل في القائمة")


def _btn_visible(page, name_re):
    try:
        b = page.get_by_role("button", name=name_re).first
        return b.count() > 0 and b.is_visible()
    except Exception:
        return False


def _recording_state(page, reopen=True, timeout_ms=6000):
    """يرجع 'active' (زر Stop ظاهر) أو 'idle' (زر Start ظاهر) أو 'unknown'."""
    if reopen:
        try:
            open_recording_panel(page)
        except MeetBotError:
            return "unknown"
    waited = 0
    while waited <= timeout_ms:
        if _btn_visible(page, STOP_REC_RE):
            return "active"
        if _btn_visible(page, START_REC_RE):
            return "idle"
        page.wait_for_timeout(400)
        waited += 400
    return "unknown"


def _verify_started(page):
    # اللوحة قد تبقى مفتوحة وتعرض Stop recording بعد البدء
    waited = 0
    while waited < 8000:
        if _btn_visible(page, STOP_REC_RE):
            return "active"
        page.wait_for_timeout(500)
        waited += 500
    state_ = _recording_state(page, reopen=True)
    if state_ == "idle":
        page.wait_for_timeout(5000)  # قد يكون التسجيل ما زال يتهيأ
        state_ = _recording_state(page, reopen=True)
    return state_


# ============================================================
# الاتصال بالمتصفح
# ============================================================
@pw_thread
def connect_browser():
    # اتصال قائم وسليم؟ لا حاجة لإعادة الاتصال
    if state["browser"] is not None:
        try:
            if state["browser"].is_connected():
                return
        except Exception:
            pass
        _cleanup_playwright()

    state["playwright"] = sync_playwright().start()
    max_attempts = 20
    for attempt in range(1, max_attempts + 1):
        try:
            browser = state["playwright"].chromium.connect_over_cdp(CDP_URL)
            contexts = browser.contexts
            context = contexts[0] if contexts else browser.new_context()
            state["browser"] = browser
            state["context"] = context
            print("✅ تم الاتصال بمتصفح Chrome (Profile 1)")
            return
        except Exception:
            print(f"⏳ محاولة {attempt}/{max_attempts}: كروم غير جاهز بعد، إعادة المحاولة...")
            time.sleep(2)

    _cleanup_playwright()
    raise MeetBotError(f"❌ فشل الاتصال بكروم. تأكد من تشغيله على {CDP_URL}")


def _cleanup_playwright():
    try:
        if state["playwright"]:
            state["playwright"].stop()
    except Exception:
        pass
    state["playwright"] = None
    state["browser"] = None
    state["context"] = None
    state["pages"].clear()


def _ensure_connected():
    ok = False
    try:
        ok = state["browser"] is not None and state["browser"].is_connected()
    except Exception:
        ok = False
    if not ok:
        connect_browser()


@pw_thread
def shutdown():
    """إغلاق صفحات البوت وفصل Playwright (بدون إغلاق كروم نفسه)."""
    for page in list(state["pages"].values()):
        try:
            page.close()
        except Exception:
            pass
    _cleanup_playwright()


# ============================================================
# الدخول للاجتماع
# ============================================================
def _click_join_and_wait(page, session_id, join_timeout_ms=60000, admit_timeout_ms=180000):
    """ينقر زر الانضمام (Join now / Ask to join) ثم ينتظر الدخول الفعلي للاجتماع."""
    waited = 0
    interval = 500
    asked_to_join = False
    joined_click = False

    while waited < join_timeout_ms:
        if "accounts.google.com" in page.url:
            raise MeetBotError("⚠️ انتهت صلاحية الجلسة، يتطلب تسجيل الدخول")

        # نافذة "متابعة بدون ميكروفون/كاميرا" إن ظهرت
        try:
            cont = page.get_by_role("button", name=CONTINUE_WITHOUT_RE).first
            if cont.count() and cont.is_visible():
                cont.evaluate("el => el.click()")
                page.wait_for_timeout(500)
        except Exception:
            pass

        try:
            btn = page.get_by_role("button", name=JOIN_RE).first
            if btn.count() and btn.is_visible():
                try:
                    text = (btn.inner_text() or "").lower()
                except Exception:
                    text = ""
                asked_to_join = ("ask" in text) or ("طلب" in text)
                btn.evaluate("el => el.click()")
                joined_click = True
                break
        except Exception:
            pass

        page.wait_for_timeout(interval)
        waited += interval

    if not joined_click:
        dump_debug(page, "join_button")
        raise MeetBotError(f"❌ [جلسة {session_id}] لم يظهر زر الانضمام")

    if asked_to_join:
        print(f"⏳ [جلسة {session_id}] تم طلب الانضمام، بانتظار موافقة المضيف...")
    wait_ms = admit_timeout_ms if asked_to_join else 30000

    try:
        page.wait_for_selector(LEAVE_SEL, state="attached", timeout=wait_ms)
    except PWTimeout:
        dump_debug(page, "join_wait")
        raise MeetBotError(
            f"❌ [جلسة {session_id}] لم يتم الدخول للاجتماع (لم تتم الموافقة أو انتهت المهلة)"
        )

    dismiss_popups(page)
    print(f"✅ [جلسة {session_id}] تم الدخول للاجتماع")


@pw_thread
def join_meeting(target, custom_link=None):
    _ensure_connected()

    session_id, link = extract_meet_info(target)
    if custom_link:
        _, link = extract_meet_info(custom_link)
        session_id = str(target)

    context = state["context"]
    old = state["pages"].pop(session_id, None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass

    page = context.new_page()
    apply_resource_limits(page)
    state["pages"][session_id] = page

    try:
        print(f"🔗 [جلسة {session_id}] جاري الدخول: {link}")
        page.goto(link, wait_until="domcontentloaded", timeout=60000)

        if "accounts.google.com" in page.url:
            raise MeetBotError("⚠️ انتهت صلاحية الجلسة، يتطلب تسجيل الدخول")

        _click_join_and_wait(page, session_id)
    except Exception:
        # لا نترك صفحة فاشلة معلّقة في الحالة
        state["pages"].pop(session_id, None)
        try:
            page.close()
        except Exception:
            pass
        raise

    try:
        context.storage_state(path=AUTH_FILE)
        try:
            os.chmod(AUTH_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass

    return session_id


# ============================================================
# التسجيل
# ============================================================
@pw_thread
def start_recording(num):
    page = _require_page(num)
    print(f"🔴 [محاضرة {num}] جاري بدء التسجيل...")

    open_recording_panel(page)

    ok = click_any(
        page,
        [
            page.get_by_role("button", name=START_REC_RE),
            page.locator(JS_START_REC),
        ],
        10000,
        "زر Start recording",
    )
    if not ok:
        dump_debug(page, "no_start_button")
        raise MeetBotError(
            "❌ لم يظهر زر Start recording (قد يكون التسجيل يعمل بالفعل)"
        )

    page.wait_for_timeout(1000)

    # نافذة التأكيد (قد لا تظهر في بعض الإصدارات)
    confirmed = click_any(
        page,
        [dialog_button(page, START_CONFIRM_RE), page.locator(JS_DIALOG_CONFIRM)],
        8000,
        "زر التأكيد",
    )
    if not confirmed:
        print("   ℹ️ لم تظهر نافذة تأكيد (قد لا تكون مطلوبة)، سيتم التحقق من الحالة")

    result = _verify_started(page)
    if ALWAYS_DEBUG:
        dump_debug(page, "after_start")

    if result == "active":
        print(f"✅ [محاضرة {num}] بدأ التسجيل بنجاح!")
        return "✅ بدأ التسجيل بنجاح في Google Meet!"
    if result == "idle":
        raise MeetBotError("❌ تم الضغط لكن التسجيل لم يبدأ (زر Start recording ما زال ظاهراً)")
    print(f"⚠️ [محاضرة {num}] لم أستطع التحقق من حالة التسجيل")
    return "⚠️ تم الضغط على أزرار التسجيل لكن تعذر التأكد من البدء، تحقق يدوياً"


@pw_thread
def stop_recording(num):
    page = _require_page(num)
    print(f"🛑 [محاضرة {num}] جاري إيقاف التسجيل...")

    open_recording_panel(page)

    ok = click_any(
        page,
        [
            page.get_by_role("button", name=STOP_REC_RE),
            page.locator(JS_STOP_REC),
        ],
        10000,
        "زر Stop recording",
    )
    if not ok:
        dump_debug(page, "no_stop_button")
        raise MeetBotError("❌ لم يظهر زر Stop recording (ربما التسجيل غير مفعّل)")

    page.wait_for_timeout(1000)

    confirmed = click_any(
        page,
        [dialog_button(page, STOP_CONFIRM_RE), page.locator(JS_DIALOG_CONFIRM)],
        8000,
        "زر تأكيد الإيقاف",
    )
    if not confirmed:
        dump_debug(page, "no_stop_confirm")
        raise MeetBotError("❌ لم يظهر زر تأكيد إيقاف التسجيل")
    page.wait_for_timeout(2000)
    result = _recording_state(page, reopen=True, timeout_ms=8000)
    if ALWAYS_DEBUG:
        dump_debug(page, "after_stop")

    if result == "active":
        raise MeetBotError("❌ تم الضغط لكن التسجيل ما زال يعمل (زر Stop recording ظاهر)")
    if result == "unknown":
        print(f"⚠️ [محاضرة {num}] لم أستطع التحقق من الإيقاف")
        return "⚠️ تم الضغط على أزرار الإيقاف لكن تعذر التأكد، تحقق يدوياً"

    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")
    return "🛑 تم إيقاف التسجيل بنجاح!"


# ============================================================
# المغادرة وإعادة الدخول
# ============================================================
@pw_thread
def leave_meeting(num, end_for_all=True):
    """مغادرة الاجتماع. end_for_all=True ينهي المكالمة للجميع (إن ظهر الخيار)."""
    page = _require_page(num)
    print(f"🚪 [محاضرة {num}] جاري المغادرة...")

    if not wait_and_click(page, LEAVE_SEL, 10000, "زر Leave call"):
        dump_debug(page, "no_leave_button")
        raise MeetBotError("❌ لم يظهر زر Leave call")

    if end_for_all:
        click_any(
            page,
            [dialog_button(page, END_FOR_ALL_RE), page.locator(JS_END_FOR_ALL)],
            5000,
            "زر End call for everyone",
        )

    page.wait_for_timeout(1000)
    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(str(num), None)
    print(f"✅ [محاضرة {num}] تمت المغادرة")
    return "🚪 تمت مغادرة الاجتماع بنجاح!"


@pw_thread
def refresh_and_rejoin(num):
    page = _require_page(num)
    print(f"🔄 [محاضرة {num}] جاري التحديث وإعادة الدخول...")

    page.reload(wait_until="domcontentloaded", timeout=60000)
    if "accounts.google.com" in page.url:
        raise MeetBotError("⚠️ انتهت صلاحية الجلسة، يتطلب تسجيل الدخول")

    _click_join_and_wait(page, str(num))
    print(f"✅ [محاضرة {num}] تم إعادة الدخول بنجاح")
    return "🔄 تم تحديث الصفحة وإعادة الدخول بنجاح!"
