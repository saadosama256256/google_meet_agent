import os
import time
from playwright.sync_api import sync_playwright

BROWSERLESS_WS = "wss://browserless.africanhouse.org?token=ZH9MFsE5RgM2KYrz9ELSz5VIOSgYDqJE&stealth=true"

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},  # {"1": page1, "2": page2, "3": page3}
}

def connect_browser():
    # إغلاق أي جلسات قديمة إن وجدت
    if state["playwright"]:
        try:
            state["playwright"].stop()
        except Exception:
            pass

    state["playwright"] = sync_playwright().start()

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"⏳ جاري الاتصال بـ Browserless (محاولة {attempt}/{max_attempts})...")
            state["browser"] = state["playwright"].chromium.connect_over_cdp(BROWSERLESS_WS)
            
            # إعداد الأذونات والكوكيز
            permissions = ["microphone", "camera", "notifications"]
            if os.path.exists("auth.json"):
                print("🔑 تم العثور على auth.json - جاري تطبيق بيانات الجلسة...")
                context = state["browser"].new_context(
                    storage_state="auth.json",
                    permissions=permissions
                )
            else:
                context = state["browser"].new_context(permissions=permissions)

            state["context"] = context
            print("✅ تم الاتصال بنجاح بسيرفر Browserless البعيد!")
            return
        except Exception as e:
            print(f"⚠️ محاولة {attempt}/{max_attempts} فشلت: {e}")
            time.sleep(2)

    raise Exception("❌ فشل الاتصال بـ Browserless. تأكد من عمل السيرفر.")

def ensure_connection():
    """تضمن أن الاتصال بـ Browserless ما زال حياً، وإذا انقطع تعيد الاتصال تلقائياً"""
    try:
        if not state["browser"] or not state["browser"].is_connected():
            print("🔄 الاتصال بـ Browserless غير نشط، جاري إعادة الاتصال...")
            connect_browser()
        else:
            # اختبار سريع لسلامة السياق (Context)
            _ = state["context"].pages
    except Exception:
        print("🔄 سياق المتصفح منتهي، جاري تجديد الاتصال...")
        connect_browser()

def get_page(num="1"):
    return state["pages"].get(str(num))

def join_meeting(link, num="1"):
    # التحقق من سلامة الاتصال وإعادة بنائه إذا انقطع
    ensure_connection()
    
    num = str(num)
    context = state["context"]

    if num in state["pages"]:
        try:
            state["pages"][num].close()
        except Exception:
            pass

    page = context.new_page()
    state["pages"][num] = page

    print(f"🔗 [محاضرة {num}] جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)

    current_url = page.url
    if "accounts.google.com" in current_url:
        raise Exception(
            "⚠️ انتهت صلاحية جلسة Google! "
            "يلزم تحديث ملف الكوكيز أو auth.json"
        )

    # إغلاق المايك والكاميرا فوراً لتوفير الاستهلاك
    page.wait_for_timeout(3000)
    try:
        page.keyboard.down('Control')
        page.keyboard.press('d')
        page.keyboard.press('e')
        page.keyboard.up('Control')
    except Exception:
        pass

    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    print(f"✅ [محاضرة {num}] تم الدخول بنجاح")

    try:
        context.storage_state(path="auth.json")
        print("💾 تم تحديث auth.json")
    except Exception as e:
        print(f"⚠️ فشل تحديث auth.json: {e}")

def start_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🔴 [محاضرة {num}] جاري بدء التسجيل...")
    more_btn = page.get_by_role("button", name="More options", exact=True)
    if not more_btn.is_visible():
        more_btn = page.locator('button[aria-label="More options"], button[aria-label="خيارات إضافية"]').first

    more_btn.wait_for(timeout=15000)
    more_btn.click()

    manage_item = page.get_by_role("menuitem", name="Manage recording")
    if not manage_item.is_visible():
        manage_item = page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first

    manage_item.wait_for(timeout=15000)
    manage_item.click()

    # محاولة الضغط على زر التسجيل
    try:
        page.click('[aria-label="Start recording"]', timeout=8000)
    except Exception:
        page.click('[jsname="A0ONe"]', timeout=8000)

    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] بدأ التسجيل!")

def stop_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🛑 [محاضرة {num}] جاري إيقاف التسجيل...")
    more_btn = page.get_by_role("button", name="More options", exact=True)
    if not more_btn.is_visible():
        more_btn = page.locator('button[aria-label="More options"], button[aria-label="خيارات إضافية"]').first

    more_btn.wait_for(timeout=15000)
    more_btn.click()

    manage_item = page.get_by_role("menuitem", name="Manage recording")
    if not manage_item.is_visible():
        manage_item = page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first

    manage_item.wait_for(timeout=15000)
    manage_item.click()

    page.click('[jsname="ahMSA"]', timeout=15000)
    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")

def leave_meeting(num="1"):
    ensure_connection()
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🚪 [محاضرة {num}] جاري المغادرة...")
    try:
        page.click('[aria-label="Leave call"]', timeout=10000)
        page.click('[data-mdc-dialog-action="rbwiRc"]', timeout=8000)
    except Exception:
        pass

    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(num, None)
    print(f"✅ [محاضرة {num}] تمت المغادرة")

def refresh_and_rejoin(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🔄 [محاضرة {num}] جاري التحديث وإعادة الدخول...")
    page.reload(wait_until="domcontentloaded", timeout=60000)
    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    print(f"✅ [محاضرة {num}] تم إعادة الدخول بنجاح")
