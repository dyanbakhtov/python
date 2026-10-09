from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from enum import Enum
from typing import Optional, Dict

from dateutil.relativedelta import relativedelta

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from utils import generate_short_uuid

logger = logging.getLogger(__name__)


class ClientStatus(Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


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

    def deposit(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Deposit amount")
        self._balance += amount
        logger.info(
            "Deposit successful: Account=%s, Amount=+%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
        )

    def withdraw(self, amount: Decimal) -> None:
        self._validate_status()
        self._validate_money_amount(amount, param_name="Withdrawal amount")

        if self.balance < amount:
            raise InsufficientFundsError(
                f"Withdraw failed: insufficient balance {self.balance} {self.currency.value}")

        self._balance -= amount
        logger.info(
            "Withdrawal successful: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
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

    def authenticate_client(self, client_id: str, password: str) -> bool:
        client = self._get_client(client_id)

        if client.status == ClientStatus.BLOCKED:
            raise InvalidOperationError(f"Client {client_id} is blocked.")

        if password == client.password:
            client.reset_login_attempts()
            return True

        client.fail_login()
        if client.login_attempts >= 3:
            client.status = ClientStatus.BLOCKED
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

        if (self.balance - amount) < self.min_balance:
            raise InsufficientFundsError(f"Withdraw failed: remaining balance would drop below min balance "
                                         f"({self.min_balance} {self.currency.value})")

        self._balance -= amount
        logger.info(
            "Withdrawal successful: Account=%s, Amount=-%s %s, New Balance=%s %s",
            self.account_id[-4:], amount, self.currency.value, self.balance, self.currency.value
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

    def __str__(self) -> str:
        return super().__str__() + (f" | Overdraft Limit: {self.overdraft_limit} {self.currency.value}"
                                    f" | Fixed Fee: {self.fixed_fee} {self.currency.value}")


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

    def buy_asset(self, asset_type: str | AssetType, amount: Decimal) -> None:
        self._validate_status()
        asset = AssetType.normalize(asset_type)
        self._validate_money_amount(amount, param_name="Amount")

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
