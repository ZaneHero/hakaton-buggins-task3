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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import asyncio
from prometheus_client import start_http_server, Summary, Counter, Histogram, generate_latest, REGISTRY
from prometheus_client.core import CollectorRegistry
from starlette.responses import Response

#создаем метрики
REQUEST_COUNT = Counter('http_requests_total', 'Total number of HTTP requests', ['method', 'endpoint'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])

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
CLIENT_SECRETS_FILE = "/app/credentials/client_secrets.json"  # путь к вашему клиентскому секрету OAuth 2.0
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly', 
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify' ]
REDIRECT_URI = "https://testing.lazy.delivery/callback"

# Инициализация потока авторизации
flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

# Путь для хранения зашифрованных учетных данных
CREDENTIALS_FILE = '/app/credentials/credentials.json'

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
        fields="nextPageToken, files(id, name, mimeType, parents, owners, createdTime)"
    ).execute()
    items = results.get('files', [])
    while 'nextPageToken' in results:
        page_token = results['nextPageToken']
        results = service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id, name, mimeType, parents, owners, createdTime)",
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

@app.get("/callback")
async def oauth2_callback(request: Request):
    code = request.query_params.get('code')
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        save_credentials(credentials)
        return JSONResponse({"message": "Authorization successful."})
    except Exception as e:
        logger.error(f"Error during OAuth callback: {e}")
        raise HTTPException(status_code=400, detail="Authorization failed")

@app.get("/files")
async def list_files():
    credentials = load_credentials()
    if not credentials or not credentials.valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        service = build('drive', 'v3', credentials=credentials)
        # Ищем начальную папку
        response = service.files().list(
            q="name='Baggins Coffee' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)"
        ).execute()
        root_folder = response.get('files', [])
        if not root_folder:
            raise HTTPException(status_code=404, detail="Baggins Coffee folder not found")
        
        root_folder_id = root_folder[0]['id']
        all_files = list_all_files(service, root_folder_id)

        if not all_files:
            return {"files": []}

        one_hour_ago = datetime.utcnow() - timedelta(minutes=20)
        kolomojcysuai_email = 'kolomojcysuai@gmail.com'
        
        files = []
        for item in all_files:
            created_time = datetime.strptime(item['createdTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
            if created_time < one_hour_ago:
                owner_emails = [owner['emailAddress'] for owner in item.get('owners', [])]
                if kolomojcysuai_email not in owner_emails:
                    files.append({
                        "id": item["id"],
                        "name": item["name"],
                        "createdTime": item["createdTime"],
                        "owners": owner_emails
                    })

        return {"files": files}
    except Exception as e:
        logger.error(f"Error fetching files: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch files")

@app.get("/file-hierarchy/{file_id}")
async def get_file_hierarchy_route(file_id: str):
    credentials = load_credentials()
    if not credentials or not credentials.valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        service = build('drive', 'v3', credentials=credentials)
        hierarchy = get_file_hierarchy(service, file_id)
        return {"hierarchy": hierarchy}
    except Exception as e:
        logger.error(f"Error fetching file hierarchy: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch file hierarchy")

def get_file_hierarchy(service, file_id):
    """Возвращает иерархию папок для указанного файла."""
    hierarchy = []
    current_id = file_id
    while current_id:
        file = service.files().get(fileId=current_id, fields="id, name, parents").execute()
        hierarchy.insert(0, {"id": file["id"], "name": file["name"]})
        parents = file.get("parents")
        current_id = parents[0] if parents else None
    return hierarchy

@app.post("/copy-files/{email}")
async def copy_files(email: str):
    credentials = load_credentials()
    if not credentials or not credentials.valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        service = build('drive', 'v3', credentials=credentials)

        # Ищем все файлы, владельцем которых является email
        query = f"'{email}' in owners and trashed = false"
        response = service.files().list(q=query, fields="files(id, name, mimeType, parents)").execute()
        files_to_copy = response.get('files', [])

        for file in files_to_copy:
            # Получаем родительскую папку
            parent_ids = file.get('parents', [])
            if not parent_ids:
                continue
            
            copy_metadata = {
                'name': file['name'],
                'parents': parent_ids
            }
            service.files().copy(fileId=file['id'], body=copy_metadata).execute()

        return JSONResponse({"message": "Files copied successfully"})
    except Exception as e:
        logger.error(f"Error copying files: {e}")
        raise HTTPException(status_code=500, detail="Failed to copy files")
    

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    method = request.method
    endpoint = request.url.path

    REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
    start_time = time.time()
    
    response = await call_next(request)
    
    latency = time.time() - start_time
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)
    
    return response

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(REGISTRY), media_type="text/plain")


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
    options.add_argument("--headless")  # Запуск в фоновом режиме
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
        logger.info(f"2 window handles before switch: {driver.window_handles}")
        time.sleep(2)

        # Нахождение и нажатие кнопки "Responde" с использованием полного XPATH
        respond_button = wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div[2]/div/div[3]/div/div[2]/div[2]/div[1]/div/div[2]/div/div[3]/div[2]/div/div[3]/div/div/div/div/div/div[1]/div[2]/div[3]/div[3]/div[1]/div/table/tbody/tr/td/table/tbody/tr/td/table[1]/tbody/tr/td/div[2]/a')))
        respond_button.click()
        logger.info("Clicked the 'Responde' button.")
        time.sleep(10)

        # Ожидание открытия новой вкладки и переключение на неё
        wait.until(EC.number_of_windows_to_be(3))  # Ожидание открытия новой вкладки
        logger.info(f"All window handles before switch: {driver.window_handles}")
        driver.switch_to.window(driver.window_handles[-1])  # Переключение на последнюю открытую вкладку
        logger.info(f"Current window handle after switch: {driver.current_window_handle}")
        time.sleep(5)


        actions = ActionChains(driver)
        actions.send_keys(Keys.RETURN).perform()
        print("Pressed the 'Enter' key.")

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