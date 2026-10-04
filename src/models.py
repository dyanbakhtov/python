import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from enum import auto
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
    ACTIVE = auto()
    FROZEN = auto()
    CLOSED = auto()


class AbstractAccount(ABC):
    def __init__(
            self,
            account_id: str,
            client: Client,
            balance: Decimal,
            account_status: AccountStatus
    ) -> None:
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
            account_status: AccountStatus,
            currency: Currency,
            account_id: Optional[str] = None
    ) -> None:
        actual_id = account_id if account_id is not None else generate_short_uuid()

        if balance < 0:
            raise InvalidOperationError("Initial balance cannot be negative")

        super().__init__(actual_id, client, balance, account_status)
        self.currency = currency

        logger.info("Account created. %s", self)

    def _validate_status(self) -> None:
        if self.account_status == AccountStatus.FROZEN:
            raise AccountFrozenError("Operation prohibited: account is frozen")
        if self.account_status == AccountStatus.CLOSED:
            raise AccountClosedError("Operation prohibited: account is closed")
        if self.account_status != AccountStatus.ACTIVE:
            raise InvalidOperationError(f"Operation prohibited: account status is {self.account_status.name}")

    def deposit(self, amount: Decimal) -> None:
        self._validate_status()
        if amount <= 0:
            raise InvalidOperationError("Operation prohibited: amount must be positive")
        self._balance += amount
        logger.info(
            "Deposit successful: Account=%s, Amount=+%s %s, New Balance=%s %s",
            self.account_id, amount, self.currency.value, self._balance, self.currency.value
        )

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        if amount <= 0:
            raise InvalidOperationError("Operation prohibited: amount must be positive")
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
