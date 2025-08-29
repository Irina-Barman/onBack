# from decimal import Decimal


# def calculate_payout(user_income: Decimal, inviter_percent: Decimal | None = None):
#     """
#     user_income: валовый доход пользователя
#     inviter_percent: процент вознаграждения его пригласителю (0.01/0.02/0.03/../0.1)
#     """
#     USER_SHARE = Decimal("0.60")
#     SERVICE_SHARE = Decimal("0.40")

#     # 1) рассчитываем базу для пользователя и сервиса
#     user_amount = (user_income * USER_SHARE).quantize(Decimal("0.01"))
#     service_fee = (user_income * SERVICE_SHARE).quantize(Decimal("0.01"))

#     # 2) если у пользователя есть пригласитель, считаем бонус
#     inviter_amount = Decimal("0.00")
#     if inviter_percent and inviter_percent > 0:
#         inviter_amount = (user_income * inviter_percent).quantize(Decimal("0.01"))

#     # 3) вычитаем бонус из комиссии
#     final_user_amount = user_amount - inviter_amount

#     # 4) итог
#     return {
#         "Валовый доход пользователя": float(user_income),
#         "Базовая доля пользователя (60%)": float(user_amount),
#         "Базовая комиссия (40%)": float(service_fee),
#         "Реферальный бонус пригласителю": float(inviter_amount),
#         "ИТОГО выплата пользователю": float(final_user_amount),  # пользователю всегда фикс 60%
#     }
