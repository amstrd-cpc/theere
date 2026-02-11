from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

ROOT_MENU_ID = "main"
SHOP_MENU_ID = "shop"
INTEGRATIONS_MENU_ID = "integrations"
SETTINGS_MENU_ID = "settings"


@dataclass(frozen=True)
class MenuDefinition:
    menu_id: str
    parent_id: Optional[str]
    command_target: Optional[str] = None


MENU_REGISTRY: Dict[str, MenuDefinition] = {
    ROOT_MENU_ID: MenuDefinition(menu_id=ROOT_MENU_ID, parent_id=None),
    SHOP_MENU_ID: MenuDefinition(menu_id=SHOP_MENU_ID, parent_id=ROOT_MENU_ID),
    INTEGRATIONS_MENU_ID: MenuDefinition(
        menu_id=INTEGRATIONS_MENU_ID,
        parent_id=ROOT_MENU_ID,
    ),
    SETTINGS_MENU_ID: MenuDefinition(menu_id=SETTINGS_MENU_ID, parent_id=ROOT_MENU_ID, command_target="/settings"),
    "add": MenuDefinition(menu_id="add", parent_id=SHOP_MENU_ID, command_target="/add"),
    "sell": MenuDefinition(menu_id="sell", parent_id=SHOP_MENU_ID, command_target="/sell"),
    "inventory": MenuDefinition(menu_id="inventory", parent_id=SHOP_MENU_ID, command_target="/inventory"),
    "reports": MenuDefinition(menu_id="reports", parent_id=SHOP_MENU_ID, command_target="/reports"),
    "integrations_woo": MenuDefinition(
        menu_id="integrations_woo",
        parent_id=INTEGRATIONS_MENU_ID,
        command_target="/integrations_woo",
    ),
    "integrations_discogs": MenuDefinition(
        menu_id="integrations_discogs",
        parent_id=INTEGRATIONS_MENU_ID,
        command_target="/integrations_discogs",
    ),
}


def get_menu_definition(menu_id: str) -> Optional[MenuDefinition]:
    return MENU_REGISTRY.get(menu_id)


def get_children(menu_id: str) -> Tuple[MenuDefinition, ...]:
    return tuple(defn for defn in MENU_REGISTRY.values() if defn.parent_id == menu_id)
