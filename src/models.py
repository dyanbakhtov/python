import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from utils import generate_short_uuid

logger = logging.getLogger(__name__)


@dataclass
class Client:
    name: str
    client_id: str = field(default_factory=generate_short_uuid)

    def __str__(self) -> str:
        return f"{self.client_id[-4:]} {self.name}"


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
            account_status: AccountStatus
    ) -> None:
        if not isinstance(client, Client):
            raise InvalidOperationError(f"Invalid client: {client}. Expected Client, got {type(client).__name__}")
        if not isinstance(account_status, AccountStatus):
            raise InvalidOperationError(f"Invalid account status: {account_status}. Expected AccountStatus enum, got {type(account_status).__name__}")

        self.account_id = account_id
        self.client = client
        self._balance = balance
        self.account_status = account_status

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
        if self.account_status == AccountStatus.FROZEN:
            raise AccountFrozenError("Operation prohibited: account is frozen")
        if self.account_status == AccountStatus.CLOSED:
            raise AccountClosedError("Operation prohibited: account is closed")
        if self.account_status != AccountStatus.ACTIVE:
            raise InvalidOperationError(f"Operation prohibited: account status is {self.account_status.name}")

    @staticmethod
    def _validate_money_amount(amount: Decimal, param_name: str = "Amount", allow_zero: bool = False) -> None:
        if not isinstance(amount, Decimal):
            raise InvalidOperationError(f"{param_name} must be a Decimal, got {type(amount).__name__}")
        if not amount.is_finite():
            raise InvalidOperationError(f"{param_name} must be finite number, got {amount}")

        if allow_zero:
            if amount < Decimal(0):
                raise InvalidOperationError(f"{param_name} cannot be negative, got {amount}")
        else:
            if amount <= Decimal(0):
                raise InvalidOperationError(f"{param_name} must be positive, got {amount}")


class Currency(Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


class BankAccount(AbstractAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            account_status: AccountStatus,
            account_id: Optional[str] = None
    ) -> None:
        if not isinstance(currency, Currency):
            raise InvalidOperationError(f"Invalid currency: {currency}. Expected Currency enum, got {type(currency).__name__}")

        self._validate_money_amount(balance, param_name="Initial balance", allow_zero=True)
        actual_id = account_id if account_id is not None else generate_short_uuid()
        self.currency = currency
        super().__init__(actual_id, client, balance, account_status)

        logger.info("Account created. %s", self)

    def deposit(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Deposit amount")
        self._balance += amount
        logger.info(
            "Deposit successful: Account=%s, Amount=+%s %s, New Balance=%s %s",
            self.account_id, amount, self.currency.value, self._balance, self.currency.value
        )

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Withdrawal amount")

        if self._balance < amount:
            raise InsufficientFundsError(
                f"Operation prohibited: insufficient balance {self._balance} {self.currency.value}")

        self._balance -= amount
        logger.info(
            "Withdrawal successful: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id, amount, self.currency.value, self._balance, self.currency.value
        )

    def get_account_info(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return (
            f"Type: {self.__class__.__name__} | Client: {self.client} | Account Number: {self.account_id[-4:]} | "
            f"Status: {self.account_status.name} | Balance: {self._balance} {self.currency.value}"
        )

class SavingsAccount(BankAccount):
    def __init__(
            self,
            client: Client,
            balance: Decimal,
            currency: Currency,
            account_status: AccountStatus,
            min_balance: Decimal,
            monthly_rate: Decimal,
            account_id: Optional[str] = None
    ) -> None:
        self._validate_money_amount(min_balance, param_name="Min Balance", allow_zero=True)
        if balance < min_balance:
            raise InsufficientFundsError(f"Balance cannot be less than min balance: "
                                         f"balance= {self._balance} {self.currency.value}, "
                                         f"min_balance= {min_balance} {self.currency.value}")

        if not isinstance(monthly_rate, Decimal) or monthly_rate <= Decimal(0) or monthly_rate > Decimal(100):
            raise InvalidOperationError("Invalid monthly rate, must be between 0 and 100")

        self.min_balance = min_balance
        self.monthly_rate = monthly_rate

        super().__init__(client, balance, currency, account_status, account_id)

    def withdraw(self, amount: Decimal) -> None:
        if (self._balance - amount) < self.min_balance:
            raise InsufficientFundsError(f"Operation prohibited: remaining balance would drop below min balance "
                                         f"({self.min_balance} {self.currency.value})")
        super().withdraw(amount)

    def apply_monthly_interest(self) -> None:
        self._validate_status()
        interest_amount = self._balance * (self.monthly_rate / Decimal(100))
        self._balance += interest_amount
        logger.info("Monthly interest applied: Account=%s, Added=%s %s, New Balance =%s %s",
            self.account_id, interest_amount, self.currency.value, self._balance, self.currency.value)

    def __str__(self) -> str:
        return super().__str__() + f" | Min Balance: {self.min_balance} | Monthly Rate: {self.monthly_rate} %"
