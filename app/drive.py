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

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Получение значения SECRET_KEY из переменных окружения
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set in the environment variables")

fernet = Fernet(SECRET_KEY)

app = FastAPI()

# Настройки OAuth 2.0
CLIENT_SECRETS_FILE = "client_secrets.json"  # путь к вашему клиентскому секрету OAuth 2.0
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']
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
        results = service.files().list(
            pageSize=10, fields="nextPageToken, files(id, name, mimeType)"
        ).execute()
        items = results.get('files', [])
        if not items:
            return {"files": []}
        
        files = []
        for item in items:
            files.append({
                "id": item["id"],
                "name": item["name"],
                "mimeType": item["mimeType"]
            })

        return {"files": files}
    except Exception as e:
        logger.error(f"Error fetching files: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch files")

# Запуск приложения: uvicorn main:app --reload
