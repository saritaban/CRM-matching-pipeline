import os
import requests

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("CRM_BASE_URL")
API_TOKEN = os.getenv("CRM_API_TOKEN")


class CRMClient:

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def options(self, endpoint):
        url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        response = self.session.options(url, timeout=30)

        print("Status:", response.status_code)
        print("Allow:", response.headers.get("Allow"))
        print("Response:", response.text[:2000])

        return response

    def get(self, endpoint, params=None):

        url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        response = self.session.get(
            url,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        return response.json()

    def post(self, endpoint, payload):

        url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        response = self.session.post(
            url,
            json=payload,
            timeout=30
        )

        response.raise_for_status()

        return response.json()

    def patch(self, endpoint, payload):

        url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        response = self.session.patch(
            url,
            json=payload,
            timeout=30
        )

        response.raise_for_status()

        return response.json()