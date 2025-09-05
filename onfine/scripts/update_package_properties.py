from decimal import Decimal
from typing import Dict, Optional, TypedDict

from onfine.app_factory import create_app
from onfine.extensions import db
from onfine.models.package import Package
from onfine.models.package_properties import PackageCategory, PackageProperty


class PackagePropertyData(TypedDict):
    term_months: int
    interest_rate_from: Decimal
    interest_rate_to: Decimal
    bonuses: str
    target_audience: PackageCategory


packages_property: Dict[str, PackagePropertyData] = {
    "Mini": {
        "term_months": 6,
        "interest_rate_from": Decimal("10.00"),
        "interest_rate_to": Decimal("20.00"),
        "bonuses": "Доступ к базовой аналитике",
        "target_audience": PackageCategory.BEGINNERS,
    },
    "Starter": {
        "term_months": 6,
        "interest_rate_from": Decimal("11.00"),
        "interest_rate_to": Decimal("22.00"),
        "bonuses": "+ ежемесячный отчет",
        "target_audience": PackageCategory.STABLE_INCOME,
    },
    "Basic": {
        "term_months": 12,
        "interest_rate_from": Decimal("12.00"),
        "interest_rate_to": Decimal("25.00"),
        "bonuses": "Чат-поддержка",
        "target_audience": PackageCategory.STABLE_INCOME,
    },
    "Standard": {
        "term_months": 12,
        "interest_rate_from": Decimal("13.00"),
        "interest_rate_to": Decimal("28.00"),
        "bonuses": "+ вебинары для новичков",
        "target_audience": PackageCategory.STABLE_INCOME,
    },
    "Advanced": {
        "term_months": 12,
        "interest_rate_from": Decimal("14.00"),
        "interest_rate_to": Decimal("32.00"),
        "bonuses": "Персональный менеджер",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "Premium": {
        "term_months": 18,
        "interest_rate_from": Decimal("15.00"),
        "interest_rate_to": Decimal("35.00"),
        "bonuses": "VIP-поддержка",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "Pro": {
        "term_months": 18,
        "interest_rate_from": Decimal("16.00"),
        "interest_rate_to": Decimal("38.00"),
        "bonuses": "Индивидуальная стратегия",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "Expert": {
        "term_months": 24,
        "interest_rate_from": Decimal("17.00"),
        "interest_rate_to": Decimal("42.00"),
        "bonuses": "Приоритетные выплаты",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "Business": {
        "term_months": 24,
        "interest_rate_from": Decimal("18.00"),
        "interest_rate_to": Decimal("45.00"),
        "bonuses": "Консультации с CEO",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "VIP": {
        "term_months": 24,
        "interest_rate_from": Decimal("19.00"),
        "interest_rate_to": Decimal("48.00"),
        "bonuses": "Участие в прибыли компании",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
    "Elite": {
        "term_months": 24,
        "interest_rate_from": Decimal("20.00"),
        "interest_rate_to": Decimal("50.00"),
        "bonuses": "Кастомные условия",
        "target_audience": PackageCategory. MAXIMUM_EARNING,
    },
}


def update_package_property() -> None:
    """
    Обновляет свойства пакетов (PackageProperty) в базе данных.

    Для каждого пакета из `packages_property`:
    - Ищет пакет в базе по имени.
    - Если пакет не найден, выводит предупреждение и пропускает.
    - Если у пакета нет связанных свойств (PackageProperty), создаёт новую запись.
    - Обновляет поля свойства согласно данным из словаря.
    - В конце коммитит изменения в базе.
    """
    for package_name, props in packages_property.items():
        pkg: Optional[Package] = Package.query.filter_by(name=package_name).first()
        if not pkg:
            print(f"Пакет {package_name} не найден в базе, пропускаем")
            continue

        prop: Optional[PackageProperty] = pkg.package_property
        if not prop:
            prop = PackageProperty(package_id=pkg.id)
            db.session.add(prop)

        prop.term_months = props["term_months"]
        prop.interest_rate_from = props["interest_rate_from"]
        prop.interest_rate_to = props["interest_rate_to"]
        prop.bonuses = props["bonuses"]
        prop.target_audience = props["target_audience"]

    db.session.commit()
    print("Свойства пакетов (PackageProperty) обновлены")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        update_package_property()
