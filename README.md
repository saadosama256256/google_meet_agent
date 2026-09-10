# نشر بوت تسجيل Google Meet على سيرفر Coolify (بموارد محدودة)

## اكتشاف مهم غيّر الخطة
التسجيل بيحصل عند جوجل نفسها (زرار "Manage recording" جوه Meet) — مش تصوير شاشة/صوت محلي. يعني التشغيل العادي مش محتاج Xvfb/PulseAudio ويقدر يبقى headless حقيقي وخفيف على الرام.

لكن عملية الـ **Login الأول** بتحتاج واجهة رسومية عشان تدخل كود التحقق، فبنيت وضعين في نفس الـ container:
- `MODE=login` → مؤقت، بيشغّل شاشة افتراضية + VNC عشان تسجل دخول
- `MODE=run` → الوضع العادي، Chrome headless + البوت شغال

## خطوة 1: تجهيز السيرفر (مرة واحدة)
```bash
chmod +x setup-swap.sh
sudo ./setup-swap.sh
```

## خطوة 2: ملفات الكود
حط `bot1.py`, `browser.py`, `config.py` (وأي ملف تاني) جنب الملفات دي.
تأكد إن `config.py` فيه `TELEGRAM_TOKEN` و`ALLOWED_USER_ID` صح.

## خطوة 3: تعديل كلمة سر VNC
في `docker-compose.yml`، غيّر:
```yaml
- VNC_PASSWORD=changeme
```
لكلمة سر قوية بتختارها إنت — دي هتحمي جلسة الـ Login وقت ما تكون شغالة.

## خطوة 4: تشغيل وضع الـ Login (مؤقت)
```bash
docker compose up -d --build
```
(تأكد إن `MODE=run` لسه في الـ compose — هنغيره دلوقتي لـ login فعليًا)

عدّل في `docker-compose.yml`:
```yaml
- MODE=login
```
وأعد التشغيل:
```bash
docker compose up -d --build
```

### الاتصال بـ VNC بأمان (عن طريق SSH tunnel)
من جهازك (مش من السيرفر):
```bash
ssh -L 5900:localhost:5900 root@YOUR_SERVER_IP
```
سيب الـ terminal ده شغال، وافتح برنامج VNC Viewer (زي TigerVNC أو RealVNC) واتصل بـ:
```
localhost:5900
```
هيطلب كلمة السر اللي حطيتها في `VNC_PASSWORD`.

### تسجيل الدخول
- هتلاقي Chrome فاتح على صفحة تسجيل دخول جوجل
- سجّل دخول بالحساب المطلوب (Noorsen)، ودخّل كود التحقق لما يتطلب
- بعد ما تخلص Login بنجاح وتوصل لصفحة Google العادية، **قفل نافذة Chrome من جوه VNC** (البروفايل بيتحفظ أوتوماتيك في الـ volume)

## خطوة 5: الرجوع للوضع العادي
عدّل تاني في `docker-compose.yml`:
```yaml
- MODE=run
```
وأعد التشغيل:
```bash
docker compose up -d --build
```
دلوقتي Chrome هيشتغل headless بنفس البروفايل المسجل دخول، والبوت هيشتغل عادي.

## خطوة 6: التحقق
```bash
docker logs -f meet-recording-bot     # نتأكد إن Chrome اتصل صح والبوت شغال
docker stats meet-recording-bot       # نراقب استهلاك الرام لحظيًا
```
جرّب تبعت رابط اجتماع قصير للبوت على تليجرام.

## ⚠️ تنبيهات أمان
- **مايتفتحش بورت 5900 للإنترنت مباشرة** — الإعداد في `docker-compose.yml` بيقصره على `127.0.0.1` قصدًا، فمينفعش يتوصله إلا عن طريق SSH tunnel. متغيرش ده.
- بعد ما تخلص الـ login، ارجع `MODE=run` فورًا — سيبان وضع login شغال يزود استهلاك الرام من غير داعي.
- الجلسة ممكن تنتهي بعد فترة وتحتاج تكرار الخطوات دي تاني.

## الملفات في المجلد ده
| الملف | الغرض |
|---|---|
| `setup-swap.sh` | يضيف swap file 2GB على السيرفر (مرة واحدة، خارج الـ container) |
| `Dockerfile` | Python + Google Chrome + أدوات Login المؤقتة (Xvfb/x11vnc/fluxbox) |
| `entrypoint.sh` | بيقرر يشغّل وضع login (VNC) ولا وضع run (headless) حسب `MODE` |
| `docker-compose.yml` | إعدادات الحدود، البورتات، الـ volume، ومتغير `MODE`/`VNC_PASSWORD` |
| `requirements.txt` | مكتبات Python |
