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
        raise Exception("⚠️ الجلسة منتهية، يتطلب تسجيل الدخول")

    join_button = page.locator(
        "button:has-text('Join now'), "
        "button:has-text('Join now without microphone'), "
        "button:has-text('الانضمام الآن')"
    ).first
    join_button.wait_for(timeout=60000)
    join_button.click()
    print(f"✅ [محاضرة {num_str}] تم الدخول للاجتماع")

def start_recording(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🔴 [محاضرة {num}] جاري بدء التسجيل...")

    # 1. فتح القائمة السفلية (More options)
    more_btn = page.locator("button[aria-label*='options' i], button[aria-label*='المزيد' i]").first
    more_btn.wait_for(timeout=15000)
    more_btn.click(force=True)
    page.wait_for_timeout(1000)

    # 2. النقر على Recording (سواء كان اسمها Recording أو Manage recording أو تسجيل)
    clicked_rec = page.evaluate('''() => {
        const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
        const item = items.find(el => 
            el.innerText.includes("Recording") || 
            el.innerText.includes("تسجيل") ||
            el.innerText.includes("Manage recording")
        );
        if (item) {
            const r = item.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }
        return null;
    }''')

    if clicked_rec:
        real_click(page, clicked_rec['x'], clicked_rec['y'])
        print("   زر Recording في القائمة ✅")
    else:
        raise Exception("❌ لم يتم العثور على خيار التسجيل في القائمة")

    page.wait_for_timeout(1500)

    # 3. الضغط على زر Start recording الفعلي في اللوحة الجانبية
    success = wait_and_click(page, '[jsname="A0ONe"]', 15000, "زر Start recording")
    if not success:
        wait_and_click(page, 'button:has-text("Start recording"), button:has-text("بدء التسجيل")', 8000, "زر البدء (fallback)")

    # 4. زر التأكيد في النافذة المنبثقة
    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 10000, "زر التأكيد")

    print(f"✅ [محاضرة {num}] بدأ التسجيل بنجاح!")
    return "✅ بدأ التسجيل بنجاح!"

def stop_recording(num):
    page = get_page(num)
    if not page:
        raise Exception(f"المحاضرة {num} غير مفتوحة")

    print(f"🛑 [محاضرة {num}] جاري إيقاف التسجيل...")

    more_btn = page.locator("button[aria-label*='options' i], button[aria-label*='المزيد' i]").first
    more_btn.wait_for(timeout=15000)
    more_btn.click(force=True)
    page.wait_for_timeout(1000)

    clicked_rec = page.evaluate('''() => {
        const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
        const item = items.find(el => 
            el.innerText.includes("Recording") || 
            el.innerText.includes("تسجيل") ||
            el.innerText.includes("Manage recording")
        );
        if (item) {
            const r = item.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }
        return null;
    }''')

    if clicked_rec:
        real_click(page, clicked_rec['x'], clicked_rec['y'])

    page.wait_for_timeout(1500)

    # زر Stop recording
    success = wait_and_click(page, '[jsname="ahMSA"]', 15000, "زر Stop recording")
    if not success:
        wait_and_click(page, 'button:has-text("Stop recording"), button:has-text("إيقاف التسجيل")', 8000, "زر الإيقاف (fallback)")

    # زر التأكيد
    wait_and_click(page, '[data-mdc-dialog-action="A9Emjd"]', 10000, "زر التأكيد")
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
