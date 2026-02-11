# Message Freeze

Inventory of user-facing text from `telegram_ui/messages.py` and inline string literals emitted by command handlers.

## 1) Canonical message constants (`telegram_ui/messages.py`)

| Constant | Line | Text |
|---|---:|---|
| `START_MESSAGE` | 3 | `🎵 *Welcome to the Record Store Bot\!* 🎵\n\nHello {first_name}\!\n\n🔒 *This bot is password protected\.*\nYou must authenticate before using any commands\.\n\nTap a button below to get started\.\n\n*Commands:*\n• /login \- Enter password to authenticate\n• /help \- Show this help message\n\nAfter authentication, you'll have access to:\n• /add \- Add new records to inventory\n• /sell \- Process record sales\n• /inventory \- Search and view inventory\n• /reports \- Generate sales reports\n• /status \- Check authentication status\n• /logout \- Sign out\n\n🔐 *Use /login to get started\!*` |
| `MAIN_MENU_PROMPT` | 22 | `Choose a section below:` |
| `SHOP_MENU_PROMPT` | 23 | `🛍️ Shop menu: pick an action.` |
| `SHOP_INVENTORY_MENU_PROMPT` | 24 | `📦 Inventory actions: pick an option.` |
| `SHOP_SALES_MENU_PROMPT` | 25 | `💸 Sales actions: pick an option.` |
| `SHOP_REPORTS_MENU_PROMPT` | 26 | `📈 Reports & summaries: pick an option.` |
| `INTEGRATIONS_MENU_PROMPT` | 27 | `🔌 Integrations: pick WooCommerce or Discogs.` |
| `DISCOGS_MENU_PROMPT` | 28 | `💿 Discogs menu: pick an action.` |
| `SETTINGS_MENU_PROMPT` | 29 | `⚙️ Settings menu: pick an action.` |
| `SETTINGS_ACCOUNT_MENU_PROMPT` | 30 | `👤 Account settings: pick an option.` |
| `SETTINGS_SUPPORT_MENU_PROMPT` | 31 | `🆘 Support & help: pick an option.` |
| `HELP_AUTHENTICATED` | 33 | `🎵 *Record Store Bot \- Commands* 🎵\n\nTap any button below to run a command instantly\.\n\n*Inventory Management:*\n• /add \- Add new records from Discogs\n• /inventory \- Interactive inventory search\n• /stock \- View low stock items\n\n*WooCommerce:*\n• /setup\_woo \- Connect a store\n• /connect \- Setup Woo \(shortcut\)\n• /repair\_webhooks \- Repair Woo webhooks\n• /integrations\_woo \- WooCommerce sync settings\n• /orders \- Recent Woo orders\n• /map\_woo \- Map Woo product to inventory\n\n• /auto\_map\_woo \- Auto map Woo products\n• /sync\_status \- Sync status summary\n• /backups \- Backup status\n*Discogs:*\n• /connect\_discogs \- Connect Discogs token\n• /discogs\_status \- Show Discogs status\n• /integrations\_discogs \- Discogs sync settings\n• /collect\_discogs \- Add release to collection\n• /collect\_discogs\_selection \- Add selection to collection\n• /link\_discogs \- Link listing to inventory\n• /unlink\_discogs \- Unlink Discogs listing\n• /update\_discogs\_listing \- Update Discogs listing fields\n• /unlist\_discogs \- Unlist Discogs listing\n• /relist\_discogs \- Relist Discogs listing\n• /remove\_discogs\_listing \- Delete Discogs listing\n• /discogs\_refresh \- Check listing quantity\n• /sync\_discogs\_all \- Sync all inventory to Discogs\n*Sales:*\n• /sell \- Process a sale\n• /sales \- View recent sales\n\n*Reports:*\n• /reports \- Generate sales reports\n• /daily \- Today's sales summary\n• /weekly \- Weekly sales report\n• /monthly \- Monthly sales report\n\n*Account:*\n• /status \- Check authentication status\n• /logout \- Sign out\n• /users \- View active users \(admin\)\n\n*General:*\n• /help \- Show this help\n• /start \- Welcome message\n• /cancel \- Cancel current operation` |
| `HELP_UNAUTHENTICATED` | 82 | `🔒 *Authentication Required* 🔒\n\nTap a button below to get started\.\n\n*Available Commands:*\n• /login \- Enter password to authenticate\n• /help \- Show this help\n• /start \- Welcome message\n\n• /cancel \- Cancel current operation\n\n*After authentication, you'll have access to:*\n• Inventory management\n• Sales processing\n• Report generation\n• And much more\!\n\n🔐 *Use /login to get started\!*` |
| `RECENT_SALES_EMPTY` | 98 | `📊 No recent sales found\.` |
| `DAILY_REPORT_EMPTY` | 100 | `📭 No sales recorded for today yet.` |
| `WEEKLY_REPORT_EMPTY` | 101 | `📭 No sales recorded for this week yet.` |
| `MONTHLY_REPORT_EMPTY` | 102 | `📭 No sales recorded for this month yet.` |
| `REPORT_ERROR` | 104 | `❌ Error generating report: {error}` |
| `REPORT_DAILY_ERROR` | 105 | `❌ Error generating daily report: {error}` |
| `REPORT_WEEKLY_ERROR` | 106 | `❌ Error generating weekly report: {error}` |
| `REPORT_MONTHLY_ERROR` | 107 | `❌ Error generating monthly report: {error}` |
| `REPORTS_EMPTY` | 108 | `📭 No sales recorded for today yet.\nStart selling some records to generate a report! 🎵` |
| `AUTH_REQUIRED` | 110 | `🔒 Access Denied!\n\nYou need to authenticate first.\nUse /login to enter the password.` |
| `AUTH_REQUIRED_MARKDOWN` | 116 | `🔒 **Access Denied!**\n\nYou must authenticate first.\nUse /login to enter the password.` |
| `LOGIN_PROMPT` | 122 | `🔐 **Authentication Required**\n\nPlease enter the bot password:` |
| `LOGIN_ALREADY` | 127 | `✅ You are already authenticated!\nSession expires in: {time_left}\n\nUse /logout to sign out or /help to see available commands.` |
| `LOGIN_SUCCESS` | 133 | `✅ **Authentication Successful!**\n\nWelcome, {first_name}!\nSession expires in {hours} hours.\n\nYou can now use all bot commands.\nType /help to see available commands.` |
| `LOGIN_FAILURE` | 141 | `❌ **Incorrect Password!**\n\nAccess denied. Please try again with /login` |
| `LOGOUT_SUCCESS` | 146 | `✅ **Logged Out Successfully**\n\nYou have been signed out of the bot.\nUse /login to authenticate again.` |
| `LOGOUT_ALREADY` | 152 | `ℹ️ You are not currently logged in.\nUse /login to authenticate.` |
| `STATUS_ACTIVE` | 157 | `✅ **Authentication Status: ACTIVE**\n\nSession expires in: {time_left}\nUse /logout to sign out.` |
| `STATUS_INACTIVE` | 163 | `❌ **Authentication Status: NOT AUTHENTICATED**\n\nUse /login to enter the password.` |
| `ADMIN_USERS_EMPTY` | 168 | `No active users.` |
| `ADMIN_USERS_HEADER` | 169 | `👥 **Active Users:**\n\n` |
| `ADMIN_AUTH_REQUIRED` | 170 | `🔒 Authentication required!` |
| `ADMIN_ONLY` | 171 | `🚫 Admin access required for this command.` |
| `CANCEL_LOGIN` | 173 | `🚫 Login cancelled.` |
| `ADD_DISCOGS_MISSING` | 175 | `⚠️ Discogs is not configured. Use /connect_discogs to enable /add.` |
| `ADD_PROMPT_QUERY` | 176 | `Enter album name (Artist - Title):` |
| `ADD_TYPE_PROMPT` | 177 | `What do we add?` |
| `ADD_TYPE_RECORD` | 178 | `Record` |
| `ADD_TYPE_OTHER` | 179 | `Other` |
| `ADD_NEXT_ID_HINT` | 180 | `Next Woo SKU will be: {next_id}` |
| `ADD_NEXT_ID_UNAVAILABLE` | 181 | `Next Woo SKU unavailable (Woo not configured).` |
| `ADD_SELECT_RELEASE` | 182 | `Select a release:` |
| `ADD_SELECT_CONDITION` | 183 | `Selected: {title}\n\nNow choose vinyl condition:` |
| `ADD_SUGGESTED_PRICE` | 184 | `Suggested price for {full_condition}: ${price_usd:.2f} ≈ {price_gel:.2f} GEL` |
| `ADD_NO_SUGGESTION` | 185 | `No price suggestion found.` |
| `ADD_PRICE_PROMPT` | 186 | `\n\nSend your own price in GEL or type 'ok' to accept the suggested price.` |
| `ADD_PRICE_INVALID` | 187 | `❌ Invalid price. Please enter a valid number or 'ok' to accept suggested price:` |
| `ADD_QUANTITY_PROMPT` | 188 | `How many copies do you want to add?` |
| `ADD_QUANTITY_INVALID` | 189 | `❌ Invalid quantity. Enter a whole number ≥ 1:` |
| `ADD_SELECT_SUPPLIER` | 190 | `Select supplier:` |
| `ADD_SUPPLIER_PROMPT` | 191 | `Enter supplier name:` |
| `ADD_SUPPLIER_STALE` | 192 | `⚠️ This supplier button is from an old /add session. Run /add again.` |
| `ADD_SAVED_LOCAL` | 193 | `✅ Saved locally (ID: {inventory_id}). Syncing to Woo…` |
| `ADD_WOO_NOT_CONFIGURED` | 194 | `🛒 Woo not configured: set WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET` |
| `ADD_WOO_FAILED` | 195 | `🛒 Woo sync failed: {error}` |
| `ADD_WOO_OK` | 196 | `🛒 Woo sync OK. Product id: {woo_id}` |
| `ADD_WOO_OK_DETAILS` | 197 | `✅ Added item. Local ID: {inventory_id} \| Woo ID: {woo_id}\nCategories: {categories}` |
| `ADD_SAVE_ERROR` | 198 | `❌ Error saving to inventory: {error}` |
| `ADD_CANCEL` | 199 | `🚫 Add flow cancelled.` |
| `ADD_OTHER_CATEGORY_PROMPT` | 200 | `Enter product category (text):` |
| `ADD_OTHER_NAME_PROMPT` | 201 | `Enter product name:` |
| `ADD_OTHER_PRICE_PROMPT` | 202 | `Enter price (GEL):` |
| `ADD_OTHER_PRICE_INVALID` | 203 | `❌ Invalid price. Please enter a valid number:` |
| `ADD_OTHER_DESCRIPTION_PROMPT` | 204 | `Enter a description for this item:` |
| `ADD_OTHER_PHOTOS_PROMPT` | 205 | `Send 1+ photos of the item. When finished, tap Done.` |
| `ADD_OTHER_PHOTOS_REMINDER` | 206 | `📸 Photo received. Send more or tap Done.` |
| `ADD_OTHER_PHOTOS_REQUIRED` | 207 | `Please send at least one photo before finishing.` |
| `ADD_OTHER_CONFIRM_PROMPT` | 208 | `Ready to add this item? Confirm to save and sync to Woo.` |
| `ADD_OTHER_CONFIRM_TITLE` | 209 | `✅ Confirm` |
| `ADD_OTHER_CANCEL_TITLE` | 210 | `🚫 Cancel` |
| `ADD_OTHER_PHOTOS_DONE` | 211 | `✅ Done` |
| `ADD_OTHER_PHOTOS_CANCEL` | 212 | `🚫 Cancel` |
| `SELL_WELCOME` | 214 | `💰 Welcome to the Sell Vinyls flow!\nPlease enter the artist or album name you want to sell:` |
| `SELL_NOT_FOUND` | 218 | `❌ No matching records found for: <b>{query}</b>` |
| `SELL_SELECT_PROMPT` | 219 | `Please select the record you want to sell:` |
| `SELL_SELECTED` | 220 | `Selected: <b>{artist_album}</b>\nCondition: {condition}\nAvailable: {quantity} copies\nListed price: ₾{price:.2f}\n\nEnter the selling price or type 'ok' to use the listed price:` |
| `SELL_PRICE_NEGATIVE` | 227 | `❌ Price cannot be negative. Please enter a valid price or 'ok':` |
| `SELL_PRICE_INVALID` | 228 | `❌ Invalid price format. Please enter a valid number or 'ok':` |
| `SELL_ADDED` | 229 | `Added {artist_album} - ₾{price:.2f} to cart.\nAdd another item or proceed to checkout?` |
| `SELL_NEXT_PROMPT` | 233 | `Enter the artist or album name of the next record:` |
| `SELL_PAYMENT_PROMPT` | 234 | `Choose payment method:` |
| `SELL_CANCEL` | 235 | `❌ Sale cancelled.` |
| `SELL_CART_EMPTY` | 236 | `Cart is empty.` |
| `SELL_FAILED_ITEM` | 237 | `Failed to sell {artist_album} (out of stock)` |
| `SELL_ERROR_PROCESSING` | 238 | `❌ Error processing sale: {error}` |
| `SELL_PAYMENT_LINE` | 239 | `Payment: {method}` |
| `SELL_TOTAL_LINE` | 240 | `Total: ₾{total:.2f}` |
| `INVENTORY_SEARCH_PROMPT` | 242 | `Enter name to search inventory` |
| `INVENTORY_QUERY_INVALID` | 243 | `❌ Please enter a valid search query or type /cancel to cancel.` |
| `INVENTORY_SEARCHING` | 244 | `🔍 Searching inventory...` |
| `INVENTORY_NO_RESULTS` | 245 | `❌ No records found\n\nSearch query: {query}\n\nTry a different search term or use /inventory to search again.` |
| `INVENTORY_SEARCH_ERROR` | 250 | `❌ Error searching inventory\n\nAn error occurred: {error}\n\nPlease try again with /inventory` |
| `INVENTORY_ALL_TITLE` | 255 | `📦 All Inventory` |
| `INVENTORY_SEARCH_TITLE` | 256 | `🔍 Search Results for: {query}` |
| `INVENTORY_SELECT_PROMPT` | 257 | `Select a record to view details and editing options:` |
| `INVENTORY_FOUND` | 258 | `Found {count} record(s)\n\n` |
| `INVENTORY_SHOWING` | 259 | `📄 Showing 1-8 of {total} results` |
| `INVENTORY_USE_AGAIN` | 260 | `Use /inventory to start a new search.` |
| `INVENTORY_CANCEL` | 261 | `🚫 Inventory search cancelled.` |
| `INVENTORY_PAGE_TITLE` | 262 | `📦 Inventory Page {page}/{total_pages}` |
| `INVENTORY_PAGE_EMPTY` | 263 | `📦 Inventory is empty.` |
| `INVENTORY_EDIT_MENU_PROMPT` | 264 | `Select an action:` |
| `INVENTORY_EDIT_PROMPT_NAME` | 265 | `Enter the new name:` |
| `INVENTORY_EDIT_PROMPT_PRICE` | 266 | `Enter the new price (GEL):` |
| `INVENTORY_EDIT_PROMPT_QUANTITY` | 267 | `Enter the new quantity:` |
| `INVENTORY_EDIT_PROMPT_CONDITION` | 268 | `Enter the new condition:` |
| `INVENTORY_EDIT_PROMPT_GENRE` | 269 | `Enter the new category/genre (or 'none' to clear):` |
| `INVENTORY_EDIT_PROMPT_SUPPLIER` | 270 | `Enter the supplier name (or 'none' to clear):` |
| `INVENTORY_EDIT_SAVED` | 271 | `✅ Updated inventory item.` |
| `INVENTORY_EDIT_INVALID_NUMBER` | 272 | `❌ Please enter a valid non-negative number.` |
| `INVENTORY_EDIT_INVALID_INTEGER` | 273 | `❌ Please enter a valid non-negative whole number.` |
| `INVENTORY_EDIT_NAME_REQUIRED` | 274 | `❌ Name cannot be empty.` |
| `INVENTORY_SYNC_MISSING_WOO` | 275 | `❌ This item is not linked to Woo (missing woo_product_id). Use /add or relink.` |
| `INVENTORY_SYNC_SUCCESS` | 276 | `✅ Synced to Woo.` |
| `INVENTORY_SYNC_NOT_FOUND` | 277 | `❌ Woo product not found for stored woo_product_id.` |
| `INVENTORY_SYNC_ERROR` | 278 | `❌ Woo sync failed: {error}` |
| `STOCK_EMPTY` | 280 | `📦 No low stock items found.` |
| `STOCK_HEADER` | 281 | `📦 Low Stock Items\n\n` |
| `WOO_NOT_CONFIGURED_MESSAGE` | 283 | `🛒 Woo sync is not configured. Set WC_API_URL / WC_CONSUMER_KEY / WC_CONSUMER_SECRET in .env` |
| `WOO_SYNC_NOTE` | 284 | `New items added via /add will sync automatically in the background.` |

## 2) Inline user-facing string literals in command handlers

> Scope: literals passed to Telegram output calls (e.g., `reply_text`, `reply_html`, `send_message`, `answer`) inside functions wired to `CommandHandler(...)`.

### `telegram_ui/discogs.py` → `connect_discogs` (line 211)
- Line 222: `Enter Discogs personal access token:`
- Line 224: `Enter Discogs personal access token:`
- Line 215: `❌ No store configured. Run /setup_woo first.`
- Line 218: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `discogs_status` (line 255)
- Line 258: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `publish_discogs` (line 270)
- Line 277: `Tell me the artist or album name to publish on Discogs:`
- Line 273: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `publish_discogs_all` (line 284)
- Line 291: `Tell me the artist or album name to publish ALL matches on Discogs:`
- Line 287: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `publish_discogs_selection` (line 298)
- Line 305: `Tell me the artist or album name to select items for Discogs publishing:`
- Line 301: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `collect_discogs` (line 312)
- Line 317: `Tell me the artist or album name to add to your Discogs collection:`
- Line 315: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `collect_discogs_selection` (line 324)
- Line 329: `Tell me the artist or album name to select items for Discogs collection:`
- Line 327: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `link_discogs` (line 336)
- Line 341: `Tell me the artist or album name you want to link to a Discogs listing:`
- Line 339: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `update_discogs_listing` (line 348)
- Line 355: `Tell me the artist or album name to update Discogs listing:`
- Line 351: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `unlist_discogs` (line 362)
- Line 369: `Tell me the artist or album name to unlist from Discogs:`
- Line 365: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `relist_discogs` (line 376)
- Line 383: `Tell me the artist or album name to relist on Discogs:`
- Line 379: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `remove_discogs_listing` (line 390)
- Line 397: `Tell me the artist or album name to delete Discogs listing:`
- Line 393: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `unlink_discogs` (line 404)
- Line 409: `Tell me the artist or album name you want to unlink from Discogs:`
- Line 407: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `reconcile_discogs` (line 416)
- Line 426: `✅ Discogs reconciled for  items.`
- Line 419: `❌ No store configured. Run /setup_woo first.`
- Line 422: `I'll reconcile by name instead. Please send the item name:`

### `telegram_ui/discogs.py` → `reconcile_woo` (line 431)
- Line 441: `✅ Woo reconciled for  items.`
- Line 434: `❌ No store configured. Run /setup_woo first.`
- Line 437: `I'll reconcile by name instead. Please send the item name:`

### `telegram_ui/discogs.py` → `discogs_refresh` (line 446)
- Line 451: `Tell me the artist or album name to refresh Discogs quantity:`
- Line 449: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `sync_discogs_all` (line 458)
- Line 463: `How should I sync all inventory to Discogs? WooCommerce stock is treated as the source of truth.`
- Line 461: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/discogs.py` → `cancel_discogs` (line 1019)
- Line 1021: `❌ Discogs action cancelled.`

### `telegram_ui/integrations.py` → `integrations_woo` (line 119)
- Line 122: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/integrations.py` → `integrations_discogs` (line 130)
- Line 133: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/integrations.py` → `sync_status` (line 190)
- Line 193: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/orders.py` → `list_orders` (line 17)
- Line 20: `❌ No store configured. Run /setup_woo first.`
- Line 25: `No recent orders found.`

### `telegram_ui/product_mapping.py` → `map_woo` (line 61)
- Line 66: `Tell me the artist or album name you want to map to WooCommerce:`
- Line 64: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/product_mapping.py` → `cancel_map` (line 166)
- Line 168: `❌ Mapping cancelled.`

### `telegram_ui/product_mapping.py` → `auto_map_woo` (line 174)
- Line 180: `🔎 Auto-mapping WooCommerce products to inventory...`
- Line 187: `✅ Auto-mapping complete.\n🔗 Linked: \n🆕 Created: \n⚠️ Ambiguous: \n⏭️ Skipped: `
- Line 177: `❌ No store configured. Run /setup_woo first.`
- Line 184: `❌ WooCommerce not configured. Run /setup_woo first.`

### `telegram_ui/store_settings.py` → `settings_command` (line 14)
- Line 17: `❌ No store configured. Run /setup_woo first.`

### `telegram_ui/woo_setup.py` → `start_setup` (line 24)
- Line 25: `Enter store name (e.g., My Record Store):`

### `telegram_ui/woo_setup.py` → `cancel_setup` (line 100)
- Line 101: `🚫 Setup cancelled.`

### `telegram_ui/woo_setup.py` → `repair_webhooks` (line 107)
- Line 110: `❌ No store configured. Run /setup_woo first.`
- Line 123: `⚠️ API_BASE_URL missing. Set it before creating webhooks.`
- Line 140: `✅ Webhooks repaired.`
- Line 142: `✅ Webhooks healthy. No changes needed.`

## Review checklist (Behavior Compatibility Contract gate)

- [ ] **Command immutability:** PR does not rename, remove, or repurpose any existing command listed in `docs/COMMAND_CATALOG.md`.
- [ ] **Alias immutability:** PR preserves existing alias command paths.
- [ ] **Message freeze:** Existing `telegram_ui/messages.py` strings remain byte-equivalent unless explicitly versioned.
- [ ] **Inline handler freeze:** Inline handler user-facing literals remain byte-equivalent unless explicitly versioned.
- [ ] **Versioned exception required:** Any intentional text change includes migration/version note and reviewer approval.
- [ ] **Catalog diff reviewed:** Reviewer checked both `docs/COMMAND_CATALOG.md` and `docs/MESSAGE_FREEZE.md` updates in the PR.
