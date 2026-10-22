import logging
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

import models
import utils
from exceptions import BankAccountError, NightOperationsForbiddenError
from models import Client, BankAccount, AccountStatus, Currency, SavingsAccount, PremiumAccount, InvestmentAccount, \
    AssetType, ClientStatus, Bank, TransactionQueue, TransactionProcessor, TransactionType, Transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


def run_tests_day1() -> None:
    logger.info("\n=== RUNNING DAY 1 TESTS: BASE ACCOUNT ===")

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
        logger.info(f"{e.__class__.__name__}: {e}")

    # ✅ валидное пополнение и снятие
    active_account.withdraw(Decimal("300.00"))
    active_account.deposit(Decimal("500.00"))


def run_tests_day2() -> None:
    logger.info("\n=== RUNNING DAY 2 TESTS: ADVANCED ACCOUNTS ===")

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
    logger.info("\n=== RUNNING DAY 3 TESTS: BANK & CLIENT ===")

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


from datetime import datetime, timedelta


def run_tests_day4() -> None:
    logger.info("\n=== RUNNING DAY 4 TESTS: TRANSACTIONS & QUEUE (WITH FIXES) ===")

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

    acc_rub_1 = BankAccount(client1, Decimal("50000.00"), Currency.RUB, AccountStatus.ACTIVE)
    acc_usd_1 = BankAccount(client1, Decimal("1000.00"), Currency.USD, AccountStatus.ACTIVE)

    acc_savings = SavingsAccount(
        client=client1,
        balance=Decimal("10000.00"),
        currency=Currency.RUB,
        status=AccountStatus.ACTIVE,
        min_balance=Decimal("5000.00"),
        monthly_rate=Decimal("1.0")
    )

    acc_premium = PremiumAccount(
        client=client2,
        balance=Decimal("5000.00"),
        currency=Currency.RUB,
        status=AccountStatus.ACTIVE,
        overdraft_limit=Decimal("10000.00"),
        fixed_fee=Decimal("50.00")
    )

    acc_frozen = BankAccount(client2, Decimal("10000.00"), Currency.RUB, AccountStatus.FROZEN)

    tx_queue = TransactionQueue()
    processor = TransactionProcessor()

    try:
        bad_tx1 = Transaction(
            sender=acc_rub_1, recipient=acc_premium,
            amount=Decimal("-100.00"), currency=Currency.RUB,
            transaction_type=TransactionType.INTERNAL
        )
    except Exception as e:
        logger.info("Caught expected negative amount error: %s", e)

    try:
        bad_currency_tx = Transaction(
            sender=acc_usd_1, recipient=acc_premium,
            amount=Decimal("10.00"), currency=Currency.RUB,
            transaction_type=TransactionType.EXTERNAL
        )
    except Exception as e:
        logger.info("Caught expected currency mismatch error: %s", e)

    logger.info("\n--- 2. Testing Scheduled (Delayed) Transactions ---")
    future_time = datetime.now() + timedelta(hours=1)
    scheduled_tx = Transaction(
        sender=acc_rub_1,
        recipient=acc_premium,
        amount=Decimal("1000.00"),
        currency=Currency.RUB,
        transaction_type=TransactionType.INTERNAL,
        priority=100,
        scheduled_at=future_time
    )
    tx_queue.add_transaction(scheduled_tx)

    next_tx = tx_queue.get_next()
    if next_tx is None:
        logger.info("Scheduled transaction correctly ignored by get_next() before its time.")

    transactions_data = [
        (acc_rub_1, acc_frozen, Decimal("1000.00"), Currency.RUB, TransactionType.INTERNAL, 10),

        (acc_savings, acc_rub_1, Decimal("8000.00"), Currency.RUB, TransactionType.INTERNAL, 8),

        (acc_rub_1, acc_usd_1, Decimal("5000.00"), Currency.RUB, TransactionType.INTERNAL, 1),
        (acc_rub_1, acc_premium, Decimal("10000.00"), Currency.RUB, TransactionType.EXTERNAL, 5),
        (acc_usd_1, acc_rub_1, Decimal("100.00"), Currency.USD, TransactionType.EXTERNAL, 2),
        (acc_premium, acc_rub_1, Decimal("3000.00"), Currency.RUB, TransactionType.INTERNAL, 3),
    ]

    for sender, recipient, amount, curr, tx_type, priority in transactions_data:
        try:
            tx = Transaction(
                sender=sender,
                recipient=recipient,
                amount=amount,
                currency=curr,
                transaction_type=tx_type,
                priority=priority
            )
            tx_queue.add_transaction(tx)
        except Exception as e:
            logger.error("Failed to add transaction to queue: %s", e)

    logger.info("Total pending transactions in queue: %s", tx_queue.pending_count)

    while tx_queue.pending_count > 0:
        tx = tx_queue.get_next()
        if not tx:
            break

        logger.info("\nProcessing -> %s", tx)
        try:
            processor.process_transaction(tx)
            logger.info("Execution success! Status: %s, Fee: %s", tx.status.value, tx.fee)
        except Exception as e:
            logger.info("Transaction cancelled/failed: %s (Reason: %s)", e, tx.failure_reason)

    logger.info("\n--- 3. Testing Premium account operation safety checks ---")

    premium_safety_acc = PremiumAccount(
        client=client2,
        balance=Decimal("5000.00"),
        currency=Currency.RUB,
        status=AccountStatus.ACTIVE,
        overdraft_limit=Decimal("10000.00"),
        fixed_fee=Decimal("50.00")
    )

    balance_before_night = premium_safety_acc.balance
    try:
        with patch.object(models, "check_night_curfew",
                          lambda: utils.check_night_curfew(time(3, 0))):
            premium_safety_acc.process_outgoing_transfer(Decimal("100.00"))
    except NightOperationsForbiddenError as e:
        logger.info("Caught expected night curfew error for premium transfer: %s", e)
    else:
        logger.error("Premium transfer PASSED during night time (00:00-05:00)! This must not happen.")

    if premium_safety_acc.balance == balance_before_night:
        logger.info("Blocked night transfer did not change balance: %s %s",
                    premium_safety_acc.balance, premium_safety_acc.currency.value)
    else:
        logger.error("Blocked night transfer changed balance: %s -> %s", balance_before_night, premium_safety_acc.balance)

    premium_large_acc = PremiumAccount(
        client=client2,
        balance=Decimal("600000.00"),
        currency=Currency.RUB,
        status=AccountStatus.ACTIVE,
        overdraft_limit=Decimal("10000.00"),
        fixed_fee=Decimal("50.00")
    )

    try:
        premium_large_acc.process_outgoing_transfer(Decimal("550000.00"))
        logger.info("Large premium transfer COMPLETED. Sender balance now: %s %s",
                    premium_large_acc.balance, premium_large_acc.currency.value)
    except BankAccountError as e:
        logger.error("Large premium transfer unexpectedly failed: %s", e)

    if client2.suspicious_activities:
        logger.info("Suspicious activities of Client %s: %s",
                    client2.client_id, client2.suspicious_activities)
    else:
        logger.error("Large premium transfer was NOT flagged as suspicious! This must not happen.")

if __name__ == "__main__":
    run_tests_day1()
    run_tests_day2()
    run_tests_day3()
    run_tests_day4()
