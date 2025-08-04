import json
import os

import requests

# Чтение API ключей из переменных окружения
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")


def get_etherscan_abi(address: str) -> list:
    """
    Получить ABI смарт-контракта ERC20 по адресу с помощью Etherscan API.

    Args:
        address (str): Ethereum-адрес контракта (например, USDT).

    Returns:
        list: ABI контракта в формате JSON.

    Raises:
        Exception: Если API ключ не задан или Etherscan возвращает ошибку.
    """
    if not ETHERSCAN_API_KEY:
        raise Exception("ETHERSCAN_API_KEY не задан")

    url = (
        "https://api.etherscan.io/api"
        "?module=contract"
        "&action=getabi"
        f"&address={address}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    if data["status"] != "1":
        # Статус "1" означает успешный запрос, иначе ошибка
        raise Exception(f"Etherscan error: {data.get('result')}")

    # Возвращаем ABI в виде списка (десериализуем JSON-строку)
    return json.loads(data["result"])


def get_bscscan_abi(address: str) -> list:
    """
    Получить ABI смарт-контракта BEP20 по адресу с помощью BSCScan API.

    Args:
        address (str): Binance Smart Chain адрес контракта.

    Returns:
        list: ABI контракта в формате JSON.

    Raises:
        Exception: Если API ключ не задан или BSCScan возвращает ошибку.
    """
    if not BSCSCAN_API_KEY:
        raise Exception("BSCSCAN_API_KEY не задан")

    url = (
        "https://api.bscscan.com/api"
        "?module=contract"
        "&action=getabi"
        f"&address={address}"
        f"&apikey={BSCSCAN_API_KEY}"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    if data["status"] != "1":
        raise Exception(f"BSCScan error: {data.get('result')}")

    return json.loads(data["result"])


def get_tronscan_abi(address: str) -> list:
    """
    Получить ABI TRC20 контракта по адресу с помощью Tronscan API.

    Args:
        address (str): Tron адрес контракта.

    Returns:
        list: ABI контракта в формате JSON.

    Raises:
        Exception: Если ABI не найден или произошла ошибка запроса.
    """
    url = f"https://apilist.tronscan.org/api/contract?contract={address}"
    headers = {}

    # Если есть TronGrid API ключ, добавляем в заголовки для авторизации
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    if "abi" not in data or data["abi"] is None:
        raise Exception(f"Tronscan error: ABI not found for {address}")

    return data["abi"]


def fetch_abi(network: str, address: str) -> list:
    """
    Универсальная функция для получения ABI контракта по сети и адресу.

    Args:
        network (str): Сеть контракта - ERC20, BEP20 или TRC20.
        address (str): Адрес контракта в соответствующей сети.

    Returns:
        list: ABI контракта в формате JSON.

    Raises:
        Exception: Если сеть не поддерживается или произошла ошибка получения ABI.
    """
    network = network.upper()

    if network == "ERC20":
        return get_etherscan_abi(address)
    elif network == "BEP20":
        return get_bscscan_abi(address)
    elif network == "TRC20":
        return get_tronscan_abi(address)
    else:
        raise Exception(f"Сеть {network} не поддерживается")
