import os
import time
from playwright.sync_api import sync_playwright

# الرابط النظيف للاتصال بسيرفر Browserless
BROWSERLESS_WS = "wss://browserless.africanhouse.org?token=ZH9MFsE5RgM2KYrz9ELSz5VIOSgYDqJE"

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {}, 
}

def connect_browser():
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
            
            # إعداد الأذونات
            permissions = ["microphone", "camera", "notifications"]
            
            if os.path.exists("auth.json"):
                print("🔑 تم العثور على auth.json - جاري تطبيق الجلسة المحفوظة...")
                context = state["browser"].new_context(
                    storage_state="auth.json",
                    permissions=permissions,
                    viewport={"width": 1280, "height": 720}
                )
            else:
                context = state["browser"].new_context(
                    permissions=permissions,
                    viewport={"width": 1280, "height": 720}
                )

            state["context"] = context
            print("✅ تم الاتصال بنجاح بسيرفر Browserless!")
            return
        except Exception as e:
            print(f"⚠️ محاولة {attempt}/{max_attempts} فشلت: {e}")
            time.sleep(2)

    raise Exception("❌ فشل الاتصال بـ Browserless. تأكد من عمل السيرفر.")

def ensure_connection():
    try:
        if not state["browser"] or not state["browser"].is_connected():
            connect_browser()
        else:
            _ = state["context"].pages
    except Exception:
        connect_browser()

def get_page(num="1"):
    return state["pages"].get(str(num))

def manual_login():
    """تفتح صفحة تسجيل الدخول وتعطيك مهلة للتسجيل مع الحفاظ على الاتصال نشطاً لمنع الإغلاق"""
    ensure_connection()
    context = state["context"]
    page = context.new_page()

    print("🌐 جاري فتح صفحة تسجيل الدخول لحساب Google...")
    page.goto('https://accounts.google.com', timeout=0)

    print("⏰ الشاشة جاهزة. قم بتسجيل الدخول الآن من قائمة Sessions...")

    # حلقة نشطة (Keep-Alive) تمنع المتصفح من الإغلاق وتراقب نجاح الدخول
    for i in range(60):  # 60 مرة × 5 ثواني = 5 دقائق كحد أقصى
        page.wait_for_timeout(5000) # انتظار 5 ثواني
        try:
            # هذا الطلب يبقي الاتصال نشطاً ويمنع سيرفر Browserless من قطع الجلسة
            current_url = page.url 
            
            # إذا اكتشف البوت أنك أنهيت الدخول، سيخرج ويحفظ الجلسة فوراً
            if "myaccount.google.com" in current_url or "myactivity.google.com" in current_url:
                print("🎉 تم رصد تسجيل الدخول بنجاح!")
                break
        except Exception:
            pass

    # حفظ الجلسة داخل السيرفر
    context.storage_state(path="auth.json")
    print("💾 تم حفظ ملف الجلسة auth.json داخل السيرفر!")
    
    try:
        page.close()
    except:
        pass
    return "✅ تم حفظ جلسة الحساب (auth.json) بنجاح! يمكنك الآن إرسال روابط المحاضرات."

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
    state["pages"][num] = page

    print(f"🔗 [محاضرة {num}] جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    current_url = page.url
    if "accounts.google.com" in current_url:
        try:
            page.screenshot(path="error_screen.png")
        except:
            pass
        raise Exception("⚠️ الحساب يطلب تسجيل الدخول! أرسل أمر /login لتوثيق الجلسة أولاً.")

    # إغلاق المايك والكاميرا
    try:
        page.keyboard.down('Control')
        page.keyboard.press('d')
        page.keyboard.press('e')
        page.keyboard.up('Control')
    except Exception:
        pass

    join_selector = (
        "button:has-text('Join now'), "
        "button:has-text('Ask to join'), "
        "button:has-text('الانضمام الآن'), "
        "button:has-text('طلب الانضمام'), "
        "button:has-text('Join now without microphone')"
    )

    try:
        join_button = page.locator(join_selector).first
        join_button.wait_for(timeout=20000)
        join_button.click()
        print(f"✅ [محاضرة {num}] تم الضغط على زر الانضمام!")
        
        # التقاط صورة بعد الضغط لتأكيد الدخول وإرسالها للمستخدم
        page.wait_for_timeout(3000)
        page.screenshot(path="success_screen.png")
        
        # تجديد حفظ الجلسة بعد الدخول الناجح
        context.storage_state(path="auth.json")
        return "✅ تم الضغط على زر الانضمام وتم الدخول بنجاح!"
    except Exception as e:
        try:
            page.screenshot(path="error_screen.png")
        except:
            pass
        raise Exception(f"لم يتم العثور على زر الانضمام. (عنوان الصفحة: {page.title()})")

def start_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

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

    try:
        page.click('[aria-label="Start recording"]', timeout=8000)
    except Exception:
        page.click('[jsname="A0ONe"]', timeout=8000)

    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    print(f"✅ [محاضرة {num}] بدأ التسجيل!")
    return "✅ بدأ التسجيل!"

def stop_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

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
    return "✅ تم إيقاف التسجيل!"

def leave_meeting(num="1"):
    ensure_connection()
    num = str(num)
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

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
    return "✅ تمت المغادرة بنجاح!"

def refresh_and_rejoin(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
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
