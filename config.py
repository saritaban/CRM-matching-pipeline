import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

CRM_BASE_URL = os.getenv("CRM_BASE_URL")

CRM_API_KEY = os.getenv("CRM_API_KEY")

PARENT_ACCOUNT_NAME = os.getenv(
    "PARENT_ACCOUNT_NAME",
    "Bellhaven Senior Living"
)

WEBSITE_URL = (
    "https://analyst-assessment-production.up.railway.app"
)