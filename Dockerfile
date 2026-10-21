FROM python:3.10-slim

WORKDIR /app

# إنشاء مجلد دائم لحفظ ملف الجلسة الاحتياطي (يربط مع Persistent Volume في Coolify)
RUN mkdir -p /app/data

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات البوت
COPY . .

# تعريف المجلد الدائم كـ Volume لضمان عدم مسح auth.json عند تحديث الحاوية
VOLUME ["/app/data"]

# المنفذ المطلوب لـ FastAPI Healthcheck
EXPOSE 7860

# تشغيل البوت
CMD ["python", "bot1.py"]
