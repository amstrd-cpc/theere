from __future__ import annotations

from dataclasses import dataclass

from adapters.config.env_settings_provider import EnvSettingsProvider
from adapters.integrations.discogs.gateway import DiscogsServiceGateway
from adapters.integrations.woo.gateway import WooServiceGateway
from adapters.notifier.stdout_notifier import StdoutNotifier
from adapters.persistence.sqlite.repos import SqliteInventoryRepo, SqliteOrdersRepo, SqliteSalesRepo


@dataclass
class AppContainer:
    inventory_repo: SqliteInventoryRepo
    orders_repo: SqliteOrdersRepo
    sales_repo: SqliteSalesRepo
    settings_provider: EnvSettingsProvider
    woo_gateway: WooServiceGateway
    discogs_gateway: DiscogsServiceGateway
    notifier: StdoutNotifier


def build_container() -> AppContainer:
    return AppContainer(
        inventory_repo=SqliteInventoryRepo(),
        orders_repo=SqliteOrdersRepo(),
        sales_repo=SqliteSalesRepo(),
        settings_provider=EnvSettingsProvider(),
        woo_gateway=WooServiceGateway(),
        discogs_gateway=DiscogsServiceGateway(),
        notifier=StdoutNotifier(),
    )
