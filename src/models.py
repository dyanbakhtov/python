from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from enum import Enum, IntEnum
from typing import Optional, Dict

from dateutil.relativedelta import relativedelta

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    BankAccountError,
    InsufficientFundsError,
    InvalidOperationError,
    SuspiciousActivityError,
)
from utils import CURFEW_END, CURFEW_START, generate_short_uuid, check_night_curfew

logger = logging.getLogger(__name__)


class TransactionStatus(Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


class TransactionType(Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


@dataclass
class Transaction:
    sender: BankAccount
    recipient: BankAccount
    amount: Decimal
    currency: Currency
    transaction_type: TransactionType
    transaction_id: str = field(default_factory=generate_short_uuid)
    fee: Decimal = field(default_factory=lambda: Decimal("0.00"))
    status: TransactionStatus = TransactionStatus.PENDING
    failure_reason: Optional[str] = None
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise InvalidOperationError(f"Amount must be a Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise InvalidOperationError(f"Amount must be finite number, got {self.amount}")
        if self.amount <= Decimal("0.00"):
            raise InvalidOperationError(f"Amount must be positive, got {self.amount}")

        if not isinstance(self.currency, Currency):
            raise InvalidOperationError(
                f"Invalid currency: {self.currency}. Expected Currency enum, got {type(self.currency).__name__}"
            )
        if self.currency != self.sender.currency:
            raise InvalidOperationError(
                f"Transaction currency {self.currency.value} does not match sender currency {self.sender.currency.value}"
            )

        if not isinstance(self.transaction_type, TransactionType):
            raise InvalidOperationError(
                f"Invalid transaction type: {self.transaction_type}. Expected TransactionType enum, got {type(self.transaction_type).__name__}"
            )

        if self.scheduled_at is None:
            self.scheduled_at = self.created_at

    def __str__(self) -> str:
        return (
            f"Tx[{self.transaction_id[-4:]}] | {self.transaction_type.value} | "
            f"Amount: {self.amount} {self.currency.value} (Fee: {self.fee}) | "
            f"Status: {self.status.value}"
        )


class TransactionQueue:
    def __init__(self) -> None:
        self._queue: list[Transaction] = []

    def add_transaction(self, transaction: Transaction) -> None:
        if transaction.status != TransactionStatus.PENDING:
            raise InvalidOperationError("Only pending transactions can be added to the queue.")
        self._queue.append(transaction)
        self._queue.sort(key=lambda t: t.priority, reverse=True)
        logger.info("Transaction %s added to queue with priority %s.",
                    transaction.transaction_id[-4:], transaction.priority)

    def get_next(self) -> Optional[Transaction]:
        now = datetime.now()
        for tx in self._queue:
            if tx.status == TransactionStatus.PENDING and tx.scheduled_at <= now:
                return tx
        return None

    def cancel_transaction(self, transaction_id: str) -> None:
        for tx in self._queue:
            if tx.transaction_id == transaction_id:
                if tx.status == TransactionStatus.COMPLETED:
                    raise InvalidOperationError("Cannot cancel an already completed transaction.")
                tx.status = TransactionStatus.CANCELLED
                tx.failure_reason = "Cancelled by user or system request."
                logger.info("Transaction %s cancelled.", transaction_id[-4:])
                return
        raise InvalidOperationError(f"Transaction {transaction_id} not found in queue.")

    @property
    def pending_count(self) -> int:
        return sum(1 for tx in self._queue if tx.status == TransactionStatus.PENDING)


class TransactionProcessor:
    EXTERNAL_FEE_RATE = Decimal("0.01")
    MAX_TRANSACTION_RETRIES = 3

    def __init__(self, exchange_rates: Optional[dict[Currency, Decimal]] = None) -> None:
        self.rates = exchange_rates or DEFAULT_EXCHANGE_RATES

    def process_transaction(self, transaction: Transaction) -> None:
        attempts = 0
        while attempts < self.MAX_TRANSACTION_RETRIES:
            try:
                self._execute(transaction)
                return
            except (InsufficientFundsError, AccountFrozenError, AccountClosedError) as e:
                attempts += 1
                transaction.status = TransactionStatus.RETRYING
                logger.warning("Transaction %s failed (attempt %s/%s): %s. Retrying...",
                               transaction.transaction_id[-4:], attempts, self.MAX_TRANSACTION_RETRIES, e)
                if attempts >= self.MAX_TRANSACTION_RETRIES:
                    transaction.status = TransactionStatus.FAILED
                    transaction.failure_reason = str(e)
                    transaction.processed_at = datetime.now()
                    logger.error("Transaction %s permanently failed: %s", transaction.transaction_id[-4:], e)
                    raise
            except Exception as e:
                transaction.status = TransactionStatus.FAILED
                transaction.failure_reason = str(e)
                transaction.processed_at = datetime.now()
                logger.error("Unexpected error in transaction %s: %s", transaction.transaction_id[-4:], e)
                raise

    def _execute(self, transaction: Transaction) -> None:
        sender = transaction.sender
        recipient = transaction.recipient

        fee = Decimal("0.00")
        if transaction.transaction_type == TransactionType.EXTERNAL:
            fee = (transaction.amount * self.EXTERNAL_FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        transaction.fee = fee
        sender_amount = transaction.amount + fee

        recipient_amount = transaction.amount
        if sender.currency != recipient.currency:
            recipient_amount = self._convert(transaction.amount, sender.currency, recipient.currency)

        recipient.validate_transaction(recipient_amount)

        sender.process_outgoing_transfer(sender_amount)
        recipient.process_incoming_transfer(recipient_amount)

        transaction.status = TransactionStatus.COMPLETED
        transaction.processed_at = datetime.now()
        logger.info(
            "Transaction %s completed successfully: -%s %s from Account %s, +%s %s to Account %s (Fee: %s)",
            transaction.transaction_id[-4:], sender_amount, sender.currency.value, sender.account_id[-4:],
            recipient_amount, recipient.currency.value, recipient.account_id[-4:], fee
        )

    def _convert(self, amount: Decimal, from_curr: Currency, to_curr: Currency) -> Decimal:
        if from_curr == to_curr:
            return amount

        if from_curr not in self.rates or to_curr not in self.rates:
            raise InvalidOperationError(f"Exchange rate not found for {from_curr.value} -> {to_curr.value}")

        amount_in_base = amount * self.rates[from_curr]
        result = amount_in_base / self.rates[to_curr]
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


class ClientStatus(Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class Currency(Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


DEFAULT_EXCHANGE_RATES: dict[Currency, Decimal] = {
    Currency.RUB: Decimal("1.0"),
    Currency.USD: Decimal("90.0"),
    Currency.EUR: Decimal("98.0"),
    Currency.KZT: Decimal("0.2"),
    Currency.CNY: Decimal("12.5"),
}


@dataclass
class Client:
    name: str
    date_of_birth: date
    phone_number: str | list[str]
    status: ClientStatus
    login_attempts: int = 0
    accounts: list[BankAccount] = field(default_factory=list)
    client_id: str = field(default_factory=generate_short_uuid)
    _password: str = field(default_factory=generate_short_uuid)
    suspicious_activities: list[str] = field(default_factory=list)

    @property
    def age(self) -> int:
        return relativedelta(date.today(), self.date_of_birth).years

    @property
    def is_adult(self) -> bool:
        return self.age >= 18

    @property
    def password(self) -> str:
        return self._password

    def fail_login(self) -> None:
        self.login_attempts += 1

    def reset_login_attempts(self) -> None:
        self.login_attempts = 0

    def flag_suspicious_activity(self, reason: str) -> None:
        timestamp = datetime.now().isoformat()
        entry = f"[{timestamp}] {reason}"
        self.suspicious_activities.append(entry)
        logger.warning("Suspicious activity flagged for Client %s: %s", self.client_id[-4:], reason)

    def get_total_balance(
            self,
            target_currency: Currency = Currency.RUB,
            rates: dict[Currency, Decimal] | None = None
    ) -> Decimal:
        if rates is None:
            rates = DEFAULT_EXCHANGE_RATES

        if target_currency not in rates:
            raise InvalidOperationError(f"Target currency rate {target_currency.value} not found.")

        target_rate = rates[target_currency]
        total_in_base = Decimal("0.00")

        for account in self.accounts:
            if account.status == AccountStatus.CLOSED:
                continue

            if account.currency not in rates:
                raise InvalidOperationError(f"Currency rate {account.currency.value} not found.")

            acc_rate = rates[account.currency]
            balance_in_base = account.balance * acc_rate
            total_in_base += balance_in_base

        total_in_target = total_in_base / target_rate
        return total_in_target.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def __post_init__(self) -> None:
        if not self.is_adult:
            raise InvalidOperationError(f"Client initialization failed: client {self.client_id[-4:]} {self.name}"
                                        f" is not adult (current age: {self.age})")

    def __str__(self) -> str:
        return f"{self.client_id[-4:]} {self.name}, {self.date_of_birth}, {self.phone_number}, {self.status.value}"


class AccountStatus(Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AbstractAccount(ABC):
    def __init__(
            self,
            account_id: str,
            client: Client,
            balance: Decimal,
            status: AccountStatus
    ) -> None:
        if not isinstance(status, AccountStatus):
            raise InvalidOperationError(
                f"Invalid account status: {status}. Expected AccountStatus enum, got {type(status).__name__}")

        self.account_id = account_id
        self.client = client
        self._balance = balance
        self.status = status

    @property
    def balance(self) -> Decimal:
        return self._balance

    @abstractmethod
    def deposit(self, amount: Decimal) -> None:
        pass

    @abstractmethod
    def withdraw(self, amount: Decimal) -> None:
        pass

    @abstractmethod
    def get_account_info(self) -> str:
        pass

    def _validate_status(self) -> None:
        if self.status == AccountStatus.FROZEN:
            raise AccountFrozenError("Operation prohibited: account is frozen")
        if self.status == AccountStatus.CLOSED:
            raise AccountClosedError("Operation prohibited: account is closed")
        if self.status != AccountStatus.ACTIVE:
            raise InvalidOperationError(f"Operation prohibited: account status is {self.status.name}")

    @staticmethod
    def _validate_money_amount(amount: Decimal, param_name: str = "Amount", allow_zero: bool = False) -> None:
        if not isinstance(amount, Decimal):
            raise InvalidOperationError(f"{param_name} must be a Decimal, got {type(amount).__name__}")
        if not amount.is_finite():
            raise InvalidOperationError(f"{param_name} must be finite number, got {amount}")

        if allow_zero:
            if amount < Decimal("0.00"):
                raise InvalidOperationError(f"{param_name} cannot be negative, got {amount}")
        else:
            if amount <= Decimal("0.00"):
                raise InvalidOperationError(f"{param_name} must be positive, got {amount}")


class BankAccount(AbstractAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            status: AccountStatus,
            account_id: Optional[str] = None
    ) -> None:
        if not isinstance(currency, Currency):
            raise InvalidOperationError(
                f"Invalid currency: {currency}. Expected Currency enum, got {type(currency).__name__}")

        self._validate_money_amount(balance, param_name="Initial balance", allow_zero=True)
        actual_id = account_id if account_id is not None else generate_short_uuid()
        self.currency = currency
        super().__init__(actual_id, client, balance, status)

        logger.info("Account created. %s", self)

    SUSPICIOUS_TRANSACTION_THRESHOLD = Decimal("500000.00")

    def validate_transaction(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_operation_safety(amount)

    def _validate_operation_safety(self, amount: Decimal) -> None:
        check_night_curfew()

        if amount >= self.SUSPICIOUS_TRANSACTION_THRESHOLD:
            self.client.flag_suspicious_activity(
                f"Large transaction of {amount} {self.currency.value} on the account {self.account_id[-4:]}"
            )

    def deposit(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Deposit amount")
        self._validate_operation_safety(amount)
        self._balance += amount
        logger.info(
            "Deposit successful: Account=%s, Amount=+%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
        )

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Withdrawal amount")
        self._validate_operation_safety(amount)

        if self.balance < amount:
            raise InsufficientFundsError(
                f"Withdraw failed: insufficient balance {self.balance} {self.currency.value}")

        self._balance -= amount
        logger.info(
            "Withdrawal successful: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
        )

    def process_incoming_transfer(self, amount: Decimal) -> None:
        self._balance += amount
        logger.info(
            "Incoming transfer received: Account=%s, Amount=+%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
        )

    def process_outgoing_transfer(self, amount_with_fee: Decimal) -> None:
        self.validate_transaction(amount_with_fee)

        if self.balance < amount_with_fee:
            raise InsufficientFundsError(
                f"Insufficient funds: balance {self.balance} {self.currency.value}, required {amount_with_fee}"
            )

        self._balance -= amount_with_fee
        logger.info(
            "Outgoing transfer sent: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount_with_fee, self.currency.value, self.balance, self.currency.value
        )

    def get_account_info(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return (
            f"Type: {self.__class__.__name__} | Client: {self.client} | Account Number: {self.account_id[-4:]} | "
            f"Status: {self.status.name} | Balance: {self.balance} {self.currency.value}"
        )


class Bank:
    def __init__(self, name: str = "Zalupabank") -> None:
        self.name = name
        self.clients: dict[str, Client] = {}
        self.accounts: dict[str, BankAccount] = {}

    def add_client(self, client: Client) -> None:
        if client.client_id in self.clients:
            raise InvalidOperationError(f"Client {client.client_id} already exists.")
        self.clients[client.client_id] = client
        logger.info(f"Client {client.client_id[-4:]} added.")

    def open_account(self, client_id: str, currency: Currency,
                     initial_balance: Decimal = Decimal("0.00")) -> BankAccount:
        client = self._get_client(client_id)
        if client.status == ClientStatus.BLOCKED:
            raise InvalidOperationError("Client is blocked.")

        account = BankAccount(
            client=client,
            balance=initial_balance,
            currency=currency,
            status=AccountStatus.ACTIVE
        )

        self.accounts[account.account_id] = account
        client.accounts.append(account)
        return account

    def close_account(self, account_id: str) -> None:
        account = self._get_account(account_id)
        if account.status == AccountStatus.CLOSED:
            raise InvalidOperationError("Account is already closed.")
        if account.balance != Decimal("0.00"):
            raise InvalidOperationError(f"Cannot close account with non-zero balance ({account.balance}).")

        account.status = AccountStatus.CLOSED
        logger.info("Account %s closed.", account_id[-4:])

    def freeze_account(self, account_id: str) -> None:
        account = self._get_account(account_id)
        if account.status == AccountStatus.CLOSED:
            raise InvalidOperationError("Cannot freeze a closed account.")
        if account.status == AccountStatus.FROZEN:
            raise InvalidOperationError("Account is already frozen.")

        account.status = AccountStatus.FROZEN
        logger.info("Account %s frozen.", account_id[-4:])

    def unfreeze_account(self, account_id: str) -> None:
        account = self._get_account(account_id)
        if account.status != AccountStatus.FROZEN:
            raise InvalidOperationError(f"Cannot unfreeze account with status {account.status.name}.")

        account.status = AccountStatus.ACTIVE
        logger.info("Account %s unfrozen.", account_id[-4:])

    MAX_LOGIN_ATTEMPTS = 3

    def authenticate_client(self, client_id: str, password: str) -> bool:
        client = self._get_client(client_id)

        if client.status == ClientStatus.BLOCKED:
            raise InvalidOperationError(f"Client {client_id} is blocked.")

        if password == client.password:
            client.reset_login_attempts()
            return True

        client.fail_login()
        if client.login_attempts >= self.MAX_LOGIN_ATTEMPTS:
            client.status = ClientStatus.BLOCKED
            client.flag_suspicious_activity(f"Maximum number of login attempts exceeded. Client is blocked.")
            logger.warning("Client %s blocked due to 3 failed login attempts.", client_id)

        return False

    def search_accounts(
            self,
            client_id: Optional[str] = None,
            currency: Optional[Currency] = None,
            status: Optional[AccountStatus] = None,
    ) -> list[BankAccount]:
        result = list(self.accounts.values())

        if client_id is not None:
            self._get_client(client_id)
            result = [acc for acc in result if acc.client.client_id == client_id]

        if currency is not None:
            result = [acc for acc in result if acc.currency == currency]

        if status is not None:
            result = [acc for acc in result if acc.status == status]

        return result

    def get_total_balance(
            self,
            target_currency: Currency = Currency.RUB,
            rates: dict[Currency, Decimal] | None = None
    ) -> Decimal:
        if rates is None:
            rates = DEFAULT_EXCHANGE_RATES

        if target_currency not in rates:
            raise InvalidOperationError(f"Target currency rate {target_currency.value} not found.")

        target_rate = rates[target_currency]
        total_in_base = Decimal("0.00")

        for account in self.accounts.values():
            if account.status == AccountStatus.CLOSED:
                continue

            if account.currency not in rates:
                raise InvalidOperationError(f"Currency rate {account.currency.value} not found.")

            acc_rate = rates[account.currency]
            balance_in_base = account.balance * acc_rate
            total_in_base += balance_in_base

        total_in_target = total_in_base / target_rate
        return total_in_target.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_clients_ranking(
            self,
            target_currency: Currency = Currency.RUB,
            rates: dict[Currency, Decimal] | None = None,
            top_n: int | None = None
    ) -> list[tuple[Client, Decimal]]:

        ranking = [
            (client, client.get_total_balance(target_currency, rates))
            for client in self.clients.values()
        ]

        ranking.sort(key=lambda item: item[1], reverse=True)

        if top_n is not None:
            return ranking[:top_n]

        return ranking

    def _get_client(self, client_id: str) -> Client:
        client = self.clients.get(client_id)
        if not client:
            raise InvalidOperationError(f"Client with ID {client_id} not found.")
        return client

    def _get_account(self, account_id: str) -> BankAccount:
        account = self.accounts.get(account_id)
        if not account:
            raise InvalidOperationError(f"Account {account_id} not found.")
        return account


class SavingsAccount(BankAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            status: AccountStatus,
            min_balance: Decimal,
            monthly_rate: Decimal,
            account_id: Optional[str] = None
    ) -> None:
        self._validate_money_amount(min_balance, param_name="Min Balance", allow_zero=True)
        if not isinstance(monthly_rate, Decimal) or monthly_rate <= Decimal("0") or monthly_rate > Decimal("100"):
            raise InvalidOperationError("Invalid monthly rate, must be between 0 and 100")

        self.min_balance = min_balance
        self.monthly_rate = monthly_rate

        super().__init__(client, balance, currency, status, account_id)

        if self.balance < self.min_balance:
            raise InsufficientFundsError(f"Balance cannot be less than min balance: "
                                         f"balance= {self.balance} {self.currency.value}, "
                                         f"min_balance= {min_balance} {self.currency.value}")

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Withdrawal amount")
        self._validate_operation_safety(amount)

        if (self.balance - amount) < self.min_balance:
            raise InsufficientFundsError(f"Withdraw failed: remaining balance would drop below min balance "
                                         f"({self.min_balance} {self.currency.value})")

        self._balance -= amount
        logger.info(
            "Withdrawal successful: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
        )

    def process_outgoing_transfer(self, amount_with_fee: Decimal) -> None:
        self.validate_transaction(amount_with_fee)

        if (self.balance - amount_with_fee) < self.min_balance:
            raise InsufficientFundsError(
                f"Savings transfer failed: remaining balance would drop below min balance "
                f"({self.min_balance} {self.currency.value})"
            )

        self._balance -= amount_with_fee
        logger.info(
            "Savings outgoing transfer sent: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount_with_fee, self.currency.value, self.balance, self.currency.value
        )

    def apply_monthly_interest(self) -> None:
        self._validate_status()
        interest_amount = (self.balance * (self.monthly_rate / Decimal("100.00"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        self._balance += interest_amount
        logger.info("Monthly interest applied: Account=%s, Added=%s %s, New Balance =%s %s",
                    self.account_id[-4:], interest_amount, self.currency.value, self.balance, self.currency.value)

    def __str__(self) -> str:
        return super().__str__() + f" | Min Balance: {self.min_balance} {self.currency.value} | Monthly Rate: {self.monthly_rate}%"

    def get_account_info(self) -> str:
        return str(self)


class PremiumAccount(BankAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            status: AccountStatus,
            overdraft_limit: Decimal,
            fixed_fee: Decimal,
            account_id: Optional[str] = None
    ) -> None:
        self._validate_money_amount(overdraft_limit, param_name="Overdraft limit", allow_zero=True)
        self._validate_money_amount(fixed_fee, param_name="Fixed fee", allow_zero=True)

        self.overdraft_limit = overdraft_limit
        self.fixed_fee = fixed_fee

        super().__init__(client, balance, currency, status, account_id)

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Withdrawal amount")
        self._validate_operation_safety(amount)

        total_deduction = amount + self.fixed_fee
        total_available_funds = self.balance + self.overdraft_limit
        account_currency = self.currency.value
        if total_available_funds < total_deduction:
            raise InsufficientFundsError(
                f"Withdraw failed: total required ({total_deduction} {account_currency} incl. fee {self.fixed_fee} {account_currency})"
                f" exceeds total available funds with overdraft ({total_available_funds} {account_currency})"
            )
        self._balance -= total_deduction
        logger.info(
            "Premium withdrawal successful: Account=%s, Amount=%s %s, Fee=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, account_currency, self.fixed_fee, account_currency, self.balance,
            account_currency
        )

    def process_outgoing_transfer(self, amount_with_fee: Decimal) -> None:
        self.validate_transaction(amount_with_fee)

        total_available = self.balance + self.overdraft_limit
        if total_available < amount_with_fee:
            raise InsufficientFundsError(
                f"Premium account overdraft exceeded: available {total_available} {self.currency.value}, required {amount_with_fee}"
            )

        self._balance -= amount_with_fee
        logger.info(
            "Premium outgoing transfer sent: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount_with_fee, self.currency.value, self.balance, self.currency.value
        )

    def __str__(self) -> str:
        return super().__str__() + (f" | Overdraft Limit: {self.overdraft_limit} {self.currency.value}"
                                    f" | Fixed Fee: {self.fixed_fee} {self.currency.value}")

    def get_account_info(self) -> str:
        return str(self)


class AssetType(str, Enum):
    STOCKS = "stocks"
    BONDS = "bonds"
    ETF = "etf"

    @classmethod
    def normalize(cls, asset_type: str | AssetType) -> AssetType:
        if isinstance(asset_type, cls):
            return asset_type

        try:
            return cls(str(asset_type).lower().strip())
        except ValueError:
            raise InvalidOperationError(f"Invalid asset type: {asset_type}")


class InvestmentAccount(BankAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            status: AccountStatus,
            account_id: Optional[str] = None
    ) -> None:
        self.portfolio: Dict[AssetType, Decimal] = {
            AssetType.STOCKS: Decimal("0.00"),
            AssetType.BONDS: Decimal("0.00"),
            AssetType.ETF: Decimal("0.00")
        }

        super().__init__(client, balance, currency, status, account_id)

    def withdraw(self, amount: Decimal) -> None:
        super().withdraw(amount)

    def buy_asset(self, asset_type: str | AssetType, amount: Decimal) -> None:
        self._validate_status()
        asset = AssetType.normalize(asset_type)
        self._validate_money_amount(amount, param_name="Amount")
        self._validate_operation_safety(amount)

        if self.balance < amount:
            raise InsufficientFundsError(
                f"Asset buy failed: balance {self.balance} {self.currency.value} insufficient"
            )
        self._balance -= amount
        self.portfolio[asset] += amount
        logger.info("Asset buy successful: %s, Amount=%s", asset, amount)

    def project_yearly_growth(self, growth_rates: Dict[str | AssetType, Decimal]) -> Decimal:
        self._validate_status()

        normalized_rates: Dict[AssetType, Decimal] = {}

        for k, v in growth_rates.items():
            asset = AssetType.normalize(k)
            self._validate_money_amount(v, param_name=f"Rate for {k}", allow_zero=True)
            normalized_rates[asset] = v

        total_growth = Decimal("0.00")

        for asset_type, invested_amount in self.portfolio.items():
            if invested_amount > Decimal("0.00"):
                if asset_type not in normalized_rates:
                    logger.warning("Missing growth rate for asset type: '%s'", asset_type.value)
                    continue
                rate = normalized_rates[asset_type]
                growth = (invested_amount * (rate / Decimal("100"))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_EVEN
                )
                logger.info("growth rate for %s: %s", asset_type, growth)
                total_growth += growth
        return total_growth

    def __str__(self) -> str:
        portfolio_details = ", ".join(
            f"{asset.value}: {amount} {self.currency.value}"
            for asset, amount in self.portfolio.items()
        )
        return super().__str__() + f" | Portfolio: [{portfolio_details}]"

    def get_account_info(self) -> str:
        return str(self)


# ============================================================
# Day 5: audit and risk analysis
# ============================================================


class AuditLogLevel(IntEnum):
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


_AUDIT_LEVEL_TO_LOGGING: dict[AuditLogLevel, int] = {
    AuditLogLevel.INFO: logging.INFO,
    AuditLogLevel.WARNING: logging.WARNING,
    AuditLogLevel.ERROR: logging.ERROR,
    AuditLogLevel.CRITICAL: logging.CRITICAL,
}


class AuditCategory(str, Enum):
    TRANSACTION = "TRANSACTION"
    RISK = "RISK"
    AUTH = "AUTH"
    SYSTEM = "SYSTEM"


@dataclass
class AuditEntry:
    level: AuditLogLevel
    message: str
    category: AuditCategory
    timestamp: datetime = field(default_factory=datetime.now)
    client_id: Optional[str] = None
    account_id: Optional[str] = None

    def to_file_line(self) -> str:
        parts = [
            self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            self.level.name,
            self.category.value,
            self.message,
        ]
        if self.client_id:
            parts.append(f"client={self.client_id[-4:]}")
        if self.account_id:
            parts.append(f"account={self.account_id[-4:]}")
        return " | ".join(parts)

    def __str__(self) -> str:
        return self.to_file_line()


class AuditLog:
    def __init__(self, name: str = "audit") -> None:
        self.name = name
        self._entries: list[AuditEntry] = []

    def log(
            self,
            level: AuditLogLevel,
            message: str,
            category: AuditCategory = AuditCategory.SYSTEM,
            client_id: Optional[str] = None,
            account_id: Optional[str] = None,
    ) -> AuditEntry:
        if not isinstance(level, AuditLogLevel):
            raise InvalidOperationError(
                f"Invalid audit level: {level}. Expected AuditLogLevel, got {type(level).__name__}"
            )
        if not isinstance(category, AuditCategory):
            raise InvalidOperationError(
                f"Invalid audit category: {category}. Expected AuditCategory, got {type(category).__name__}"
            )

        entry = AuditEntry(
            level=level,
            message=message,
            category=category,
            client_id=client_id,
            account_id=account_id,
        )
        self._entries.append(entry)

        logger.log(_AUDIT_LEVEL_TO_LOGGING[level], "[%s] %s: %s", self.name, category.value, message)
        return entry

    def info(self, message: str, **kwargs) -> AuditEntry:
        return self.log(AuditLogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> AuditEntry:
        return self.log(AuditLogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> AuditEntry:
        return self.log(AuditLogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> AuditEntry:
        return self.log(AuditLogLevel.CRITICAL, message, **kwargs)

    def filter_entries(
            self,
            min_level: AuditLogLevel | None = None,
            category: AuditCategory | None = None,
            client_id: Optional[str] = None,
            account_id: Optional[str] = None,
    ) -> list[AuditEntry]:
        result = self._entries
        if min_level is not None:
            result = [entry for entry in result if entry.level >= min_level]
        if category is not None:
            result = [entry for entry in result if entry.category == category]
        if client_id is not None:
            result = [entry for entry in result if entry.client_id == client_id]
        if account_id is not None:
            result = [entry for entry in result if entry.account_id == account_id]
        return list(result)

    def get_suspicious_entries(self) -> list[AuditEntry]:
        return self.filter_entries(min_level=AuditLogLevel.WARNING, category=AuditCategory.RISK)

    def get_error_statistics(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for entry in self.filter_entries(min_level=AuditLogLevel.ERROR):
            stats[entry.category.value] = stats.get(entry.category.value, 0) + 1
        return stats

    def save_to_file(self, path: str) -> int:
        with open(path, "w", encoding="utf-8") as file:
            file.write(f"# Audit journal '{self.name}' — {len(self._entries)} records\n")
            for entry in self._entries:
                file.write(entry.to_file_line() + "\n")

        logger.info("Audit journal '%s' saved to %s (%s records)", self.name, path, len(self._entries))
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class RiskFactor(Enum):
    LARGE_AMOUNT = "large amount"
    FREQUENT_OPERATIONS = "frequent operations"
    NEW_RECIPIENT = "new recipient"
    NIGHT_OPERATION = "night operation"


@dataclass
class RiskAssessment:
    transaction: Transaction
    risk_level: RiskLevel
    risk_score: int
    factors: list[RiskFactor] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return self.risk_level is not RiskLevel.LOW

    def __str__(self) -> str:
        factors_text = ", ".join(factor.value for factor in self.factors) or "no"
        return (
            f"risk {self.risk_level.name} ({self.risk_score}), "
            f"factors: {factors_text}, operation {self.transaction.transaction_id[-4:]}"
        )


@dataclass
class RiskProfile:
    client_id: str
    client_name: str
    transactions_analyzed: int = 0
    suspicious_transactions: int = 0
    blocked_transactions: int = 0
    max_risk_level: RiskLevel = RiskLevel.LOW
    total_risk_score: int = 0
    factor_counts: dict[RiskFactor, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"Client {self.client_name} ({self.client_id[-4:]}):",
            f"  transactions analyzed: {self.transactions_analyzed}",
            f"  suspicious transactions: {self.suspicious_transactions}, blocked: {self.blocked_transactions}",
            f"  max risk level: {self.max_risk_level.name}",
            f"  total risk score: {self.total_risk_score}",
            f"  risk factors: {self._factors_text()}",
        ]
        return "\n".join(lines)

    def _factors_text(self) -> str:
        if not self.factor_counts:
            return "no"
        return ", ".join(f"{factor.value} ×{count}" for factor, count in self.factor_counts.items())


class RiskAnalyzer:
    LARGE_AMOUNT_THRESHOLD_RUB = Decimal("500000.00")
    FREQUENCY_THRESHOLD = 2
    FREQUENCY_WINDOW_SECONDS = 1
    MEDIUM_RISK_SCORE_THRESHOLD = 2
    HIGH_RISK_SCORE_THRESHOLD = 4

    FACTOR_WEIGHTS: dict[RiskFactor, int] = {
        RiskFactor.LARGE_AMOUNT: 3,
        RiskFactor.FREQUENT_OPERATIONS: 2,
        RiskFactor.NEW_RECIPIENT: 2,
        RiskFactor.NIGHT_OPERATION: 2,
    }

    def __init__(
            self,
            audit_log: AuditLog,
            exchange_rates: Optional[dict[Currency, Decimal]] = None
    ) -> None:
        self.audit_log = audit_log
        self._exchange_rates = exchange_rates or DEFAULT_EXCHANGE_RATES
        self._transactions_by_client: dict[str, list[Transaction]] = {}
        self._known_recipient_account_ids: set[str] = set()
        self._assessments_by_client: dict[str, list[RiskAssessment]] = {}

    def assess_transaction(self, transaction: Transaction) -> RiskAssessment:
        client_id = transaction.sender.client.client_id
        factors = self._collect_risk_factors(transaction, client_id)
        score = sum(self.FACTOR_WEIGHTS[factor] for factor in factors)
        return RiskAssessment(
            transaction=transaction,
            risk_level=self._score_to_level(score),
            risk_score=score,
            factors=factors,
        )

    def check_transaction(self, transaction: Transaction) -> RiskAssessment:
        assessment = self.assess_transaction(transaction)
        self._record(transaction, assessment)
        self._publish_audit_event(transaction, assessment)

        if assessment.risk_level is RiskLevel.HIGH:
            self._block_transaction(transaction, assessment)

        return assessment

    # ---- risk profile reports -----------------------------------------------------------

    def get_risk_profile(self, client_id: str) -> Optional[RiskProfile]:
        assessments = self._assessments_by_client.get(client_id)
        if not assessments:
            return None

        profile = RiskProfile(
            client_id=client_id,
            client_name=assessments[0].transaction.sender.client.name,
            transactions_analyzed=len(assessments),
        )

        for assessment in assessments:
            profile.total_risk_score += assessment.risk_score

            if assessment.risk_level is RiskLevel.HIGH:
                profile.blocked_transactions += 1
            if assessment.is_suspicious:
                profile.suspicious_transactions += 1
            if assessment.risk_level > profile.max_risk_level:
                profile.max_risk_level = assessment.risk_level

            for factor in assessment.factors:
                profile.factor_counts[factor] = profile.factor_counts.get(factor, 0) + 1

        return profile

    def get_all_risk_profiles(self) -> list[RiskProfile | None]:
        return [self.get_risk_profile(client_id) for client_id in self._assessments_by_client]

    # ---- helpers ---------------------------------------------------

    def _collect_risk_factors(self, transaction: Transaction, client_id: str) -> list[RiskFactor]:
        factors: list[RiskFactor] = []

        if self._is_large_amount(transaction):
            factors.append(RiskFactor.LARGE_AMOUNT)

        if self._is_frequent(transaction, client_id):
            factors.append(RiskFactor.FREQUENT_OPERATIONS)

        if transaction.recipient.account_id not in self._known_recipient_account_ids:
            factors.append(RiskFactor.NEW_RECIPIENT)

        if CURFEW_START <= transaction.created_at.time() < CURFEW_END:
            factors.append(RiskFactor.NIGHT_OPERATION)

        return factors

    def _is_large_amount(self, transaction: Transaction) -> bool:
        rate = self._exchange_rates.get(transaction.currency)
        if rate is None:
            return False
        return transaction.amount * rate >= self.LARGE_AMOUNT_THRESHOLD_RUB

    def _is_frequent(self, transaction: Transaction, client_id: str) -> bool:
        window_start = transaction.created_at - timedelta(seconds=self.FREQUENCY_WINDOW_SECONDS)
        recent_count = sum(
            1
            for previous in self._transactions_by_client.get(client_id, [])
            if previous.created_at >= window_start
        )
        return recent_count >= self.FREQUENCY_THRESHOLD

    @classmethod
    def _score_to_level(cls, score: int) -> RiskLevel:
        if score >= cls.HIGH_RISK_SCORE_THRESHOLD:
            return RiskLevel.HIGH
        if score >= cls.MEDIUM_RISK_SCORE_THRESHOLD:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _record(self, transaction: Transaction, assessment: RiskAssessment) -> None:
        client_id = transaction.sender.client.client_id
        self._transactions_by_client.setdefault(client_id, []).append(transaction)
        self._known_recipient_account_ids.add(transaction.recipient.account_id)
        self._assessments_by_client.setdefault(client_id, []).append(assessment)

    def _publish_audit_event(self, transaction: Transaction, assessment: RiskAssessment) -> None:
        client_id = transaction.sender.client.client_id
        account_id = transaction.sender.account_id
        message = f"Transaction {transaction.transaction_id[-4:]}: {assessment}"

        if assessment.risk_level is RiskLevel.HIGH:
            self.audit_log.critical(
                f"{message} — transaction will be blocked",
                category=AuditCategory.RISK,
                client_id=client_id,
                account_id=account_id,
            )
        elif assessment.risk_level is RiskLevel.MEDIUM:
            self.audit_log.warning(
                f"{message} — suspicious transaction allowed to process (placed under monitoring)",
                category=AuditCategory.RISK,
                client_id=client_id,
                account_id=account_id,
            )
        else:
            self.audit_log.info(
                message,
                category=AuditCategory.RISK,
                client_id=client_id,
                account_id=account_id,
            )

    @staticmethod
    def _block_transaction(transaction: Transaction, assessment: RiskAssessment) -> None:
        reasons = ", ".join(factor.value for factor in assessment.factors)
        message = (
            f"Operation {transaction.transaction_id[-4:]} blocked: "
            f"risk level {assessment.risk_level.name} ({assessment.risk_score}), "
            f"reasons: {reasons}"
        )
        transaction.status = TransactionStatus.FAILED
        transaction.failure_reason = message
        transaction.processed_at = datetime.now()
        raise SuspiciousActivityError(message)


class RiskGuardedTransactionProcessor(TransactionProcessor):
    def __init__(
            self,
            risk_analyzer: RiskAnalyzer,
            exchange_rates: Optional[dict[Currency, Decimal]] = None
    ) -> None:
        super().__init__(exchange_rates)
        self.risk_analyzer = risk_analyzer

    def process_transaction(self, transaction: Transaction) -> None:
        self.risk_analyzer.check_transaction(transaction)

        try:
            super().process_transaction(transaction)
        except BankAccountError as e:
            self._audit_transaction(
                AuditLogLevel.ERROR,
                f"Transaction {transaction.transaction_id[-4:]} aborted: {e}",
                transaction,
            )
            raise

        self._audit_transaction(
            AuditLogLevel.INFO,
            f"Transaction {transaction.transaction_id[-4:]} executed: {transaction}",
            transaction,
        )

    def _audit_transaction(self, level: AuditLogLevel, message: str, transaction: Transaction) -> None:
        self.risk_analyzer.audit_log.log(
            level,
            message,
            category=AuditCategory.TRANSACTION,
            client_id=transaction.sender.client.client_id,
            account_id=transaction.sender.account_id,
        )
