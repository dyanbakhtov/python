import logging
from decimal import Decimal

from exceptions import BankAccountError
from models import Client, BankAccount, AccountStatus, Currency, SavingsAccount, PremiumAccount, InvestmentAccount, \
    AssetType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    test_client = Client("Семён Персунов")

    # ➕ создание активного и замороженного счёта
    active_account = BankAccount(
        client=test_client,
        balance=Decimal("1000.00"),
        account_status=AccountStatus.ACTIVE,
        currency=Currency.RUB
    )

    frozen_account = BankAccount(
        client=test_client,
        balance=Decimal("5000.00"),
        account_status=AccountStatus.FROZEN,
        currency=Currency.USD
    )

    # 🚫 попытка операций над замороженным счётом
    try:
        frozen_account.deposit(Decimal("5000.00"))
    except BankAccountError as e:
        logger.warning(f"{e.__class__.__name__}: {e}")

    # ✅ валидное пополнение и снятие
    active_account.withdraw(Decimal("300.00"))
    active_account.deposit(Decimal("500.00"))

    savings_account = SavingsAccount(test_client, Decimal("500.00"), Currency.RUB, AccountStatus.ACTIVE,
                                     Decimal("300.00"), Decimal("10.3"))
    savings_account.deposit(Decimal("500.00"))
    savings_account.apply_monthly_interest()

    try:
        savings_account.withdraw(Decimal("1000.00"))
    except BankAccountError as e:
        logger.warning(f"{e.__class__.__name__}: {e}")

    premium_account = PremiumAccount(test_client, Decimal("100000"), Currency.USD, AccountStatus.ACTIVE, Decimal("50000"),
                                     Decimal("100"))
    premium_account.withdraw(Decimal("100000"))

    try:
        premium_account.withdraw(Decimal("50000.00"))
    except BankAccountError as e:
        logger.warning(f"{e.__class__.__name__}: {e}")

    investment_account = InvestmentAccount(test_client, Decimal(1000), Currency.RUB, AccountStatus.ACTIVE)
    investment_account.buy_asset(AssetType.STOCKS, Decimal("200.00"))
    investment_account.buy_asset(AssetType.BONDS, Decimal("100.00"))
    investment_account.buy_asset(AssetType.ETF, Decimal("500.00"))

    try:
        investment_account.buy_asset(AssetType.STOCKS, Decimal("300.00"))
    except BankAccountError as e:
        logger.warning(f"{e.__class__.__name__}: {e}")

    growth_rates = {AssetType.STOCKS: Decimal("10.00"),
                    AssetType.BONDS: Decimal("4.00"),
                    AssetType.ETF: Decimal("7.00")}
    yearly_growth = investment_account.project_yearly_growth(growth_rates)
    logger.info("Projected yearly growth: %s %s", yearly_growth, investment_account.currency.value)