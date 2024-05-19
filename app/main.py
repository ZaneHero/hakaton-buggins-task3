import os
import pickle
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from datetime import datetime, timedelta

app = FastAPI()

# Путь к вашему файлу client_secret.json
CLIENT_SECRET_FILE = 'credentials.json'
SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group.readonly',
    'https://www.googleapis.com/auth/drive'
]

@app.get("/")
def read_root():
    return {"message": "Welcome to the Google API FastAPI application"}

@app.get("/authenticate")
def authenticate():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    flow.redirect_uri = 'http://localhost:8000/oauth2callback'
    auth_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    
    # Сохранение состояния в файл, чтобы использовать его в обратном вызове
    with open('state.pkl', 'wb') as f:
        pickle.dump(state, f)

    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
def oauth2callback(request: Request):
    # Загрузка состояния из файла
    with open('state.pkl', 'rb') as f:
        state = pickle.load(f)
    
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES, state=state)
    flow.redirect_uri = 'http://localhost:8000/oauth2callback'
    
    # Получение авторизационного кода из запроса
    authorization_response = str(request.url)
    flow.fetch_token(authorization_response=authorization_response)

    creds = flow.credentials
    # Сохранение учетных данных для следующего выполнения
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)

    return {"message": "Authentication successful! You can now use the API endpoints."}

def get_credentials():
    creds = None
    # Файл token.pickle хранит токены доступа и обновления пользователя, создается автоматически при первом выполнении
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # Если нет допустимых учетных данных, запрашиваем их у пользователя
    if not creds or not creds.valid:
        raise HTTPException(status_code=401, detail="The user is not authenticated. Please authenticate first.")
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

@app.get("/groups")
def list_google_groups():
    creds = get_credentials()
    service = build('admin', 'directory_v1', credentials=creds)
    groups = []
    page_token = None

    while True:
        try:
            results = service.groups().list(customer='my_customer', pageToken=page_token).execute()
            groups.extend(results.get('groups', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(content=groups)

@app.get("/untransferred_documents")
def list_untransferred_documents(folder_id: str, company_email: str):
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    results = []
    page_token = None
    seven_days_ago = datetime.now() - timedelta(days=7)

    while True:
        response = drive_service.files().list(q=f"'{folder_id}' in parents and trashed=false",
                                              fields="nextPageToken, files(id, name, owners, createdTime)",
                                              pageToken=page_token).execute()
        for file in response.get('files', []):
            created_time = datetime.strptime(file['createdTime'], '%Y-%m-%dT%H:%M:%S.%fZ')
            if created_time < seven_days_ago:
                owner_email = file['owners'][0]['emailAddress']
                if owner_email != company_email:
                    results.append({
                        'name': file['name'],
                        'owner': owner_email,
                        'createdDate': created_time
                    })

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    return JSONResponse(content=results)

@app.post("/copy_documents_by_owner")
def copy_documents_by_owner(folder_id: str, owner_email: str):
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    page_token = None
    copied_files = []

    while True:
        response = drive_service.files().list(q=f"'{folder_id}' in parents and trashed=false",
                                              fields="nextPageToken, files(id, name, owners)",
                                              pageToken=page_token).execute()
        for file in response.get('files', []):
            if file['owners'][0]['emailAddress'] == owner_email:
                copy = drive_service.files().copy(fileId=file['id'], body={'name': f"Copy of {file['name']}"}).execute()
                drive_service.permissions().create(fileId=copy['id'],
                                                   body={'role': 'owner', 'type': 'user', 'emailAddress': creds.service_account_email}).execute()
                copied_files.append(copy['name'])

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    return JSONResponse(content={"copied_files": copied_files})

@app.post("/accept_ownership_transfers")
def accept_ownership_transfers(folder_id: str):
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    page_token = None
    accepted_files = []

    while True:
        response = drive_service.files().list(q=f"'{folder_id}' in parents and trashed=false",
                                              fields="nextPageToken, files(id, name, owners, permissions)",
                                              pageToken=page_token).execute()
        for file in response.get('files', []):
            for permission in file.get('permissions', []):
                if permission.get('role') == 'owner' and permission.get('pendingOwner'):
                    try:
                        drive_service.permissions().update(fileId=file['id'], permissionId=permission['id'],
                                                           body={'role': 'owner'}, transferOwnership=True).execute()
                        accepted_files.append(file['name'])
                    except Exception as e:
                        print(f"Error accepting ownership for file: {file['name']} - {str(e)}")

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    return JSONResponse(content={"accepted_files": accepted_files})
