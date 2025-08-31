import os
from functools import lru_cache
from typing import List

import requests

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")
ETHERSCAN_BASE_URL = os.getenv("ETHERSCAN_BASE_URL", "https://api.etherscan.io/api")
TRONGRID_CONTRACT_API_URL = os.getenv("TRONGRID_CONTRACT_API_URL", "https://api.trongrid.io/wallet/getcontract")

SUPPORTED_CHAINS = {"ERC20": "eth", "BEP20": "bsc", "TRC20": "tron"}


@lru_cache(maxsize=1024)
def get_token_abi(network: str, contract_addr: str) -> List[dict]:
    """
    Загружает и кэширует ABI токена по адресу в зависимости от сети.

    Args:
        network (str): ERC20, BEP20, TRC20 и др.
        contract_addr (str): адрес токена

    Returns:
        List[dict]: ABI контракта
    """
    if network.upper() == "TRC20":
        return fetch_trongrid_abi(contract_addr)
    elif network.upper() in SUPPORTED_CHAINS:
        chain = SUPPORTED_CHAINS[network.upper()]
        return fetch_etherscan_multichain_abi(chain, contract_addr)
    else:
        raise ValueError(f"[ABI] Unsupported network: {network}")


def fetch_etherscan_multichain_abi(chain: str, contract_addr: str) -> List[dict]:
    """
    Получить ABI токена из Etherscan Multichain API.

    API возвращает ABI по адресу контракта и цепочке (сети), которая может быть:
    Ethereum ("eth"), Binance Smart Chain ("bsc"), Polygon ("polygon") и другие.

    Args:
        chain (str): Код сети для API (например, "eth", "bsc", "polygon").
        contract_addr (str): Адрес смарт-контракта токена в данной сети.

    Returns:
        List[dict]: ABI контракта, представленное списком описаний функций и событий.

    Raises:
        ValueError: Если произошла ошибка HTTP запроса,
                    или структура возвращаемых данных не соответствует ожиданиям.

    Пример:
        abi = fetch_etherscan_multichain_abi("eth", "0x6b175474e89094c44da98b954eedeac495271d0f")
    """
    params = {"chain": chain, "address": contract_addr, "apikey": ETHERSCAN_API_KEY}
    response = requests.get(f"{ETHERSCAN_BASE_URL}/contracts/abi", params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    abi = data.get("data")
    if not abi or not isinstance(abi, list):
        raise ValueError(f"[ABI] Invalid ABI response for {chain}:{contract_addr} → {data}")
    return abi


def fetch_trongrid_abi(contract_addr: str) -> List[dict]:
    """
    Загружает ABI токена из TronGrid API.

    Args:
        contract_addr (str): адрес контракта в формате base58 (TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t)

    Returns:
        List[dict]: ABI контракта
    """
    headers = {"Content-Type": "application/json"}
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY

    payload = {
        "value": contract_addr,
        "visible": True,
    }

    print(f"Отправка запроса ABI для TRON адреса: {contract_addr}")  # noqa: T201

    try:
        response = requests.post(TRONGRID_CONTRACT_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Проверяем наличие ошибок в ответе
        if "Error" in data:
            raise ValueError(f"[TRON] TronGrid error: {data.get('Error')}")

        abi_data = data.get("abi", {}).get("entrys", [])
        if not abi_data and "abi" in data:
            # Альтернативная проверка структуры ответа
            abi_data = data["abi"].get("entrys", [])

        if not abi_data:
            # Проверяем если ABI доступен напрямую в ответе
            if isinstance(data.get("abi"), list):
                return data["abi"]
            raise ValueError(f"[TRON] ABI not found for {contract_addr}: {data}")

        return abi_data

    except requests.exceptions.RequestException as e:
        raise ValueError(f"[TRON] Network error: {e}")
    except ValueError as e:
        raise e
    except Exception as e:
        raise ValueError(f"[TRON] Unexpected error: {e}")
