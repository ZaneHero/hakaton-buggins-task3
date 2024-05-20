from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
import json
import logging
import base64
from datetime import datetime, timedelta
import time
import imaplib
from email.header import decode_header
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Получение значения SECRET_KEY из переменных окружения
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set in the environment variables")

# Проверка и декодирование ключа
try:
    key = base64.urlsafe_b64decode(SECRET_KEY)
    if len(key) != 32:
        raise ValueError("Invalid Fernet key length")
except Exception as e:
    raise ValueError("Fernet key must be 32 url-safe base64-encoded bytes.") from e

fernet = Fernet(base64.urlsafe_b64encode(key))

app = FastAPI()

# Настройки OAuth 2.0
CLIENT_SECRETS_FILE = "client_secrets.json"  # путь к вашему клиентскому секрету OAuth 2.0
SCOPES = [
    'https://www.googleapis.com/auth/drive.metadata.readonly', 
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'  # Добавляем разрешение на изменение статуса писем
]
REDIRECT_URI = "http://localhost:8000/callback"

# Инициализация потока авторизации
flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

# Путь для хранения зашифрованных учетных данных
CREDENTIALS_FILE = 'credentials.json'

def encrypt_data(data):
    return fernet.encrypt(json.dumps(data).encode()).decode()

def decrypt_data(data):
    return json.loads(fernet.decrypt(data.encode()).decode())

def save_credentials(credentials):
    encrypted_credentials = encrypt_data({
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    })
    with open(CREDENTIALS_FILE, 'w') as file:
        file.write(encrypted_credentials)

def load_credentials():
    if not os.path.exists(CREDENTIALS_FILE):
        return None

    with open(CREDENTIALS_FILE, 'r') as file:
        encrypted_credentials = file.read()

    data = decrypt_data(encrypted_credentials)
    return Credentials(
        token=data['token'],
        refresh_token=data['refresh_token'],
        token_uri=data['token_uri'],
        client_id=data['client_id'],
        client_secret=data['client_secret'],
        scopes=data['scopes']
    )

def list_all_files(service, folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    results = service.files().list(
        q=query,
        pageSize=1000,
        fields="nextPageToken, files(id, name, mimeType, owners, createdTime)"
    ).execute()
    items = results.get('files', [])
    while 'nextPageToken' in results:
        page_token = results['nextPageToken']
        results = service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id, name, mimeType, owners, createdTime)",
            pageToken=page_token
        ).execute()
        items.extend(results.get('files', []))

    all_files = []
    for item in items:
        all_files.append(item)
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            all_files.extend(list_all_files(service, item['id']))

    return all_files

@app.get("/authorize")
async def authorize():
    authorization_url, _ = flow.authorization_url(prompt='consent')
    return RedirectResponse(authorization_url)


# Новый роутер для выполнения задачи с использованием imaplib и selenium
@app.post("/check-emails/")
async def check_emails(background_tasks: BackgroundTasks):
    background_tasks.add_task(check_and_process_emails)
    return {"message": "Started checking emails"}

# Подключение к почтовому ящику
def connect_to_mail():
    creds = load_credentials()
    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    return service

# Получение новых писем
def get_unread_emails(service):
    results = service.users().messages().list(userId='me', q='is:unread').execute()
    messages = results.get('messages', [])
    return messages

# Проверка и обработка новых писем
def check_and_process_emails():
    try:
        service = connect_to_mail()
        email_ids = get_unread_emails(service)
        for e_id in email_ids:
            msg = service.users().messages().get(userId='me', id=e_id['id']).execute()
            email_from = None
            headers = msg.get('payload', {}).get('headers', [])
            for header in headers:
                if header['name'] == 'From':
                    email_from = header['value']
                    break

            if email_from and "drive-shares-dm-noreply@google.com" in email_from:
                # Инициализация Selenium для автоматического нажатия "Accept"
                accept_invitation(e_id['id'])

                # Пометить письмо как прочитанное
                service.users().messages().modify(userId='me', id=e_id['id'], body={'removeLabelIds': ['UNREAD']}).execute()
    except Exception as e:
        logger.error(f"An error occurred: {e}")

def accept_invitation(email_id):
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-dev-shm-usage")
    #options.add_argument("--headless")  # Запуск в фоновом режиме
    driver = webdriver.Chrome(service=service, options=options)
    logger.info("Chrome driver initialized.")

    try:
        # Открытие Gmail
        driver.get("https://mail.google.com/")
        wait = WebDriverWait(driver, 30)

        # Вход в Google аккаунт
        email_input = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='email']")))
        email_input.send_keys(os.getenv("GMAIL_USERNAME"))
        email_input.send_keys(Keys.RETURN)
        time.sleep(2)

        password_input = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='password']")))
        password_input.send_keys(os.getenv("GMAIL_PASSWORD"))
        password_input.send_keys(Keys.RETURN)
        time.sleep(5)

        # Ожидание загрузки инбокса
        wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='main']")))

        # Открытие письма по ID
        email_url = f"https://mail.google.com/mail/u/0/#inbox/{email_id}"
        driver.get(email_url)
        logger.info(f"Opened the email with ID {email_id}")
        time.sleep(2)

        # Нахождение и нажатие кнопки "In new window" с использованием полного XPATH
        new_window_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[7]/div[3]/div/div[2]/div[2]/div/div/div/div[2]/div/div[1]/div/div[2]/div/div[2]/div[1]/div/div[1]/div/span[4]/button/div')))
        new_window_button.click()
        time.sleep(1)  # Ожидание после нажатия
        logger.info("Clicked the 'In new window' button.")

        # Переключение на новую вкладку
        wait.until(EC.number_of_windows_to_be(2))  # Ожидание открытия второй вкладки
        driver.switch_to.window(driver.window_handles[-1])  # Переключение на последнюю открытую вкладку
        logger.info("Switched to new tab.")
        time.sleep(2)

        # Нахождение и нажатие кнопки "Responde" с использованием полного XPATH
        respond_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div[2]/div/div[3]/div/div[2]/div[2]/div[1]/div/div[2]/div/div[3]/div[2]/div/div[3]/div/div/div/div/div/div[1]/div[2]/div[3]/div[3]/div[1]/div/table/tbody/tr/td/table/tbody/tr/td/table[1]/tbody/tr/td/div[2]/a')))
        respond_button.click()
        logger.info("Clicked the 'Responde' button.")
        time.sleep(10)

        # Ожидание открытия новой вкладки и переключение на неё
        wait.until(EC.number_of_windows_to_be(2))  # Ожидание открытия новой вкладки
        driver.switch_to.window(driver.window_handles[-1])  # Переключение на последнюю открытую вкладку
        logger.info("Switched to new tab after clicking 'Responde'.")
        time.sleep(5)
        x=400
        y=100
        driver.execute_script(f"document.elementFromPoint({x}, {y}).click();")
        logger.info("JsClicked")

        # iframe = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@class, 'share-client-content-iframe')]")))
        # logger.info("Iframe got")
        # driver.switch_to.frame(iframe)
        # logger.info("Iframe switched")

        # # Нахождение и нажатие кнопки "Done" с использованием полного XPATH
        # done_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Accept')]")))
        # done_button.click()                                            
        # logger.info("Clicked the 'Done' button.")
        # time.sleep(2)

    except Exception as e:
        logger.error(f"An error occurred while accepting the invitation: {e}")
    finally:
        driver.quit()
        logger.info("Chrome driver quit.")





# Новый роутер для получения ID письма
@app.get("/get-email-id/")
async def get_email_id():
    try:
        service = connect_to_mail()
        email_ids = get_unread_emails(service)
        for e_id in email_ids:
            msg = service.users().messages().get(userId='me', id=e_id['id']).execute()
            email_from = None
            headers = msg.get('payload', {}).get('headers', [])
            for header in headers:
                if header['name'] == 'From':
                    email_from = header['value']
                    break

            if email_from and "drive-shares-dm-noreply@google.com" in email_from:
                return {"email_id": e_id['id']}

        return {"message": "No unread emails from drive-shares-dm-noreply@google.com found"}
    except Exception as e:
        logger.error(f"An error occurred while fetching email ID: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch email ID")

# Инициализация планировщика
scheduler = AsyncIOScheduler()

# Добавление задачи в планировщик
@scheduler.scheduled_job('interval', minutes=1)
def scheduled_job():
    check_and_process_emails()

# Запуск планировщика при старте приложения
@app.on_event("startup")
async def startup_event():
    scheduler.start()

# Запуск приложения: uvicorn main:app --reload
