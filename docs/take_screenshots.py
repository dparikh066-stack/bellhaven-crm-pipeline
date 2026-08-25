import os
import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options

OUT = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(OUT, exist_ok=True)

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--window-size=1400,2400")
opts.add_argument("--force-device-scale-factor=1")
driver = webdriver.Edge(options=opts)

try:
    driver.get("http://127.0.0.1:5000/")
    time.sleep(0.5)
    height = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(1400, min(height + 60, 4000))
    time.sleep(0.3)
    driver.save_screenshot(os.path.join(OUT, "pending_queue.png"))
    print("saved pending_queue.png, height=", height)

    driver.get("http://127.0.0.1:5000/decided")
    time.sleep(0.5)
    driver.set_window_size(1400, 2100)
    time.sleep(0.3)
    driver.save_screenshot(os.path.join(OUT, "decided_history.png"))
    print("saved decided_history.png (viewport-cropped)")

    # scroll to a chow_split card for a more interesting example
    el = driver.execute_script("""
        const cards = [...document.querySelectorAll('.card')];
        const target = cards.find(c => c.textContent.includes('chow_split'));
        if (target) { target.scrollIntoView({block: 'start'}); return true; }
        return false;
    """)
    time.sleep(0.4)
    driver.save_screenshot(os.path.join(OUT, "decided_chow_example.png"))
    print("saved decided_chow_example.png, found target:", el)
finally:
    driver.quit()
