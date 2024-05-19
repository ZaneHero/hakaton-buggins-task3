from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import logging
import csv
import pickle
import os

logging.basicConfig(level=logging.INFO)
app = FastAPI()

class LoginRequest(BaseModel):
    email: str
    password: str

def save_to_csv(groups, file_path):
    keys = groups[0].keys()
    with open(file_path, 'w', newline='') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(groups)
    logging.info(f"Groups saved to {file_path}")

def authenticate_and_save_cookies(email, password):
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")  # Уберите headless для отладки
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=service, options=options)
    logging.info("Chrome driver initialized.")

    try:
        # Авторизация в Google-аккаунте
        driver.get("https://accounts.google.com/signin")
        logging.info("Navigating to Google Sign-In page")
        wait = WebDriverWait(driver, 30)
        
        email_input = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='email']")))
        email_input.send_keys(email)
        email_input.send_keys(Keys.RETURN)
        logging.info("Email entered.")
        time.sleep(2)

        password_input = wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@type='password']")))
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        logging.info("Password entered.")
        time.sleep(5)

        # Переход на страницу групп для установки домена
        driver.get("https://groups.google.com/u/1/my-groups")
        time.sleep(5)

        # Сохранение куки после успешной авторизации
        cookies = driver.get_cookies()
        cookies_path = "cookies.pkl"
        with open(cookies_path, 'wb') as f:
            pickle.dump(cookies, f)
        logging.info(f"Cookies saved to {cookies_path}")

        return cookies_path
    finally:
        driver.quit()
        logging.info("Chrome driver quit.")

def parse_groups_with_cookies(cookies_path):
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")  # Уберите headless для отладки
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=service, options=options)
    logging.info("Chrome driver initialized.")

    try:
        # Загрузка страницы для установки домена куки
        driver.get("https://groups.google.com/u/1/my-groups")
        time.sleep(5)

        # Загрузка куки
        with open(cookies_path, 'rb') as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                # Удаляем 'expiry' если она есть, т.к. она мешает установке куки
                if 'expiry' in cookie:
                    del cookie['expiry']
                driver.add_cookie(cookie)
        logging.info("Cookies loaded into the browser.")

        # Переход на страницу групп после загрузки куки
        driver.get("https://groups.google.com/u/1/my-groups")
        logging.info("Navigated to Google Groups.")
        time.sleep(10)  # Увеличено время ожидания загрузки страницы

        # Снимок экрана перед попыткой найти элементы
        screenshot_path = "screenshot.png"
        driver.save_screenshot(screenshot_path)
        logging.info(f"Screenshot saved to {screenshot_path}")

        # Проверка загрузки страницы групп
        if "my-groups" not in driver.current_url:
            raise Exception("Failed to load Google Groups page")

        # Парсинг названий групп
        wait = WebDriverWait(driver, 30)
        group_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, './g/') and .//div[contains(text(), 'Отдел')]]")))

        # Парсинг данных
        groups = []
        for group_element in group_elements:
            group_name = group_element.text
            group_href = group_element.get_attribute("href")
            group_info = {
                "group_name": group_name,
                "group_href": group_href,
            }
            groups.append(group_info)

        # Сохранение данных в CSV файл
        if groups:
            save_to_csv(groups, 'groups.csv')
        else:
            logging.error("No groups found to save.")

        return groups
    finally:
        driver.quit()
        logging.info("Chrome driver quit.")

async def background_authenticate_task(email, password):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        cookies_path = await loop.run_in_executor(pool, authenticate_and_save_cookies, email, password)
        return cookies_path

async def background_parse_task(cookies_path):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        groups = await loop.run_in_executor(pool, parse_groups_with_cookies, cookies_path)
        return groups

@app.post("/authenticate/")
async def authenticate(request: LoginRequest):
    try:
        cookies_path = await background_authenticate_task(request.email, request.password)
        return {"message": "Authentication successful, cookies saved.", "cookies_path": cookies_path}
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/parse-groups/")
async def parse_groups():
    try:
        cookies_path = "cookies.pkl"  # Загрузка куки из сохраненного файла
        if not os.path.exists(cookies_path):
            raise HTTPException(status_code=400, detail="No cookies found. Please authenticate first.")
        groups = await background_parse_task(cookies_path)
        return {"groups": groups}
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Запуск приложения
# Запуск: uvicorn main:app --reload
