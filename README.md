# hakaton-buggins-task3
Создание приложения управления папками и файлами на Google Drive.
создаем venv: python3 -m venv venv
активируем venv: source venv/bin/activate
запуск приложения: uvicorn app.main:app --reload

создаем папку с миграциями: alembic init migrations
создаем ревизию: alembic revision --autogenerate -m "create db"
накатываем последнюю ревизию: alembic upgrade head

OAUTHLIB_INSECURE_TRANSPORT=1
SECRET_KEY=agPN2AMlAwokI5ozW2oFyJ3jJt4MlPS8cIEplfsCGgo=
GMAIL_USERNAME=kolomojcysuai@gmail.com
GMAIL_PASSWORD=SUAIHakaton1


