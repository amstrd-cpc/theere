# Command Catalog

Inventory of every `CommandHandler(...)` declaration in `bot.py` and `telegram_ui/*`.

- Total command declarations: **51**
- Unique command names: **44**

## Registered commands

| Command | Callback | Declaration(s) |
|---|---|---|
| `/add` | `start_add` | `telegram_ui/add.py:715` |
| `/auto_map_woo` | `auto_map_woo` | `telegram_ui/product_mapping.py:212` |
| `/backups` | `backups_status` | `telegram_ui/integrations.py:334` |
| `/cancel` | `cancel_add, cancel_discogs, cancel_inventory_search, cancel_login, cancel_map, cancel_sale, cancel_setup` | `telegram_ui/add.py:741`<br>`telegram_ui/auth.py:143`<br>`telegram_ui/discogs.py:1032`<br>`telegram_ui/discogs.py:1067`<br>`telegram_ui/inventory.py:326`<br>`telegram_ui/product_mapping.py:205`<br>`telegram_ui/sales.py:177`<br>`telegram_ui/woo_setup.py:154` |
| `/collect_discogs` | `collect_discogs` | `telegram_ui/discogs.py:1041` |
| `/collect_discogs_selection` | `collect_discogs_selection` | `telegram_ui/discogs.py:1042` |
| `/connect` | `start_setup` | `telegram_ui/woo_setup.py:147` |
| `/connect_discogs` | `connect_discogs` | `telegram_ui/discogs.py:1028` |
| `/daily` | `daily_report` | `bot.py:165` |
| `/discogs_refresh` | `discogs_refresh` | `telegram_ui/discogs.py:1051` |
| `/discogs_status` | `discogs_status` | `telegram_ui/discogs.py:1073` |
| `/help` | `help_command` | `bot.py:161` |
| `/integrations_discogs` | `integrations_discogs` | `telegram_ui/integrations.py:332` |
| `/integrations_woo` | `integrations_woo` | `telegram_ui/integrations.py:331` |
| `/inventory` | `start_inventory` | `telegram_ui/inventory.py:320` |
| `/link_discogs` | `link_discogs` | `telegram_ui/discogs.py:1043` |
| `/login` | `start_login` | `telegram_ui/auth.py:139` |
| `/logout` | `logout_user` | `telegram_ui/auth.py:150` |
| `/map_woo` | `map_woo` | `telegram_ui/product_mapping.py:198` |
| `/monthly` | `monthly_report` | `bot.py:167` |
| `/orders` | `list_orders` | `telegram_ui/orders.py:119` |
| `/publish_discogs` | `publish_discogs` | `telegram_ui/discogs.py:1038` |
| `/publish_discogs_all` | `publish_discogs_all` | `telegram_ui/discogs.py:1039` |
| `/publish_discogs_selection` | `publish_discogs_selection` | `telegram_ui/discogs.py:1040` |
| `/reconcile_discogs` | `reconcile_discogs` | `telegram_ui/discogs.py:1049` |
| `/reconcile_woo` | `reconcile_woo` | `telegram_ui/discogs.py:1050` |
| `/relist_discogs` | `relist_discogs` | `telegram_ui/discogs.py:1047` |
| `/remove_discogs_listing` | `remove_discogs_listing` | `telegram_ui/discogs.py:1048` |
| `/repair_webhooks` | `repair_webhooks` | `telegram_ui/woo_setup.py:161` |
| `/reports` | `reports_command` | `telegram_ui/reports.py:74` |
| `/sales` | `recent_sales` | `bot.py:164` |
| `/sell` | `sell_flow_start` | `telegram_ui/sales.py:169` |
| `/settings` | `settings_command` | `telegram_ui/store_settings.py:133` |
| `/setup_woo` | `start_setup` | `telegram_ui/woo_setup.py:147` |
| `/start` | `start` | `bot.py:160` |
| `/status` | `show_status` | `telegram_ui/auth.py:151` |
| `/stock` | `low_stock` | `bot.py:168` |
| `/sync_discogs_all` | `sync_discogs_all` | `telegram_ui/discogs.py:1052` |
| `/sync_status` | `sync_status` | `telegram_ui/integrations.py:333` |
| `/unlink_discogs` | `unlink_discogs` | `telegram_ui/discogs.py:1044` |
| `/unlist_discogs` | `unlist_discogs` | `telegram_ui/discogs.py:1046` |
| `/update_discogs_listing` | `update_discogs_listing` | `telegram_ui/discogs.py:1045` |
| `/users` | `admin_users` | `telegram_ui/auth.py:152` |
| `/weekly` | `weekly_report` | `bot.py:166` |

## Alias groups

| Callback | Commands (aliases) |
|---|---|
| `start_setup` | `/connect`, `/setup_woo` |

## Raw declarations

| File | Line | Commands argument | Callback |
|---|---:|---|---|
| `bot.py` | 160 | `/start` | `start` |
| `bot.py` | 161 | `/help` | `help_command` |
| `bot.py` | 164 | `/sales` | `recent_sales` |
| `bot.py` | 165 | `/daily` | `daily_report` |
| `bot.py` | 166 | `/weekly` | `weekly_report` |
| `bot.py` | 167 | `/monthly` | `monthly_report` |
| `bot.py` | 168 | `/stock` | `low_stock` |
| `telegram_ui/add.py` | 715 | `/add` | `start_add` |
| `telegram_ui/add.py` | 741 | `/cancel` | `cancel_add` |
| `telegram_ui/auth.py` | 139 | `/login` | `start_login` |
| `telegram_ui/auth.py` | 143 | `/cancel` | `cancel_login` |
| `telegram_ui/auth.py` | 150 | `/logout` | `logout_user` |
| `telegram_ui/auth.py` | 151 | `/status` | `show_status` |
| `telegram_ui/auth.py` | 152 | `/users` | `admin_users` |
| `telegram_ui/discogs.py` | 1028 | `/connect_discogs` | `connect_discogs` |
| `telegram_ui/discogs.py` | 1032 | `/cancel` | `cancel_discogs` |
| `telegram_ui/discogs.py` | 1038 | `/publish_discogs` | `publish_discogs` |
| `telegram_ui/discogs.py` | 1039 | `/publish_discogs_all` | `publish_discogs_all` |
| `telegram_ui/discogs.py` | 1040 | `/publish_discogs_selection` | `publish_discogs_selection` |
| `telegram_ui/discogs.py` | 1041 | `/collect_discogs` | `collect_discogs` |
| `telegram_ui/discogs.py` | 1042 | `/collect_discogs_selection` | `collect_discogs_selection` |
| `telegram_ui/discogs.py` | 1043 | `/link_discogs` | `link_discogs` |
| `telegram_ui/discogs.py` | 1044 | `/unlink_discogs` | `unlink_discogs` |
| `telegram_ui/discogs.py` | 1045 | `/update_discogs_listing` | `update_discogs_listing` |
| `telegram_ui/discogs.py` | 1046 | `/unlist_discogs` | `unlist_discogs` |
| `telegram_ui/discogs.py` | 1047 | `/relist_discogs` | `relist_discogs` |
| `telegram_ui/discogs.py` | 1048 | `/remove_discogs_listing` | `remove_discogs_listing` |
| `telegram_ui/discogs.py` | 1049 | `/reconcile_discogs` | `reconcile_discogs` |
| `telegram_ui/discogs.py` | 1050 | `/reconcile_woo` | `reconcile_woo` |
| `telegram_ui/discogs.py` | 1051 | `/discogs_refresh` | `discogs_refresh` |
| `telegram_ui/discogs.py` | 1052 | `/sync_discogs_all` | `sync_discogs_all` |
| `telegram_ui/discogs.py` | 1067 | `/cancel` | `cancel_discogs` |
| `telegram_ui/discogs.py` | 1073 | `/discogs_status` | `discogs_status` |
| `telegram_ui/integrations.py` | 331 | `/integrations_woo` | `integrations_woo` |
| `telegram_ui/integrations.py` | 332 | `/integrations_discogs` | `integrations_discogs` |
| `telegram_ui/integrations.py` | 333 | `/sync_status` | `sync_status` |
| `telegram_ui/integrations.py` | 334 | `/backups` | `backups_status` |
| `telegram_ui/inventory.py` | 320 | `/inventory` | `start_inventory` |
| `telegram_ui/inventory.py` | 326 | `/cancel` | `cancel_inventory_search` |
| `telegram_ui/orders.py` | 119 | `/orders` | `list_orders` |
| `telegram_ui/product_mapping.py` | 198 | `/map_woo` | `map_woo` |
| `telegram_ui/product_mapping.py` | 205 | `/cancel` | `cancel_map` |
| `telegram_ui/product_mapping.py` | 212 | `/auto_map_woo` | `auto_map_woo` |
| `telegram_ui/reports.py` | 74 | `/reports` | `reports_command` |
| `telegram_ui/sales.py` | 169 | `/sell` | `sell_flow_start` |
| `telegram_ui/sales.py` | 177 | `/cancel` | `cancel_sale` |
| `telegram_ui/store_settings.py` | 133 | `/settings` | `settings_command` |
| `telegram_ui/woo_setup.py` | 147 | `/setup_woo` | `start_setup` |
| `telegram_ui/woo_setup.py` | 147 | `/connect` | `start_setup` |
| `telegram_ui/woo_setup.py` | 154 | `/cancel` | `cancel_setup` |
| `telegram_ui/woo_setup.py` | 161 | `/repair_webhooks` | `repair_webhooks` |
