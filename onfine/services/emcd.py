import os
import requests

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"

class EMCDService:
    def __init__(self):
        self.api_key = os.getenv("EMCD_API_KEY")
        if not self.api_key:
            raise RuntimeError("EMCD_API_KEY is not set")

    def _get(self, url: str) -> dict:
        r = requests.get(f"{url}/{self.api_key}", timeout=10)
        r.raise_for_status()
        return r.json()

    def get_account_info(self) -> dict:
        """ General user data: v2/info """
        return self._get(f"{BASE_V2}/info")

    def get_workers(self, coin: str) -> dict:
        """ Connected workers: v1/{coin}/workers """
        return self._get(f"{BASE_V1}/{coin}/workers")

    def get_income(self, coin: str) -> dict:
        """ Rewards on account: v1/{coin}/income """
        return self._get(f"{BASE_V1}/{coin}/income")

    def get_payouts(self, coin: str) -> dict:
        """ Payouts: v1/{coin}/payouts """
        return self._get(f"{BASE_V1}/{coin}/payouts")
