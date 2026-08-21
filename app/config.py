from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str = "your-bot-token-from-botfather"
    TELEGRAM_WEBHOOK_SECRET: str = "a-random-string-you-choose"
    TELEGRAM_WEBHOOK_URL: str = "https://your-render-app.onrender.com/telegram/webhook"
    ADMIN_CHAT_ID: int = 123456789

    # AI Providers (Groq or Gemini)
    GROQ_API_KEY: str = ""
    GEMINI_API_KEYS: str = ""

    # Notion
    NOTION_TOKEN: str = "secret_xxx"
    NOTION_PARENT_PAGE_ID: str = "32-char-hex-from-notion-url"
    ORDERS_DB_ID: str = "filled-after-running-setup-script"
    RUN_LOG_DB_ID: str = "filled-after-running-setup-script"
    CONTROL_PANEL_PAGE_ID: str = ""

    # Email
    GMAIL_USER: str = "your-email@gmail.com"
    GMAIL_APP_PASSWORD: str = "xxxx-xxxx-xxxx-xxxx"
    VENDOR_EMAIL: str = "vendor-lab@example.com"

    # App Settings & Active Blueprint
    ACTIVE_BLUEPRINT: str = "optical"
    DEV_MODE: bool = True
    SHOP_NAME: str = "ShopSight Opticals"
    SHOP_ADDRESS: str = "123 Main Street, City"
    SHOP_PHONE: str = "+91-9876543210"
    AUTO_APPROVE_CONFIDENCE: float = 0.85
    AUTO_APPROVE_MAX_VALUE: float = 3000.0
    SLA_THRESHOLD_MINUTES: int = 120
    SHOP_HOURS_START: int = 9
    SHOP_HOURS_END: int = 21

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def gemini_api_key_list(self) -> List[str]:
        return [key.strip() for key in self.GEMINI_API_KEYS.split(",") if key.strip()]

settings = Settings()
