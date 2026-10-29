import logging
from datetime import date, time
from time import sleep
from decimal import Decimal
from unittest.mock import patch

import models
import utils
from exceptions import BankAccountError, NightOperationsForbiddenError
from models import Client, BankAccount, AccountStatus, Currency, SavingsAccount, PremiumAccount, InvestmentAccount, \
    AssetType, ClientStatus, Bank, TransactionQueue, TransactionProcessor, TransactionType, Transaction, \
    AuditLog, AuditLogLevel, RiskAnalyzer, RiskGuardedTransactionProcessor, TransactionHistory, TRANSACTION_HISTORY

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
    logger.info("\n=== RUNNING DAY 4 TESTS: TRANSACTIONS & QUEUE ===")

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


def run_tests_day5() -> None:
    logger.info("\n=== RUNNING DAY 5 TESTS: AUDIT & RISK ANALYSIS ===")

    logger.info("\n== 1. Prepare clients and accounts ==")
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
    client3 = Client(
        name="Тимофей Куликов",
        date_of_birth=date(2001, 3, 8),
        phone_number="+79261112233",
        status=ClientStatus.ACTIVE
    )

    acc_main = BankAccount(client1, Decimal("900000.00"), Currency.RUB, AccountStatus.ACTIVE)
    acc_second = BankAccount(client1, Decimal("50000.00"), Currency.RUB, AccountStatus.ACTIVE)
    acc_partner = BankAccount(client2, Decimal("100000.00"), Currency.RUB, AccountStatus.ACTIVE)
    acc_frozen = BankAccount(client3, Decimal("10000.00"), Currency.RUB, AccountStatus.FROZEN)
    acc_client3 = BankAccount(client3, Decimal("20000.00"), Currency.RUB, AccountStatus.ACTIVE)

    # Shared audit log; risk analyzer writes to it, and the processor blocks dangerous operations
    audit_log = AuditLog("audit")
    analyzer = RiskAnalyzer(audit_log)
    processor = RiskGuardedTransactionProcessor(analyzer)

    # helper builder
    def build_transaction(
            sender: BankAccount,
            recipient: BankAccount,
            amount_str: str,
            created_at=None
    ) -> Transaction:
        return Transaction(
            sender=sender,
            recipient=recipient,
            amount=Decimal(amount_str),
            currency=Currency.RUB,
            transaction_type=TransactionType.INTERNAL,
            created_at=created_at if created_at else datetime.now(),
        )


    sleep(1)
    logger.info("\n== 2. Standard transactions ==")
    for tx in (
            build_transaction(acc_main, acc_second, "5000.00"),
            build_transaction(acc_main, acc_second, "3000.00"),
    ):
        try:
            processor.process_transaction(tx)
        except BankAccountError as e:
            logger.warning("Standard transaction aborted: %s", e)


    sleep(1)
    logger.info("\n== 3. Large amount to new recipient (high risk -> block) ==")
    tx_large = build_transaction(acc_main, acc_partner, "600000.00")
    try:
        processor.process_transaction(tx_large)
    except BankAccountError as e:
        logger.warning("Suspicious transaction, blocked: %s", e)
        logger.info("Blocked transaction status: %s, resason: %s",
                    tx_large.status.value, tx_large.failure_reason)


    sleep(1)
    logger.info("\n== 4. Frequent transactions (series of money transfers -> medium risk) ==")
    for i in range(1, 5):
        tx = build_transaction(acc_main, acc_partner, "10000.00")
        try:
            processor.process_transaction(tx)
        except BankAccountError as e:
            logger.warning("Transaction %s aborted: %s", i, e)


    sleep(1)
    logger.info("\n== 5. Night time transactions ==")
    night_time = datetime.combine(date.today(), time(2, 30))
    tx_night_big = build_transaction(acc_partner, acc_main, "300000.00", created_at=night_time)
    try:
        processor.process_transaction(tx_night_big)
    except BankAccountError as e:
        logger.warning("Night time suspicious transaction blocked: %s", e)

    tx_night_small = build_transaction(acc_partner, acc_second, "1000.00", created_at=night_time)
    try:
        processor.process_transaction(tx_night_small)
    except BankAccountError as e:
        logger.warning("Night time transaction aborted: %s", e)


    sleep(1)
    logger.info("\n== 6. Transfer to frozen account (analyze completes, execution fails) ==")
    tx_to_frozen = build_transaction(acc_client3, acc_frozen, "500.00")
    try:
        processor.process_transaction(tx_to_frozen)
    except BankAccountError as e:
        logger.warning("Transaction aborted: %s (reason: %s)", e, tx_to_frozen.failure_reason)


    sleep(1)
    logger.info("\n== 7. Insufficient funds (analyze completes, execution fails) ==")
    tx_nsf = build_transaction(acc_partner, acc_second, "150000.00")
    try:
        processor.process_transaction(tx_nsf)
    except BankAccountError as e:
        logger.warning("Transaction aborted: %s (reason: %s)", e, tx_nsf.failure_reason)


    sleep(1)
    logger.info("\n== 8. Audit reports ==")
    audit_log.save_to_file("audit_log.txt")

    suspicious = audit_log.get_suspicious_entries()
    logger.info("Suspicious transactions in audit (%s):", len(suspicious))
    for entry in suspicious:
        logger.info("  %s", entry)

    logger.info("Error statistics: %s", audit_log.get_error_statistics())

    logger.info("Client risk profiles:")
    for profile in analyzer.get_all_risk_profiles():
        logger.info("%s", profile.summary())

    logger.info(
        "Critical records in audit: %s, records by client %s: %s",
        len(audit_log.filter_entries(min_level=AuditLogLevel.CRITICAL)),
        client1.name,
        len(audit_log.filter_entries(client_id=client1.client_id)),
    )

def run_tests_day6() -> None:
    logger.info("\n=== RUNNING DAY 6 TESTS: FULL BANK DEMONSTRATION ===")

    logger.info("\n== 1. Инициализация банка ==")
    bank = Bank("ДемоБанк")
    tx_queue = TransactionQueue()
    history = TRANSACTION_HISTORY

    audit_log = AuditLog("demo-audit")
    analyzer = RiskAnalyzer(audit_log)
    processor = RiskGuardedTransactionProcessor(analyzer)

    clients = [
        Client("Семён Персунов", date(1993, 5, 16), "+71234567890", ClientStatus.ACTIVE),
        Client("Номад Горячев", date(1988, 10, 20), "+79998887766", ClientStatus.ACTIVE),
        Client("Тимофей Куликов", date(2001, 3, 8), "+79261112233", ClientStatus.ACTIVE),
        Client("Анна Смирнова", date(1995, 9, 1), "+79160001234", ClientStatus.ACTIVE),
        Client("Игорь Волков", date(1979, 2, 14), "+79031234567", ClientStatus.ACTIVE),
        Client("Ольга Иванова", date(2000, 7, 30), "+79179876543", ClientStatus.ACTIVE),
    ]
    for client in clients:
        bank.add_client(client)

    c1, c2, c3, c4, c5, c6 = clients

    # обычные счета
    acc_c1_main = bank.open_account(c1.client_id, Currency.RUB, Decimal("800000.00"))
    acc_c1_usd = bank.open_account(c1.client_id, Currency.USD, Decimal("5000.00"))
    acc_c3_main = bank.open_account(c3.client_id, Currency.RUB, Decimal("500000.00"))
    acc_c4_usd = bank.open_account(c4.client_id, Currency.USD, Decimal("8000.00"))
    acc_c4_eur = bank.open_account(c4.client_id, Currency.EUR, Decimal("3000.00"))
    acc_c5_main = bank.open_account(c5.client_id, Currency.RUB, Decimal("150000.00"))
    acc_c6_main = bank.open_account(c6.client_id, Currency.RUB, Decimal("80000.00"))
    acc_c6_usd = bank.open_account(c6.client_id, Currency.USD, Decimal("2000.00"))

    # специальные счета
    acc_c2_premium = bank.open_premium_account(
        c2.client_id, Currency.RUB, Decimal("300000.00"), Decimal("50000.00"), Decimal("100.00"))
    acc_c3_savings = bank.open_savings_account(
        c3.client_id, Currency.RUB, Decimal("200000.00"), Decimal("100000.00"), Decimal("0.5"))
    acc_c5_savings = bank.open_savings_account(
        c5.client_id, Currency.RUB, Decimal("120000.00"), Decimal("60000.00"), Decimal("0.8"))
    acc_c6_invest = bank.open_investment_account(
        c6.client_id, Currency.RUB, Decimal("100000.00"))

    # замороженный и закрытый счета
    acc_frozen_target = bank.open_account(c2.client_id, Currency.RUB, Decimal("5000.00"))
    bank.freeze_account(acc_frozen_target.account_id)

    acc_closing_target = bank.open_account(c2.client_id, Currency.RUB, Decimal("1000.00"))
    acc_closing_target.withdraw(Decimal("1000.00"))
    bank.close_account(acc_closing_target.account_id)

    logger.info("Итого: клиентов=%s, счетов=%s, общий баланс банка=%s RUB",
                len(bank.clients), len(bank.accounts), bank.get_total_balance())

    # ------------------------------------------------------------------
    # Помощник: создаёт транзакцию (она сама попадает в TRANSACTION_HISTORY)
    # и кладёт её в очередь.
    # Возвращает None, если транзакция отклонена уже на этапе создания.
    # Приоритет назначается по порядку создания: чем раньше — тем выше,
    # чтобы порядок обработки в очереди совпадал с порядком создания.
    # created_at раскладывается в прошлое с шагом > 1 секунды, чтобы
    # фактор FREQUENT_OPERATIONS не срабатывал между обычными транзакциями.
    # ------------------------------------------------------------------
    tx_counter = [0]

    def submit_tx(
            sender: BankAccount,
            recipient: BankAccount,
            amount: Decimal,
            currency: Currency = Currency.RUB,
            tx_type: TransactionType = TransactionType.INTERNAL,
            created_at: datetime | None = None,
            scheduled_at: datetime | None = None,
    ) -> Transaction | None:
        try:
            tx = Transaction(
                sender=sender,
                recipient=recipient,
                amount=amount,
                currency=currency,
                transaction_type=tx_type,
                priority=1000 - tx_counter[0],
                created_at=created_at if created_at is not None
                else datetime.now() - timedelta(seconds=3 * tx_counter[0]),
                scheduled_at=scheduled_at,
            )
        except BankAccountError as e:
            logger.warning("❌ Транзакция отклонена при создании: %s", e)
            return None

        tx_counter[0] += 1
        tx_queue.add_transaction(tx)
        return tx


    logger.info("\n== 2. Очередь: приоритеты, отложенные и отменённые операции ==")

    # отложенная на час транзакция не берётся из очереди раньше времени
    scheduled_tx = submit_tx(acc_c1_main, acc_c2_premium, Decimal("1000.00"),
                             scheduled_at=datetime.now() + timedelta(hours=1))
    logger.info("Отложенная транзакция %s в очереди, доступна к исполнению: %s",
                scheduled_tx.transaction_id[-4:], tx_queue.get_next() is not None)

    urgent_tx = submit_tx(acc_c1_main, acc_c6_main, Decimal("1500.00"))
    regular_tx = submit_tx(acc_c1_usd, acc_c4_usd, Decimal("300.00"), Currency.USD)

    next_available = tx_queue.get_next()
    logger.info("Первая доступная к исполнению (высший приоритет): %s", next_available)

    tx_queue.cancel_transaction(regular_tx.transaction_id)
    logger.info("Отмена в очереди выполнена: статус %s, в очереди %s, доступно к исполнению %s",
                regular_tx.status.value, tx_queue.pending_count, tx_queue.get_next() is not None)


    logger.info("\n== 3. Основной поток транзакций ==")

    normal_transfers = [  # (отправитель, получатель, сумма, валюта, тип)
        (acc_c1_main, acc_c2_premium, "25000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c2_premium, acc_c3_main, "15000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c3_main, acc_c4_eur, "30000.00", Currency.RUB, TransactionType.INTERNAL),   # конвертация RUB → EUR
        (acc_c4_usd, acc_c1_main, "200.00", Currency.USD, TransactionType.INTERNAL),     # конвертация USD → RUB
        (acc_c5_main, acc_c6_main, "10000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c3_savings, acc_c3_main, "20000.00", Currency.RUB, TransactionType.INTERNAL),  # между своими счетами
        (acc_c6_invest, acc_c6_main, "5000.00", Currency.RUB, TransactionType.INTERNAL),    # между своими счетами
        (acc_c1_usd, acc_c4_usd, "500.00", Currency.USD, TransactionType.EXTERNAL),      # комиссия 1%
        (acc_c1_main, acc_c6_main, "7500.00", Currency.RUB, TransactionType.EXTERNAL),
        (acc_c5_savings, acc_c5_main, "5000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c2_premium, acc_c3_main, "5000.00", Currency.RUB, TransactionType.INTERNAL),   # повторный получатель
        (acc_c3_main, acc_c1_main, "8000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c4_eur, acc_c1_main, "100.00", Currency.EUR, TransactionType.INTERNAL),        # конвертация EUR → RUB
        (acc_c5_main, acc_c3_main, "20000.00", Currency.RUB, TransactionType.INTERNAL),
        (acc_c6_main, acc_c6_usd, "7500.00", Currency.RUB, TransactionType.INTERNAL),       # конвертация RUB → USD
    ]
    for sender, recipient, amount, curr, tx_type in normal_transfers:
        submit_tx(sender, recipient, Decimal(amount), curr, tx_type)


    logger.info("\n== 4. Подозрительные операции (риск-анализ) ==")

    # ночь (00:00–05:00) + крупная сумма + новый получатель → риск HIGH → блокировка
    submit_tx(acc_c4_usd, acc_c4_eur, Decimal("6000.00"), Currency.USD,
              created_at=datetime.combine(date.today(), time(1, 30)))

    # ночь, но получатель уже проверен ранее → риск MEDIUM → исполнится под мониторингом
    submit_tx(acc_c1_main, acc_c2_premium, Decimal("10000.00"), Currency.RUB,
              created_at=datetime.combine(date.today(), time(2, 30)))

    # крупная сумма проверенному получателю → риск MEDIUM → исполнится под мониторингом
    submit_tx(acc_c1_main, acc_c2_premium, Decimal("600000.00"))

    # серия переводов в коротком окне → у 3-й и 4-й фактор FREQUENT_OPERATIONS (MEDIUM)
    series_time = datetime.now()
    for _ in range(4):
        submit_tx(acc_c3_main, acc_c1_main, Decimal("5000.00"), created_at=series_time)

    # крупная сумма новому получателю днём → риск HIGH → блокировка
    submit_tx(acc_c3_main, acc_c6_invest, Decimal("550000.00"))

    # небольшой внешний перевод новому получателю → риск MEDIUM → исполнится
    submit_tx(acc_c6_usd, acc_c4_usd, Decimal("100.00"), Currency.USD, TransactionType.EXTERNAL)


    logger.info("\n== 5. Ошибочные операции ==")

    logger.info("-- Отклоняются при создании --")
    submit_tx(acc_c1_main, acc_c2_premium, Decimal("-500.00"))          # отрицательная сумма
    submit_tx(acc_c1_usd, acc_c2_premium, Decimal("100.00"), Currency.RUB)  # валюта не совпадает со счётом отправителя

    try:
        acc_c1_main.deposit(25)                                        # пополнение не Decimal
    except BankAccountError as e:
        logger.info("❌ Пополнение отклонено: %s", e)

    logger.info("-- Отклоняются при исполнении --")
    submit_tx(acc_c6_main, acc_frozen_target, Decimal("7000.00"))      # получатель заморожен
    submit_tx(acc_c6_main, acc_c1_main, Decimal("150000.00"))          # недостаточно средств
    submit_tx(acc_c3_savings, acc_c5_savings, Decimal("150000.00"))    # ниже минимального остатка накопительного счёта
    submit_tx(acc_c6_main, acc_closing_target, Decimal("500.00"))      # получатель закрыт


    logger.info("\n== 6. Обработка очереди ==")
    logger.info("Транзакций в очереди к исполнению: %s", tx_queue.pending_count)

    executed_count = 0
    rejected_count = 0
    while True:
        tx = tx_queue.get_next()
        if tx is None:
            break

        logger.info("")
        logger.info("Обработка -> %s", tx)
        try:
            processor.process_transaction(tx)  # сначала риск-анализ, затем исполнение (с повторными попытками)
            executed_count += 1
            logger.info("✅ Исполнена. Статус: %s, комиссия: %s %s",
                        tx.status.value, tx.fee, tx.sender.currency.value)
        except BankAccountError as e:
            rejected_count += 1
            logger.info("🚫 Отклонена: %s | Статус: %s | Причина: %s",
                        e, tx.status.value, tx.failure_reason)

    logger.info("Итог обработки: исполнено=%s, отклонено=%s", executed_count, rejected_count)

    # в очереди осталась только отложенная на час транзакция — закрываем её отменой
    logger.info("В очереди осталась отложенная транзакция: %s", scheduled_tx.transaction_id[-4:])
    tx_queue.cancel_transaction(scheduled_tx.transaction_id)
    logger.info("Отложенная транзакция отменена, очередь пуста: %s", tx_queue.pending_count)


    logger.info("\n== 7. Пользовательские сценарии ==")

    for client in (c1, c3):
        logger.info("\n— 💳 Счета клиента %s —", client.name)
        for account in bank.search_accounts(client_id=client.client_id):
            logger.info(account.get_account_info())

        client_history = history.get_by_client(client.client_id)
        logger.info("\n— 📜 История транзакций клиента %s (%s шт.) —", client.name, len(client_history))
        for tx in client_history:
            logger.info("%s", tx)

    logger.info("\n— ⚠️ Подозрительные операции —")
    suspicious_entries = audit_log.get_suspicious_entries()
    logger.info("Записей в аудит-журнале: %s", len(suspicious_entries))
    for entry in suspicious_entries:
        logger.info("  %s", entry)

    logger.info("Флаги подозрительной активности по клиенту %s: %s", c1.name, c1.suspicious_activities)

    # ------------------------------------------------------------------
    # == 8. Отчёты
    # ------------------------------------------------------------------
    logger.info("\n== 8. Отчёты ==")

    logger.info("\n— 🏆 Топ-3 клиентов по балансу —")
    for rank, (client, total) in enumerate(bank.get_clients_ranking(top_n=3), start=1):
        logger.info("%s место: %s — %s RUB", rank, client.name, total)

    logger.info("\n— 📊 Статистика транзакций —")
    stats = history.get_statistics()
    logger.info("Всего транзакций: %s", stats["total"])
    for status_name, count in stats["by_status"].items():
        logger.info("  %s: %s", status_name, count)
    logger.info("Отклонено (FAILED/CANCELLED): %s", stats["rejected"])
    logger.info("Доля успешных: %s%%", stats["success_rate"])
    for currency, volume in stats["completed_volume_by_currency"].items():
        logger.info("  Объём исполненных %s: %s", currency.value, volume)
    for currency, fees in stats["fees_by_currency"].items():
        logger.info("  Собрано комиссий %s: %s", currency.value, fees)

    logger.info("\n— 💎 Общий баланс банка —")
    logger.info("%s RUB", bank.get_total_balance())


if __name__ == "__main__":
    # run_tests_day1()
    # run_tests_day2()
    # run_tests_day3()
    # run_tests_day4()
    # run_tests_day5()
    run_tests_day6()
