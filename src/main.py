import logging
from datetime import date
from decimal import Decimal

from exceptions import BankAccountError
from models import Client, BankAccount, AccountStatus, Currency, SavingsAccount, PremiumAccount, InvestmentAccount, \
    AssetType, ClientStatus, Bank

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


def run_tests_day1() -> None:
    test_client = Client(
        name="Семён Персунов",
        date_of_birth=date(1993, 5, 16),
        phone_number="+71234567890",
        status=ClientStatus.ACTIVE
    )

    # ➕ создание активного и замороженного счёта
    active_account = BankAccount(
        client=test_client,
        balance=Decimal("1000.00"),
        currency=Currency.RUB,
        status=AccountStatus.ACTIVE
    )

    frozen_account = BankAccount(
        client=test_client,
        balance=Decimal("5000.00"),
        currency=Currency.USD,
        status=AccountStatus.FROZEN
    )

    # 🚫 попытка операций над замороженным счётом
    try:
        frozen_account.deposit(Decimal("5000.00"))
    except BankAccountError as e:
        print(f"{e.__class__.__name__}: {e}")

    # ✅ валидное пополнение и снятие
    active_account.withdraw(Decimal("300.00"))
    active_account.deposit(Decimal("500.00"))


def run_tests_day2() -> None:
    test_client = Client(
        name="Семён Персунов",
        date_of_birth=date(1993, 5, 16),
        phone_number="+71234567890",
        status=ClientStatus.ACTIVE
    )

    savings_account = SavingsAccount(test_client, Decimal("500.00"), Currency.RUB, AccountStatus.ACTIVE,
                                     Decimal("300.00"), Decimal("10.3"))
    savings_account.deposit(Decimal("500.00"))
    savings_account.apply_monthly_interest()

    try:
        savings_account.withdraw(Decimal("1000.00"))
    except BankAccountError as e:
        logger.warning(f"{e.__class__.__name__}: {e}")

    premium_account = PremiumAccount(test_client, Decimal("100000"), Currency.USD, AccountStatus.ACTIVE,
                                     Decimal("50000"),
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


def run_tests_day3() -> None:
    logger.info("\n== 1. Creating bank and clients ==")
    bank = Bank("Zalupabank")

    client1 = Client(
        name="Семён Персунов",
        date_of_birth=date(1993, 5, 16),
        phone_number="+71234567890",
        status=ClientStatus.ACTIVE
    )

    client2 = Client(
        name="Номад Горячев",
        date_of_birth=date(1882, 10, 20),
        phone_number="+79998887766",
        status=ClientStatus.ACTIVE
    )

    bank.add_client(client1)
    bank.add_client(client2)

    try:
        underage_client = Client(
            name="Школяр Рандомный",
            date_of_birth=date(2015, 1, 1),
            phone_number="+70000000000",
            status=ClientStatus.ACTIVE
        )
    except BankAccountError as e:
        logger.warning("Underage exception was caught: %s", e)

    logger.info("\n== 2. Creating accounts ==")
    c1_acc1 = bank.open_account(client1.client_id, currency=Currency.RUB, initial_balance=Decimal("150000.00"))
    c1_acc2 = bank.open_account(client1.client_id, currency=Currency.USD, initial_balance=Decimal("2000.00"))
    c2_acc1 = bank.open_account(client2.client_id, currency=Currency.RUB, initial_balance=Decimal("40000.00"))

    logger.info("Client %s has %s accounts", client1.name, len(client1.accounts))
    logger.info("Total bank capital in RUB: %s", bank.get_total_balance(Currency.RUB))

    logger.info("\n== 3. Authentication and suspicious activities ==")
    logger.info("Generated password of %s: %s", client1.name, client1.password)

    auth_success = bank.authenticate_client(client1.client_id, client1.password)
    logger.info("Authentication success: %s", auth_success)

    for attempt in range(3):
        try:
            bank.authenticate_client(client1.client_id, "wrong_password")
        except BankAccountError as e:
            logger.warning("Authentication exception was caught: %s", e)

    logger.info("Current status of %s: %s", client1.name, client1.status)
    logger.info("Suspicious activities of %s: %s", client1.name, client1.suspicious_activities)

    logger.info("\n== 4. Freezing and unfreezing accounts ==")
    bank.freeze_account(c2_acc1.account_id)
    logger.info("Account %s status: %s", c2_acc1.account_id[-4:], c2_acc1.status.name)

    try:
        c2_acc1.withdraw(Decimal("100.00"))
    except BankAccountError as e:
        logger.warning("Frozen account exception was caught: %s", e)

    bank.unfreeze_account(c2_acc1.account_id)
    logger.info("Account %s status: %s", c2_acc1.account_id[-4:], c2_acc1.status.name)
    c2_acc1.withdraw(Decimal("100.00"))
    logger.info("Withdraw successful. New balance: %s", c2_acc1.balance)

    logger.info("\n== 5. Closing accounts ==")
    try:
        bank.close_account(c2_acc1.account_id)
    except BankAccountError as e:
        logger.warning("Closing account exception was caught: %s", e)

    c2_acc1.withdraw(c2_acc1.balance)
    bank.close_account(c2_acc1.account_id)
    logger.info("Closing successful. New status: %s", c2_acc1.status.name)

    logger.info("\n== 6. Client ranking and search ==")
    ranking = bank.get_clients_ranking(target_currency=Currency.RUB)
    logger.info("Client ranking by balance:")
    for rank, (client, total_balance) in enumerate(ranking):
        logger.info(f"Rank {rank + 1}: {client.name}: {total_balance}")

    search_res = bank.search_accounts(currency=Currency.USD)
    logger.info("USD accounts found: %s", len(search_res))


if __name__ == "__main__":
    run_tests_day1()
    run_tests_day2()
    run_tests_day3()
