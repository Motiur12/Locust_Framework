from locust import User, task, between, events
import asyncio
from playwright.sync_api import sync_playwright

class PlaywrightUser(User):
    wait_time = between(1, 3)

    def on_start(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)  # set False to see browser
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def on_stop(self):
        self.page.close()
        self.context.close()
        self.browser.close()
        self.playwright.stop()

    @task
    def login_task(self):
        self.page.goto("http://example.com/login")
        self.page.fill('input[name="username"]', "admin")
        self.page.fill('input[name="password"]', "1234")
        self.page.click('button#login')
        self.page.wait_for_load_state("networkidle")
