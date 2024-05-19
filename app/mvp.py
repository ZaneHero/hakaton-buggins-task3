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

logging.basicConfig(level=logging.INFO)
app = FastAPI()

class LoginRequest(BaseModel):
    email: str
    password: str

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
        time.sleep(5)  # Ожидание загрузки страницы

        # Проверка наличия iframe и переключение на него
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        logging.info(f"Found {len(iframes)} iframes.")
        
        for iframe in iframes:
            driver.switch_to.frame(iframe)
            logging.info("Switched to iframe.")

            try:
                # Парсинг названий групп
                main_div = wait.until(EC.visibility_of_element_located((By.XPATH, "//div[@role='main']")))
                logging.info("Main div found.")
                
                group_elements = wait.until(EC.visibility_of_all_elements_located((By.XPATH, "//div[@role='main']//tr/td[1]//span[@role='link']")))
                group_names = [group.text for group in group_elements]
                logging.info(f"Groups found: {group_names}")

                return group_names
            except Exception as e:
                logging.error(f"Error during selenium task in iframe: {e}")
            finally:
                driver.switch_to.default_content()
        
        raise Exception("Unable to find groups in any iframe.")
    except Exception as e:
        logging.error(f"Error during selenium task: {e}")
        raise
    finally:
        driver.quit()
        logging.info("Chrome driver quit.")

async def background_selenium_task(email, password):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        group_names = await loop.run_in_executor(pool, run_selenium_task, email, password)
        return group_names

@app.post("/get-groups/")
async def get_groups(request: LoginRequest):
    try:
        group_names = await background_selenium_task(request.email, request.password)
        return {"groups": group_names}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Запуск приложения
# Запуск: uvicorn main:app --reload
