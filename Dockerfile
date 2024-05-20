# syntax=docker/dockerfile:1

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1


RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    gnupg \
    --no-install-recommends

# Install Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable

# Install ChromeDriver
RUN CHROMEDRIVER_VERSION=$(curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE) && \
    wget -q "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip" -O /tmp/chromedriver.zip && \
    unzip /tmp/chromedriver.zip -d /usr/local/bin/ && \
    rm /tmp/chromedriver.zip

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.release:app", "--host", "0.0.0.0", "--port", "8000"]

   