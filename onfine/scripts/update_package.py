from decimal import Decimal

from onfine.app_factory import create_app
from onfine.extensions import db
from onfine.models.package import Package

# Данные пакетов с суммами входа (price_usdt) и типом (например, 'investment')
packages_data = [
    {"name": "Mini", "price_usdt": Decimal("50"), "type": "investment"},
    {"name": "Starter", "price_usdt": Decimal("100"), "type": "investment"},
    {"name": "Basic", "price_usdt": Decimal("200"), "type": "investment"},
    {"name": "Standard", "price_usdt": Decimal("500"), "type": "investment"},
    {"name": "Advanced", "price_usdt": Decimal("1000"), "type": "investment"},
    {"name": "Premium", "price_usdt": Decimal("2000"), "type": "investment"},
    {"name": "Pro", "price_usdt": Decimal("5000"), "type": "investment"},
    {"name": "Expert", "price_usdt": Decimal("10000"), "type": "investment"},
    {"name": "Business", "price_usdt": Decimal("20000"), "type": "investment"},
    {"name": "VIP", "price_usdt": Decimal("50000"), "type": "investment"},
    {"name": "Elite", "price_usdt": Decimal("100000"), "type": "investment"},
]


def create_packages():
    for data in packages_data:
        pkg = Package.query.filter_by(name=data["name"]).first()
        if pkg:
            print(f"Пакет {data['name']} уже существует, пропускаем")
            continue

        new_pkg = Package(
            name=data["name"],
            type=data["type"],
            price_usdt=data["price_usdt"],
            description=None,  # можно добавить описание при необходимости
        )
        db.session.add(new_pkg)
        print(f"Создан пакет {data['name']}")

    db.session.commit()
    print("Создание пакетов завершено")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        create_packages()
