import os
import time
from playwright.sync_api import sync_playwright

# رابط الاتصال بسيرفر Browserless عبر WebSocket
BROWSERLESS_WS = "wss://browserless.africanhouse.org?token=ZH9MFsE5RgM2KYrz9ELSz5VIOSgYDqJE&stealth=true"

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},  # {"1": page1, "2": page2, "3": page3}
}

def connect_browser():
    state["playwright"] = sync_playwright().start()

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"⏳ جاري الاتصال بـ Browserless (محاولة {attempt}/{max_attempts})...")
            state["browser"] = state["playwright"].chromium.connect_over_cdp(BROWSERLESS_WS)
            
            # تحميل ملف الجلسة auth.json إذا كان متوفراً أو إنشاء Context جديد بأذونات جاهزة
            if os.path.exists("auth.json"):
                print("🔑 تم العثور على auth.json - جاري تطبيق بيانات الجلسة...")
                context = state["browser"].new_context(
                    storage_state="auth.json",
                    permissions=["microphone", "camera", "notifications"]
                )
            else:
                print("🌐 استخدام سياق المتصفح المباشر من Browserless...")
                context = state["browser"].contexts[0] if state["browser"].contexts else state["browser"].new_context(
                    permissions=["microphone", "camera", "notifications"]
                )

            state["context"] = context
            print("✅ تم الاتصال بنجاح بسيرفر Browserless البعيد!")
            return
        except Exception as e:
            print(f"⚠️ محاولة {attempt}/{max_attempts} فشلت: {e}")
            time.sleep(3)

    raise Exception("❌ فشل الاتصال بـ Browserless. تأكد من عمل السيرفر وصحة الـ Token.")

def get_page(num="1"):
    """احصل على صفحة المحاضرة num، أو None إذا لم تكن مفتوحة"""
    return state["pages"].get(str(num))

def list_open_meetings():
    """أرجع قائمة بأرقام المحاضرات المفتوحة حالياً"""
    return list(state["pages"].keys())

def real_click(page, x, y):
    """ضغطة حقيقية كاملة: move ثم down ثم up"""
    page.mouse.move(x, y)
    page.wait_for_timeout(200)
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.up()

def get_coords(page, selector):
    """احصل على مركز العنصر فوراً (بدون انتظار)"""
    return page.evaluate(f"""
        () => {{
            const btn = document.querySelector('{selector}');
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {{ x: r.x + r.width / 2, y: r.y + r.height / 2 }};
        }}
    """)

def wait_and_click(page, selector, timeout_ms=15000, label=""):
    """
    ينتظر ظهور العنصر فعلياً (polling كل 300ms) حتى timeout،
    ثم يضغطه بضغطة حقيقية. يرجع True/False حسب النجاح.
    """
    waited = 0
    interval = 300
    while waited < timeout_ms:
        coords = get_coords(page, selector)
        if coords:
            real_click(page, coords['x'], coords['y'])
            print(f"   {label} ✅ (بعد {waited}ms انتظار)")
            return True
        page.wait_for_timeout(interval)
        waited += interval
    print(f"   ❌ {label} لم يظهر خلال {timeout_ms}ms")
    return False

def join_meeting(link, num="1"):
    num = str(num)
    context = state["context"]
    
    # إذا كانت مفتوحة مسبقاً، أغلقها أولاً
    if num in state["pages"]:
        try:
            state["pages"][num].close()
        except Exception:
            pass

    page = context.new_page()
    state["pages"][num] = page

    print(f"🔗 [محاضرة {num}] جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)

    # فحص: هل تحولنا لصفحة تسجيل دخول Google؟
    current_url = page.url
    if "accounts.google.com" in current_url:
        raise Exception(
            "⚠️ انتهت صلاحية جلسة Google! "
            "يلزم تحديث ملف الكوكيز أو auth.json"
        )

    # إغلاق الكاميرا والمايك تلقائياً لتخفيف الضغط على السيرفر
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

    # حفظ وتحديث حالة الجلسة
    try:
        context.storage_state(path="auth.json")
        print("💾 تم تحديث auth.json")
    except Exception as e:
        print(f"⚠️ فشل تحديث auth.json: {e}")

def start_recording(num="1"):
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

    success = wait_and_click(page, '[jsname="A0ONe"]', timeout_ms=15000, label="زر Start recording")
    if not success:
        success = wait_and_click(page, '[aria-label="Start recording"]', timeout_ms=8000, label="زر Start recording (aria-label)")

    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', timeout_ms=10000, label="زر التأكيد")
    print(f"✅ [محاضرة {num}] بدأ التسجيل!")

def stop_recording(num="1"):
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

    success = wait_and_click(page, '[jsname="ahMSA"]', timeout_ms=15000, label="زر Stop recording")
    if not success:
        print(f"❌ [محاضرة {num}] فشل إيقاف التسجيل")
        return

    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', timeout_ms=10000, label="زر التأكيد")
    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")

def leave_meeting(num="1"):
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🚪 [محاضرة {num}] جاري المغادرة...")

    wait_and_click(page, '[aria-label="Leave call"]', timeout_ms=10000, label="زر Leave call")
    wait_and_click(page, '[data-mdc-dialog-action="rbwiRc"]', timeout_ms=8000, label="زر End the call for everyone")

    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(num, None)

    print(f"✅ [محاضرة {num}] تمت المغادرة")

def refresh_and_rejoin(num="1"):
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
