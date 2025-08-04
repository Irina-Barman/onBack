import os
from functools import lru_cache
from typing import List

import requests

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")
ETHERSCAN_BASE_URL = os.getenv("ETHERSCAN_BASE_URL")
TRONGRID_CONTRACT_API_URL = os.getenv("TRONGRID_CONTRACT_API_URL")

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
    Загружает ABI токена из Etherscan Multichain API (V2).

    Args:
        chain (str): Название сети: eth, bsc, polygon, arbitrum и т.д.
        contract_addr (str): Контракт токена.

    Returns:
        List[dict]: ABI контракта.
    """
    url = (
        f"{ETHERSCAN_BASE_URL}/contracts/abi"
        f"?chain={chain}"
        f"&address={contract_addr}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )

    response = requests.get(url)
    if not response.ok:
        raise ValueError(f"[ABI] HTTP error: {response.status_code} - {response.text}")

    data = response.json()
    abi = data.get("data")
    if not abi or not isinstance(abi, list):
        raise ValueError(f"[ABI] Invalid ABI response for {chain}:{contract_addr} → {data}")

    return abi


def fetch_trongrid_abi(contract_addr: str) -> List[dict]:
    """
    Загружает ABI контракта TRC20 через TronGrid API.

    Args:
        contract_addr (str): адрес токена TRC20

    Returns:
        List[dict]: ABI контракта
    """
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
    payload = {"value": contract_addr}

    response = requests.post(TRONGRID_CONTRACT_API_URL, json=payload, headers=headers)
    if not response.ok:
        raise ValueError(f"[TRON] HTTP error: {response.status_code} - {response.text}")

    data = response.json()
    abi_data = data.get("abi", {}).get("entrys")
    if not abi_data:
        raise ValueError(f"[TRON] Failed to fetch ABI for {contract_addr}: {data}")

    return abi_data
