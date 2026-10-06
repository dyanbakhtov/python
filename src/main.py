import logging
from decimal import Decimal

from exceptions import BankAccountError
from models import Client, BankAccount, AccountStatus, Currency, SavingsAccount

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

    savings_account = SavingsAccount(test_client, Decimal("500.00"), Currency.RUB, AccountStatus.ACTIVE, Decimal("300.00"), Decimal("10.3"))
    savings_account.apply_monthly_interest()
    print(savings_account.get_account_info())