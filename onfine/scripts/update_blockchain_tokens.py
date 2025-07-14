from datetime import datetime

from onfine.app_factory import create_app
from onfine.extensions import db
from onfine.models.blockchain_tokens import BlockchainTokens

tokens = [
    # ERC20
    {
        "network": "ERC20",
        "symbol": "USDT",
        "contract_address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
    },
    {
        "network": "ERC20",
        "symbol": "USDC",
        "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "decimals": 6,
    },
    {
        "network": "ERC20",
        "symbol": "BUSD",
        "contract_address": "0x4fabb145d64652a948d72533023f6e7a623c7c53",
        "decimals": 18,
    },
    {
        "network": "ERC20",
        "symbol": "DAI",
        "contract_address": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "decimals": 18,
    },
    {
        "network": "ERC20",
        "symbol": "TUSD",
        "contract_address": "0x0000000000085d4780B73119b644AE5ecd22b376",
        "decimals": 18,
    },
    {
        "network": "ERC20",
        "symbol": "WETH",
        "contract_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "decimals": 18,
    },
    # BEP20
    {
        "network": "BEP20",
        "symbol": "USDT",
        "contract_address": "0x55d398326f99059ff775485246999027b3197955",
        "decimals": 18,
    },
    {
        "network": "BEP20",
        "symbol": "USDC",
        "contract_address": "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
        "decimals": 18,
    },
    {
        "network": "BEP20",
        "symbol": "BUSD",
        "contract_address": "0xe9e7cea3dedca5984780bafc599bd69add087d56",
        "decimals": 18,
    },
    {
        "network": "BEP20",
        "symbol": "DAI",
        "contract_address": "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3",
        "decimals": 18,
    },
    {
        "network": "BEP20",
        "symbol": "TUSD",
        "contract_address": "0x14016e85a25aeb13065688cafb43044c2ef86784",
        "decimals": 18,
    },
    {
        "network": "BEP20",
        "symbol": "WBNB",
        "contract_address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "decimals": 18,
    },
    # TRC20
    {"network": "TRC20", "symbol": "USDT", "contract_address": "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", "decimals": 6},
    {"network": "TRC20", "symbol": "USDC", "contract_address": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8", "decimals": 6},
    {"network": "TRC20", "symbol": "TUSD", "contract_address": "TD6Eddh6FMSYM8PJhCwRW2V5y3KiLZRnPt", "decimals": 18},
]


def seed_tokens() -> None:  # noqa D103
    for t in tokens:
        exists = BlockchainTokens.query.filter_by(network=t["network"], symbol=t["symbol"]).first()
        if exists:
            print(f"{t['network']}:{t['symbol']} уже существует, пропускаем.")  # noqa T201
            continue

        token = BlockchainTokens(
            network=t["network"],
            symbol=t["symbol"],
            contract_address=t["contract_address"],
            decimals=t["decimals"],
            is_active=True,
            created_at=datetime.utcnow(),  # noqa DTZ003
        )
        db.session.add(token)
        print(f"Добавлен токен: {t['network']}:{t['symbol']}")  # noqa T201

    db.session.commit()
    print("Готово: Все токены добавлены.")  # noqa T201


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_tokens()
