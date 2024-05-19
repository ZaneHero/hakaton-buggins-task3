from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
import os
import json

app = FastAPI()

# Настройки OAuth 2.0
CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']

# Путь для хранения и загрузки токенов
TOKEN_FILE = "token.json"

# Загрузка токенов из файла
def load_credentials():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as token:
            creds_data = json.load(token)
            return Credentials(**creds_data)
    return None

# Сохранение токенов в файл
def save_credentials(credentials):
    with open(TOKEN_FILE, "w") as token:
        token.write(credentials.to_json())

@app.get("/authorize/")
async def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    return RedirectResponse(url=authorization_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.query_params.get('state')
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/oauth2callback"
    )
    authorization_response = str(request.url)
    flow.fetch_token(authorization_response=authorization_response)

    credentials = flow.credentials
    save_credentials(credentials)
    return {"message": "Authorization successful. You can now access the check-folders endpoint."}

class NoOpCache(Cache):
    """Класс, который не выполняет кэширование."""
    def get(self, url):
        return None

    def set(self, url, content):
        pass

@app.get("/check-api-access/")
async def check_api_access():
    credentials = load_credentials()
    if not credentials:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        service = build('drive', 'v3', credentials=credentials, cache=NoOpCache())

        # Выполнение простого запроса для проверки доступа
        results = service.files().list(
            pageSize=10, fields="nextPageToken, files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            return {"message": "No files found."}
        else:
            files = [{"id": item["id"], "name": item["name"]} for item in items]
            return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Запуск приложения: uvicorn main:app --reload
