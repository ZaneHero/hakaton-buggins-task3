from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import os
import json
import logging
import base64
from datetime import datetime, timedelta
from prometheus_client import start_http_server, Summary, Counter, Histogram, generate_latest, REGISTRY
from prometheus_client.core import CollectorRegistry
from starlette.responses import Response
import time

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
CLIENT_SECRETS_FILE = "client_secrets"  # путь к вашему клиентскому секрету OAuth 2.0
SCOPES = ['https://www.googleapis.com/auth/drive']
REDIRECT_URI = "http://localhost:8000/callback"

# Инициализация потока авторизации
flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

# Путь для хранения зашифрованных учетных данных
CREDENTIALS_FILE = 'credentials'

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

