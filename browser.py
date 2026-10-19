import os
import time
from playwright.sync_api import sync_playwright

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
            print(f"⏳ الاتصال بـ Browserless (محاولة {attempt}/{max_attempts})...")
            state["browser"] = state["playwright"].chromium.connect_over_cdp(BROWSERLESS_WS)
            
            permissions = ["microphone", "camera", "notifications"]
            
            if os.path.exists("auth.json"):
                print("🔑 تم العثور على auth.json - تطبيق الجلسة...")
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
            print("✅ تم الاتصال بنجاح!")
            return
        except Exception as e:
            print(f"⚠️ محاولة {attempt} فشلت: {e}")
            time.sleep(2)

    raise Exception("❌ فشل الاتصال. تأكد من عمل سيرفر Browserless.")

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
    ensure_connection()
    context = state["context"]
    page = context.new_page()

    print("🌐 جاري فتح صفحة تسجيل الدخول...")
    page.goto('https://accounts.google.com', timeout=0)

    # 5 دقائق مهلة للتسجيل اليدوي
    page.wait_for_timeout(300000)

    context.storage_state(path="auth.json")
    print("💾 تم حفظ ملف الجلسة auth.json داخل السيرفر!")
    
    try:
        page.close()
    except:
        pass
    return "✅ انتهت المهلة وتم حفظ الجلسة داخل السيرفر بنجاح!"

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

    print(f"🔗 جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    current_url = page.url
    if "accounts.google.com" in current_url:
        try:
            page.screenshot(path="error_screen.png")
        except:
            pass
        raise Exception("⚠️ الحساب يطلب تسجيل الدخول! أرسل أمر /login لتوثيق الجلسة أولاً.")

    try:
        page.keyboard.down('Control')
        page.keyboard.press('d')
        page.keyboard.press('e')
        page.keyboard.up('Control')
    except:
        pass

    join_selector = "button:has-text('Join now'), button:has-text('Ask to join'), button:has-text('الانضمام الآن'), button:has-text('طلب الانضمام')"

    try:
        join_button = page.locator(join_selector).first
        join_button.wait_for(timeout=20000)
        join_button.click()
        
        page.wait_for_timeout(3000)
        page.screenshot(path="success_screen.png")
        context.storage_state(path="auth.json")
        return "✅ تم الضغط على زر الانضمام!"
    except Exception as e:
        try:
            page.screenshot(path="error_screen.png")
        except:
            pass
        raise Exception(f"فشل إيجاد زر الانضمام. (الصفحة: {page.title()})")

def start_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception("المحاضرة غير مفتوحة")

    page.locator('button[aria-label="More options"], button[aria-label="خيارات إضافية"]').first.click()
    page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first.click()
    
    try:
        page.click('[aria-label="Start recording"]', timeout=8000)
    except:
        page.click('[jsname="A0ONe"]', timeout=8000)

    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    return "✅ بدأ التسجيل!"

def stop_recording(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page:
        raise Exception("المحاضرة غير مفتوحة")

    page.locator('button[aria-label="More options"], button[aria-label="خيارات إضافية"]').first.click()
    page.locator('li:has-text("Recording"), li:has-text("التسجيل")').first.click()
    page.click('[jsname="ahMSA"]', timeout=15000)
    page.click('[data-mdc-dialog-action="A9Emjd"]', timeout=10000)
    return "✅ تم إيقاف التسجيل!"

def leave_meeting(num="1"):
    ensure_connection()
    page = get_page(num)
    if not page: return "المحاضرة غير مفتوحة"

    try:
        page.click('[aria-label="Leave call"]', timeout=10000)
        page.click('[data-mdc-dialog-action="rbwiRc"]', timeout=8000)
        page.close()
    except:
        pass
    state["pages"].pop(str(num), None)
    return "✅ تمت المغادرة"
