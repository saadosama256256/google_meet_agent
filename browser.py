from playwright.sync_api import sync_playwright
import time

state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "pages": {},
}

def connect_browser():
    state["playwright"] = sync_playwright().start()
    max_attempts = 20
    for attempt in range(1, max_attempts + 1):
        try:
            state["browser"] = state["playwright"].chromium.connect_over_cdp("http://localhost:9223")
            context = state["browser"].contexts[0]
            state["context"] = context
            print("✅ تم الاتصال بمتصفح Chrome (Profile 1)")
            return
        except Exception:
            print(f"⏳ محاولة {attempt}/20: كروم غير جاهز بعد، إعادة المحاولة...")
            time.sleep(2)
    raise Exception("❌ فشل الاتصال بكروم. تأكد من تشغيله على بورت 9223")

def get_page(num):
    return state["pages"].get(str(num))

def list_open_meetings():
    return list(state["pages"].keys())

def real_click(page, x, y):
    """ضغطة ماوس حقيقية بإحداثيات الشاشة"""
    page.mouse.move(x, y)
    page.wait_for_timeout(200)
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.up()

def get_coords(page, selector):
    return page.evaluate(f"""
        () => {{
            const btn = document.querySelector('{selector}');
            if (!btn) return null;
            const r = btn.getBoundingClientRect();
            return {{ x: r.x + r.width / 2, y: r.y + r.height / 2 }};
        }}
    """)

def wait_and_click(page, selector, timeout_ms=15000, label=""):
    """انتظار ذكي ثم النقر عبر جافاسكربت لتخطي الطبقات الشفافة تماماً"""
    waited = 0
    interval = 300
    while waited < timeout_ms:
        # البحث عن العنصر في DOM والنقر عليه مباشرة (أقوى طريقة لـ Meet)
        clicked = page.evaluate(f"""() => {{
            const btn = document.querySelector('{selector}');
            if (btn && btn.offsetParent !== null) {{
                btn.click();
                return true;
            }}
            return false;
        }}""")
        if clicked:
            print(f"   {label} ✅ (بعد {waited}ms)")
            return True
        page.wait_for_timeout(interval)
        waited += interval
    print(f"   ❌ {label} لم يظهر خلال {timeout_ms}ms")
    return False

def wake_up_controls(page):
    """تحريك الماوس لإجبار الشريط السفلي على الظهور"""
    page.mouse.move(500, 500)
    page.wait_for_timeout(200)
    page.mouse.move(960, 540)
    page.wait_for_timeout(300)

def open_more_options(page):
    """فتح القائمة السفلية مع تجنب أزرار المشتركين تماماً"""
    wake_up_controls(page)
    
    if page.locator("ul[role='menu'], div[role='menu']").is_visible():
        return

    # استخدام التطابق التام (Exact Match) لضمان عدم التقاط زر فيديو المشترك
    btn = page.locator('button[aria-label="More options"], button[aria-label="المزيد من الخيارات"]').first
    
    try:
        btn.wait_for(state="attached", timeout=8000)
        # النقر المباشر (DOM Click) لتجاوز خطأ التمرير (scrolling into view)
        btn.evaluate("el => el.click()")
    except:
        # خطة بديلة باستخدام دور العنصر
        fallback = page.get_by_role("button", name="More options", exact=True)
        fallback.evaluate("el => el.click()")
        
    page.wait_for_timeout(1000)

def join_meeting(num, link):
    num_str = str(num)
    context = state["context"]
    if num_str in state["pages"]:
        try:
            state["pages"][num_str].close()
        except Exception:
            pass

    page = context.new_page()
    state["pages"][num_str] = page

    print(f"🔗 [محاضرة {num_str}] جاري الدخول: {link}")
    page.goto(link, wait_until="domcontentloaded", timeout=60000)

    if "accounts.google.com" in page.url:
        raise Exception("⚠️ انتهت صلاحية الجلسة، يتطلب تسجيل الدخول")

    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    
    # تجنب أي تعليق أثناء الضغط على زر الانضمام
    join_button.evaluate("el => el.click()")
    print(f"✅ [محاضرة {num_str}] تم الدخول للاجتماع")

    try:
        context.storage_state(path="auth.json")
    except Exception:
        pass

def start_recording(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🔴 [محاضرة {num}] جاري بدء التسجيل...")

    open_more_options(page)

    clicked_rec = page.evaluate('''() => {
        const allElements = Array.from(document.querySelectorAll('li, div, span, button'));
        const target = allElements.reverse().find(el => {
            const txt = (el.innerText || "").trim();
            return (txt === "Recording" || txt === "تسجيل" || txt === "Manage recording") && el.offsetParent !== null;
        });

        if (target) {
            target.click(); // النقر البرمجي هو الأضمن هنا
            return true;
        }
        return false;
    }''')

    if clicked_rec:
        print("   تم الضغط على خيار Recording ✅")
    else:
        raise Exception("❌ لم يتم العثور على خيار التسجيل في القائمة")

    page.wait_for_timeout(1500)

    # الضغط على زر Start recording الجانبي
    success = wait_and_click(page, '[jsname="A0ONe"]', 10000, "زر Start recording")
    if not success:
        fallback = page.locator("button:has-text('Start recording'), button:has-text('بدء التسجيل')").first
        if fallback.is_visible():
            fallback.evaluate("el => el.click()")

    page.wait_for_timeout(1000)

    # زر التأكيد
    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 8000, "زر التأكيد")

    print(f"✅ [محاضرة {num}] بدأ التسجيل بنجاح!")
    return "✅ بدأ التسجيل بنجاح في Google Meet!"

def stop_recording(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🛑 [محاضرة {num}] جاري إيقاف التسجيل...")

    open_more_options(page)

    clicked_rec = page.evaluate('''() => {
        const allElements = Array.from(document.querySelectorAll('li, div, span, button'));
        const target = allElements.reverse().find(el => {
            const txt = (el.innerText || "").trim();
            return (txt === "Recording" || txt === "تسجيل" || txt === "Manage recording") && el.offsetParent !== null;
        });

        if (target) {
            target.click();
            return true;
        }
        return false;
    }''')

    page.wait_for_timeout(1500)

    wait_and_click(page, '[jsname="ahMSA"]', 10000, "زر Stop recording")
    page.wait_for_timeout(1000)
    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 8000, "زر تأكيد الإيقاف")

    print(f"✅ [محاضرة {num}] تم إيقاف التسجيل")
    return "🛑 تم إيقاف التسجيل بنجاح!"

def leave_meeting(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🚪 [محاضرة {num}] جاري المغادرة...")
    wait_and_click(page, '[aria-label="Leave call"], [aria-label="مغادرة المكالمة"]', 10000, "زر Leave call")
    wait_and_click(page, '[data-mdc-dialog-action="rbwiRc"]', 8000, "زر End call for everyone")

    try:
        page.close()
    except Exception:
        pass
    state["pages"].pop(str(num), None)
    print(f"✅ [محاضرة {num}] تمت المغادرة")
    return "🚪 تمت مغادرة الاجتماع بنجاح!"

def refresh_and_rejoin(num):
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
    join_button.evaluate("el => el.click()")
    print(f"✅ [محاضرة {num}] تم إعادة الدخول بنجاح")
