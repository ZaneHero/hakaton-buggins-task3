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

def run_selenium_task(email, password):
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")  # Уберите headless для отладки
    options.add_argument("--no-sandbox")
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

        # Переход на страницу групп
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
        group_elements = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='yDmH0d']/c-wiz[4]/c-wiz/div/div[3]/div/div[1]/div[2]/div")))
        logging.info(f"Found {len(group_elements)} group elements.")

        groups = []
        for group_element in group_elements:
            try:
                group_name = group_element.find_element(By.XPATH, ".//div[2]/div/a/div").text
                group_email = group_element.find_element(By.XPATH, ".//div[1]/div/span[2]").text
                groups.append({
                    "name": group_name,
                    "email": group_email
                })
                logging.info(f"Group found: {group_name} - {group_email}")
            except Exception as e:
                logging.error(f"Error parsing group element: {e}")

        # Сохранение данных в CSV файл
        if groups:
            save_to_csv(groups, 'groups.csv')
        else:
            logging.error("No groups found to save.")

        return groups
    except Exception as e:
        logging.error(f"Error during selenium task: {e}")
        raise
    finally:
        driver.quit()
        logging.info("Chrome driver quit.")

async def background_selenium_task(email, password):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        groups = await loop.run_in_executor(pool, run_selenium_task, email, password)
        return groups

@app.post("/get-groups/")
async def get_groups(request: LoginRequest):
    try:
        groups = await background_selenium_task(request.email, request.password)
        return {"groups": groups}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Запуск приложения
# Запуск: uvicorn main:app --reload
