FROM python:3.11-slim[cite: 2]

# ============================================
# نستخدم Google Chrome الرسمي مع دعم الشاشة الافتراضية
# وأدوات البث المباشر عبر الويب (noVNC + websockify)
# ============================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation procps curl \
    xvfb x11vnc fluxbox novnc websockify \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*[cite: 2]

WORKDIR /app[cite: 2]

COPY requirements.txt .[cite: 2]
RUN pip install --no-cache-dir -r requirements.txt[cite: 2]

COPY . .[cite: 2]

ENV PYTHONUNBUFFERED=1[cite: 2]

# كشف منفذ البث الحي (6080) ومنفذ السيرفر الوهمي (7860)
EXPOSE 6080 7860

COPY entrypoint.sh /entrypoint.sh[cite: 2]
RUN chmod +x /entrypoint.sh[cite: 2]

ENTRYPOINT ["/entrypoint.sh"][cite: 2]
