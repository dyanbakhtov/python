class BankAccountError(Exception):
    pass


class AccountFrozenError(BankAccountError):
    pass


class AccountClosedError(BankAccountError):
    pass


class InsufficientFundsError(BankAccountError):
    pass


class InvalidOperationError(BankAccountError):
    pass
