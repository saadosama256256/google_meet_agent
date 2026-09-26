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
    """ضغطة ماوس حقيقية بإحداثيات الشاشة لتخطي أي Overlay شفاف"""
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
    """انتظار ذكي حتى يظهر العنصر ثم ضغط حقيقي بالماوس"""
    waited = 0
    interval = 300
    while waited < timeout_ms:
        coords = get_coords(page, selector)
        if coords:
            real_click(page, coords['x'], coords['y'])
            print(f"   {label} ✅ (بعد {waited}ms)")
            return True
        page.wait_for_timeout(interval)
        waited += interval
    print(f"   ❌ {label} لم يظهر خلال {timeout_ms}ms")
    return False

def wake_up_controls(page):
    """تحريك الماوس لإظهار شريط الأدوات السفلي في حال اختفائه تلقائياً"""
    page.mouse.move(500, 500)
    page.wait_for_timeout(200)
    page.mouse.move(960, 540)
    page.wait_for_timeout(300)

def open_more_options(page):
    """فتح قائمة النقاط الثلاث بأمان مع التأكد من ظهور الشريط"""
    wake_up_controls(page)
    
    # التحقق أولاً إذا كانت القائمة مفتوحة بالفعل
    is_menu_open = page.locator("ul[role='menu'], div[role='menu']").is_visible()
    if is_menu_open:
        return

    btn = page.locator("button[aria-label*='options' i], button[aria-label*='المزيد' i], button[data-panel-id='quick-actions']").first
    btn.wait_for(state="attached", timeout=10000)
    btn.click(force=True)
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
    join_button.click()
    print(f"✅ [محاضرة {num_str}] تم الدخول للاجتماع")

    try:
        context.storage_state(path="auth.json")
        print("💾 تم تحديث auth.json")
    except Exception as e:
        print(f"⚠️ فشل تحديث auth.json: {e}")

def start_recording(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🔴 [محاضرة {num}] جاري بدء التسجيل...")

    # 1. فتح القائمة السفلية
    open_more_options(page)

    # 2. النقر على عنصر التسجيل عبر موقعه الفعلي بالشاشة لتجاوز الطبقات
    clicked_rec = page.evaluate('''() => {
        const allElements = Array.from(document.querySelectorAll('li, div, span, button'));
        const target = allElements.reverse().find(el => {
            const txt = (el.innerText || "").trim();
            return (txt === "Recording" || txt === "تسجيل" || txt.startsWith("Recording") || txt.startsWith("تسجيل")) && el.offsetParent !== null;
        });

        if (target) {
            const r = target.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }
        return null;
    }''')

    if clicked_rec:
        real_click(page, clicked_rec['x'], clicked_rec['y'])
        print("   تم الضغط على خيار Recording ✅")
    else:
        rec_locator = page.locator("text='Recording', text='تسجيل'").first
        rec_locator.wait_for(timeout=5000)
        rec_locator.click(force=True)

    page.wait_for_timeout(1500)

    # 3. الضغط على زر Start recording في اللوحة الجانبية
    start_btn_clicked = wait_and_click(page, '[jsname="A0ONe"]', 8000, "زر Start recording الأساسي")
    if not start_btn_clicked:
        start_btn = page.locator("button:has-text('Start recording'), button:has-text('بدء التسجيل')").first
        if start_btn.is_visible():
            start_btn.click(force=True)

    page.wait_for_timeout(1000)

    # 4. تأكيد التسجيل من النافذة المنبثقة
    confirm_clicked = wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 6000, "زر التأكيد")
    if not confirm_clicked:
        confirm_btn = page.locator("button:has-text('Start'), button:has-text('بدء')").first
        if confirm_btn.is_visible():
            confirm_btn.click(force=True)

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
            return (txt === "Recording" || txt === "تسجيل" || txt.startsWith("Recording") || txt.startsWith("تسجيل")) && el.offsetParent !== null;
        });

        if (target) {
            const r = target.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }
        return null;
    }''')

    if clicked_rec:
        real_click(page, clicked_rec['x'], clicked_rec['y'])

    page.wait_for_timeout(1500)

    # الضغط على زر Stop recording
    stop_clicked = wait_and_click(page, '[jsname="ahMSA"]', 8000, "زر Stop recording")
    if not stop_clicked:
        stop_btn = page.locator("button:has-text('Stop recording'), button:has-text('إيقاف التسجيل')").first
        if stop_btn.is_visible():
            stop_btn.click(force=True)

    page.wait_for_timeout(1000)
    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 6000, "زر تأكيد الإيقاف")

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
    join_button.click()
    print(f"✅ [محاضرة {num}] تم إعادة الدخول بنجاح")
