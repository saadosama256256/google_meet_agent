FROM python:3.10-slim

WORKDIR /app

# نسخ ملف المطلببات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات البوت
COPY . .

# المنفذ المطلوب لـ FastAPI
EXPOSE 7860

# تشغيل البوت
CMD ["python", "bot1.py"]
