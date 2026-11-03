"""День 7: Система отчётности и визуализации.

ReportBuilder собирает отчёты трёх типов (по клиенту, по банку, по рискам),
экспортирует их в текст, JSON и CSV и строит диаграммы через matplotlib:
- круговая (распределение балансов клиентов);
- столбчатые (статусы и объёмы транзакций);
- график движения баланса клиента по истории транзакций.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # рендеринг строго в файлы, без интерактивного окна
import matplotlib.pyplot as plt

from exceptions import InvalidOperationError
from models import (
    TRANSACTION_HISTORY,
    DEFAULT_EXCHANGE_RATES,
    AccountStatus,
    AuditLogLevel,
    Bank,
    BankAccount,
    Client,
    Currency,
    RiskAnalyzer,
    TransactionHistory,
    TransactionStatus,
)

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


# ---------------------------------------------------------------------------
# Сериализация: JSON не знает Decimal/Enum/datetime — приводим всё к базовым типам
# ---------------------------------------------------------------------------
def _jsonable(value) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k.value if isinstance(k, Enum) else str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


@dataclass
class Report:
    """Готовый отчёт: машинные данные (dict), строки для CSV и красивый текст."""

    report_type: str  # "client" | "bank" | "risk"
    title: str
    generated_at: datetime = field(default_factory=datetime.now)
    data: dict = field(default_factory=dict)
    rows: list[dict[str, str]] = field(default_factory=list)  # плоские однотипные строки для CSV

    def to_dict(self) -> dict:
        """JSON-совместимое представление отчёта."""
        return {
            "report_type": self.report_type,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "data": _jsonable(self.data),
        }

    def to_text(self) -> str:
        lines = [
            "=" * 64,
            self.title,
            f"Сформирован: {self.generated_at:%Y-%m-%d %H:%M:%S}",
            "=" * 64,
        ]
        for key, value in self.data.items():
            _render_value(key, value, lines, indent=1)
        lines.append("=" * 64)
        return "\n".join(lines)


def _render_value(key: str, value: object, lines: list[str], indent: int) -> None:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines.append(f"{prefix}{key}:")
        for sub_key, sub_value in value.items():
            _render_value(sub_key, sub_value, lines, indent + 1)
    elif isinstance(value, (list, tuple)):
        if not value:
            lines.append(f"{prefix}{key}: (пусто)")
        else:
            lines.append(f"{prefix}{key}: {len(value)} шт.")
            for index, item in enumerate(value, 1):
                if isinstance(item, dict):
                    summary = ", ".join(f"{k}: {v}" for k, v in item.items())
                    lines.append(f"{prefix}  {index}. {summary}")
                else:
                    lines.append(f"{prefix}  {index}. {item}")
    else:
        lines.append(f"{prefix}{key}: {value}")


class ReportBuilder:
    DPI = 150

    def __init__(
            self,
            bank: Bank,
            history: TransactionHistory = TRANSACTION_HISTORY,
            analyzer: RiskAnalyzer | None = None,
    ) -> None:
        self._bank = bank
        self._history = history
        self._analyzer = analyzer
        self._rates = DEFAULT_EXCHANGE_RATES

    # ------------------------------------------------------------------
    # Отчёты
    # ------------------------------------------------------------------
    def build_client_report(self, client: Client) -> Report:
        logger.info("Формирование отчёта по клиенту %s", client.name)
        client_transactions = self._history.get_by_client(client.client_id)

        status_counts = {
            status.name: sum(
                1 for tx in client_transactions if tx.status is status
            )
            for status in TransactionStatus
            if any(tx.status is status for tx in client_transactions)
        }

        completed = [
            tx for tx in client_transactions if tx.status is TransactionStatus.COMPLETED
        ]
        outgoing_volume: dict[Currency, Decimal] = {}
        incoming_volume: dict[Currency, Decimal] = {}
        client_account_ids = {account.account_id for account in client.accounts}

        for tx in completed:
            if tx.sender.account_id in client_account_ids:
                outgoing_volume[tx.currency.value] = outgoing_volume.get(tx.currency.value, Decimal("0.00")) + tx.amount
            if tx.recipient.account_id in client_account_ids:
                incoming_volume[tx.currency.value] = incoming_volume.get(tx.currency.value, Decimal("0.00")) + tx.amount

        rejected = {
            tx.transaction_id[-4:]: tx.failure_reason
            for tx in client_transactions
            if tx.status is TransactionStatus.FAILED
        }

        data = {
            "клиент": f"{client.name} (ID …{client.client_id[-4:]})",
            "статус клиента": client.status.value,
            "общий баланс (RUB)": client.get_total_balance(),
            "счета": [self._account_row(account) for account in client.accounts],
            "транзакции клиента": {
                "всего": len(client_transactions),
                "по статусам": status_counts,
                "объём исходящих": outgoing_volume,
                "объём входящих": incoming_volume,
                "отклонённые": rejected or "нет",
            },
        }

        rows = [
            {"клиент": client.name, **{k: str(v) for k, v in self._account_row(account).items()}}
            for account in client.accounts
        ]

        return Report(
            report_type="client",
            title=f"Отчёт по клиенту {client.name}",
            data=data,
            rows=rows,
        )

    def build_bank_report(self) -> Report:
        logger.info("Формирование отчёта по банку %s", self._bank.name)

        accounts_by_type: dict[str, int] = {}
        accounts_by_status: dict[str, int] = {}
        balances_by_currency: dict[Currency, Decimal] = {}
        for account in self._bank.accounts.values():
            type_name = account.__class__.__name__
            accounts_by_type[type_name] = accounts_by_type.get(type_name, 0) + 1
            accounts_by_status[account.status.name] = accounts_by_status.get(account.status.name, 0) + 1
            if account.status is not AccountStatus.CLOSED:
                balances_by_currency[account.currency.value] = (
                        balances_by_currency.get(account.currency.value, Decimal("0.00")) + account.balance
                )

        stats = self._history.get_statistics()
        transaction_stats = {
            "всего": stats["total"],
            "исполнено": stats["by_status"].get(TransactionStatus.COMPLETED.value, 0),
            "отклонено (FAILED/CANCELLED)": stats["rejected"],
            "доля успешных, %": stats["success_rate"],
            "объём исполненных по валютам": stats["completed_volume_by_currency"],
            "комиссии по валютам": stats["fees_by_currency"],
        }

        ranking = self._bank.get_clients_ranking()
        top_clients = [
            {"место": str(i), "клиент": client.name, "баланс RUB": total}
            for i, (client, total) in enumerate(ranking, 1)
        ]

        data = {
            "банк": self._bank.name,
            "клиентов": len(self._bank.clients),
            "счетов": len(self._bank.accounts),
            "счета по типам": accounts_by_type,
            "счета по статусам": accounts_by_status,
            "балансы по валютам": balances_by_currency,
            "общий баланс (RUB)": self._bank.get_total_balance(),
            "рейтинг клиентов по балансу": top_clients,
            "статистика транзакций": transaction_stats,
        }

        rows = [
            {
                "клиент": client.name,
                "id": client.client_id,
                "статус": client.status.value,
                "счетов": str(len(client.accounts)),
                "баланс RUB": str(total),
            }
            for client, total in ranking
        ]

        return Report(
            report_type="bank",
            title=f"Отчёт по банку {self._bank.name}",
            data=data,
            rows=rows,
        )

    def build_risk_report(self) -> Report:
        if self._analyzer is None:
            raise InvalidOperationError("Risk report requires a RiskAnalyzer.")

        analyzer = self._analyzer
        logger.info("Формирование отчёта по рискам (аудит: %s)", analyzer.audit_log.name)

        profiles = [p for p in analyzer.get_all_risk_profiles() if p is not None]
        factors_total: dict[str, int] = {}
        for profile in profiles:
            for factor, count in profile.factor_counts.items():
                factors_total[factor.value] = factors_total.get(factor.value, 0) + count

        client_profiles = [
            {
                "клиент": f"{p.client_name} (ID …{p.client_id[-4:]})",
                "проанализировано": p.transactions_analyzed,
                "подозрительных": p.suspicious_transactions,
                "заблокировано": p.blocked_transactions,
                "максимальный уровень риска": p.max_risk_level.name,
                "суммарный балл риска": p.total_risk_score,
                "факторы риска": {f.value: c for f, c in p.factor_counts.items()} or "нет",
            }
            for p in profiles
        ]

        critical_entries = analyzer.audit_log.filter_entries(min_level=AuditLogLevel.CRITICAL)

        data = {
            "проанализировано клиентов": len(profiles),
            "всего проверок": sum(p.transactions_analyzed for p in profiles),
            "подозрительных транзакций": sum(p.suspicious_transactions for p in profiles),
            "заблокировано транзакций (HIGH)": sum(p.blocked_transactions for p in profiles),
            "факторы риска (итого)": factors_total or "нет",
            "критичных записей в аудите": len(critical_entries),
            "профили клиентов": client_profiles,
        }

        rows = [
            {
                "клиент": profile["клиент"],
                "проанализировано": str(profile["проанализировано"]),
                "подозрительных": str(profile["подозрительных"]),
                "заблокировано": str(profile["заблокировано"]),
                "максимальный уровень": profile["максимальный уровень риска"],
                "суммарный балл": str(profile["суммарный балл риска"]),
            }
            for profile in client_profiles
        ]

        return Report(
            report_type="risk",
            title="Отчёт по рискам и подозрительным операциям",
            data=data,
            rows=rows,
        )

    # ------------------------------------------------------------------
    # Экспорт
    # ------------------------------------------------------------------
    @staticmethod
    def export_to_json(report: Report, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("JSON-отчёт сохранён: %s", path)
        return path

    @staticmethod
    def export_to_csv(report: Report, path: str | Path) -> Path:
        if not report.rows:
            raise InvalidOperationError(f"Report {report.report_type} has no rows to export.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # объединяем ключи всех строк, сохраняя порядок первого появления
        fieldnames: list[str] = []
        for row in report.rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report.rows)
        logger.info("CSV-отчёт сохранён: %s", path)
        return path

    @staticmethod
    def export_to_text(report: Report, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_text(), encoding="utf-8")
        logger.info("Текстовый отчёт сохранён: %s", path)
        return path

    # ------------------------------------------------------------------
    # Диаграммы
    # ------------------------------------------------------------------
    def save_charts(self, output_dir: str | Path = REPORTS_DIR, balance_client: Client | None = None) -> dict[str, Path]:
        """Строит и сохраняет все диаграммы дня 7, возвращает пути к PNG-файлам."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths = {
            "балансы клиентов (круговая)": self._chart_balance_pie(output_dir / "client_balance_pie.png"),
            "транзакции по статусам (столбчатая)": self._chart_transactions_by_status(
                output_dir / "transactions_by_status.png"),
            "объём по валютам (столбчатая)": self._chart_volume_by_currency(
                output_dir / "volume_by_currency.png"),
        }

        client = balance_client or next(
            (client for client, _ in self._bank.get_clients_ranking() if client.accounts), None)
        if client is None:
            raise InvalidOperationError("No client with accounts for the balance movement chart.")
        paths["движение баланса"] = self._chart_balance_movement(client, output_dir / "balance_movement.png")

        for name, path in paths.items():
            logger.info("Диаграмма «%s» сохранена: %s", name, path)
        return paths

    def _chart_balance_pie(self, path: Path) -> Path:
        ranking = [(c, b) for c, b in self._bank.get_clients_ranking() if b > 0]
        names = [client.name for client, _ in ranking]
        balances = [float(balance) for _, balance in ranking]

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.pie(balances, labels=names, autopct="%1.1f%%", startangle=90)
        ax.set_title(f"Распределение балансов клиентов — {self._bank.name} (RUB)")
        self._save(fig, path)
        return path

    def _chart_transactions_by_status(self, path: Path) -> Path:
        counts = {
            status.name: sum(1 for tx in self._history if tx.status is status)
            for status in TransactionStatus
        }
        counts = {status: count for status, count in counts.items() if count > 0}

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.bar(counts.keys(), counts.values(), color="steelblue")
        ax.bar_label(ax.containers[0])
        ax.set_title("Количество транзакций по статусам")
        ax.set_ylabel("шт.")
        self._save(fig, path)
        return path

    def _chart_volume_by_currency(self, path: Path) -> Path:
        stats = self._history.get_statistics()
        volumes = stats["completed_volume_by_currency"]
        labels = [currency.value for currency in volumes]
        values = [float(volume) for volume in volumes.values()]

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.bar(labels, values, color="seagreen")
        for label, value in zip(labels, values):
            ax.annotate(f"{value:,.0f}", (label, value), ha="center", va="bottom")
        ax.set_title("Исполненный объём транзакций по валютам")
        ax.set_ylabel("сумма")
        self._save(fig, path)
        return path

    def _chart_balance_movement(self, client: Client, path: Path) -> Path:
        """Восстанавливает движение баланса клиента по истории исполненных транзакций.

        Отправитель платит (amount + fee) в валюте отправителя, получатель получает
        amount в валюте получателя (с конвертацией, если валюты различаются) —
        ровно так же, как это делает TransactionProcessor.
        """
        account_ids = {account.account_id for account in client.accounts}

        events: list[tuple[datetime, Currency, Decimal]] = []
        for tx in self._history:
            if tx.status is not TransactionStatus.COMPLETED:
                continue
            happened_at = tx.processed_at or tx.created_at
            if tx.sender.account_id in account_ids:
                events.append((happened_at, tx.sender.currency, -(tx.amount + tx.fee)))
            if tx.recipient.account_id in account_ids:
                received = self._convert(tx.amount, tx.sender.currency, tx.recipient.currency)
                events.append((happened_at, tx.recipient.currency, +received))

        by_currency: dict[Currency, list[tuple[datetime, Decimal]]] = {}
        for happened_at, currency, delta in events:
            by_currency.setdefault(currency, []).append((happened_at, delta))

        if not by_currency:
            raise InvalidOperationError(f"Client {client.name} has no completed transactions.")

        currencies = sorted(by_currency, key=lambda cur: cur.value)
        curves = {currency: self._cumulative(by_currency[currency]) for currency in currencies}

        fig, axes = plt.subplots(len(currencies), 1, figsize=(10, 4 * len(currencies)),
                                 sharex=True, squeeze=False)
        for ax, currency in zip(axes[:, 0], currencies):
            times, cumulative = curves[currency]
            net_change = cumulative[-1]
            # восстанавливаем абсолютный баланс: текущий баланс минус суммарное движение
            current_balance = sum(
                (a.balance for a in client.accounts if a.currency is currency), Decimal("0.00"))
            initial_balance = current_balance - net_change
            values = [initial_balance + value for value in cumulative]

            ax.plot(times, values, marker="o", markersize=4, drawstyle="steps-post",
                    color=f"C{currencies.index(currency)}")
            ax.axhline(float(initial_balance), color="grey", linewidth=0.5, linestyle="--")
            ax.annotate(f"начальный баланс: {initial_balance:,.2f}",
                        (times[0], values[0]), textcoords="offset points",
                        xytext=(8, 10), fontsize=8, color="dimgray")
            ax.set_ylabel(f"баланс, {currency.value}")
            ax.set_title(f"{client.name} ({currency.value}): "
                         f"начало {initial_balance:,.2f} → текущий {current_balance:,.2f}, "
                         f"чистое движение {net_change:+,.2f}", fontsize=9)
        ax.set_xlabel("время обработки транзакций")
        fig.autofmt_xdate()
        fig.suptitle(f"График движения баланса — {client.name}", y=0.995)
        fig.tight_layout()
        self._save(fig, path)
        return path

    def _cumulative(self, event_list: list[tuple[datetime, Decimal]]) -> tuple[list[datetime], list[Decimal]]:
        event_list = sorted(event_list, key=lambda item: item[0])
        times = [moment for moment, _ in event_list]
        values: list[Decimal] = []
        total = Decimal("0.00")
        for _, delta in event_list:
            total += delta
            values.append(total)
        return times, values

    def _convert(self, amount: Decimal, from_currency: Currency, to_currency: Currency) -> Decimal:
        if from_currency is to_currency:
            return amount
        amount_in_base = amount * self._rates[from_currency]
        return (amount_in_base / self._rates[to_currency]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # helpers -----------------------------------------------------------
    @staticmethod
    def _account_row(account: BankAccount) -> dict[str, object]:
        return {
            "счёт": f"…{account.account_id[-4:]}",
            "тип": account.__class__.__name__,
            "валюта": account.currency.value,
            "баланс": account.balance,
            "статус": account.status.value,
        }

    @classmethod
    def _save(cls, fig: "plt.Figure", path: Path) -> None:
        fig.savefig(path, dpi=cls.DPI, bbox_inches="tight")
        plt.close(fig)
        logger.info("График сохранён: %s", path)
