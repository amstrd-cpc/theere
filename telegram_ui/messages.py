from __future__ import annotations

START_MESSAGE = (
    "🎵 *Welcome to the Record Store Bot\\!* 🎵\n\n"
    "Hello {first_name}\\!\n\n"
    "🔒 *This bot is password protected\\.*\n"
    "You must authenticate before using any commands\\.\n\n"
    "*Commands:*\n"
    "• /login \\- Enter password to authenticate\n"
    "• /help \\- Show this help message\n\n"
    "After authentication, you'll have access to:\n"
    "• /add \\- Add new records to inventory\n"
    "• /sell \\- Process record sales\n"
    "• /inventory \\- Search and view inventory\n"
    "• /reports \\- Generate sales reports\n"
    "• /status \\- Check authentication status\n"
    "• /logout \\- Sign out\n\n"
    "🔐 *Use /login to get started\\!*"
)

HELP_AUTHENTICATED = (
    "🎵 *Record Store Bot \\- Commands* 🎵\n\n"
    "*Inventory Management:*\n"
    "• /add \\- Add new records from Discogs\n"
    "• /inventory \\- Interactive inventory search\n"
    "• /stock \\- View low stock items\n\n"
    "*Sales:*\n"
    "• /sell \\- Process a sale\n"
    "• /sales \\- View recent sales\n\n"
    "*Reports:*\n"
    "• /reports \\- Generate sales reports\n"
    "• /daily \\- Today's sales summary\n"
    "• /weekly \\- Weekly sales report\n"
    "• /monthly \\- Monthly sales report\n\n"
    "*Account:*\n"
    "• /status \\- Check authentication status\n"
    "• /logout \\- Sign out\n"
    "• /users \\- View active users \\(admin\\)\n\n"
    "*General:*\n"
    "• /help \\- Show this help\n"
    "• /cancel \\- Cancel current operation"
)

HELP_UNAUTHENTICATED = (
    "🔒 *Authentication Required* 🔒\n\n"
    "*Available Commands:*\n"
    "• /login \\- Enter password to authenticate\n"
    "• /help \\- Show this help\n"
    "• /start \\- Welcome message\n\n"
    "*After authentication, you'll have access to:*\n"
    "• Inventory management\n"
    "• Sales processing\n"
    "• Report generation\n"
    "• And much more\\!\n\n"
    "🔐 *Use /login to get started\\!*"
)

RECENT_SALES_EMPTY = "📊 No recent sales found\\."

DAILY_REPORT_EMPTY = "📭 No sales recorded for today yet."
WEEKLY_REPORT_EMPTY = "📭 No sales recorded for this week yet."
MONTHLY_REPORT_EMPTY = "📭 No sales recorded for this month yet."

REPORT_ERROR = "❌ Error generating report: {error}"
REPORT_DAILY_ERROR = "❌ Error generating daily report: {error}"
REPORT_WEEKLY_ERROR = "❌ Error generating weekly report: {error}"
REPORT_MONTHLY_ERROR = "❌ Error generating monthly report: {error}"
REPORTS_EMPTY = "📭 No sales recorded for today yet.\nStart selling some records to generate a report! 🎵"

AUTH_REQUIRED = (
    "🔒 Access Denied!\n\n"
    "You need to authenticate first.\n"
    "Use /login to enter the password."
)

AUTH_REQUIRED_MARKDOWN = (
    "🔒 **Access Denied!**\n\n"
    "You must authenticate first.\n"
    "Use /login to enter the password."
)

LOGIN_PROMPT = (
    "🔐 **Authentication Required**\n\n"
    "Please enter the bot password:"
)

LOGIN_ALREADY = (
    "✅ You are already authenticated!\n"
    "Session expires in: {time_left}\n\n"
    "Use /logout to sign out or /help to see available commands."
)

LOGIN_SUCCESS = (
    "✅ **Authentication Successful!**\n\n"
    "Welcome, {first_name}!\n"
    "Session expires in {hours} hours.\n\n"
    "You can now use all bot commands.\n"
    "Type /help to see available commands."
)

LOGIN_FAILURE = (
    "❌ **Incorrect Password!**\n\n"
    "Access denied. Please try again with /login"
)

LOGOUT_SUCCESS = (
    "✅ **Logged Out Successfully**\n\n"
    "You have been signed out of the bot.\n"
    "Use /login to authenticate again."
)

LOGOUT_ALREADY = (
    "ℹ️ You are not currently logged in.\n"
    "Use /login to authenticate."
)

STATUS_ACTIVE = (
    "✅ **Authentication Status: ACTIVE**\n\n"
    "Session expires in: {time_left}\n"
    "Use /logout to sign out."
)

STATUS_INACTIVE = (
    "❌ **Authentication Status: NOT AUTHENTICATED**\n\n"
    "Use /login to enter the password."
)

ADMIN_USERS_EMPTY = "No active users."
ADMIN_USERS_HEADER = "👥 **Active Users:**\n\n"
ADMIN_AUTH_REQUIRED = "🔒 Authentication required!"

CANCEL_LOGIN = "🚫 Login cancelled."

ADD_DISCOGS_MISSING = "⚠️ Discogs is not configured. Set DISCOGS_TOKEN to enable /add."
ADD_PROMPT_QUERY = "Enter album name (Artist - Title):"
ADD_SELECT_RELEASE = "Select a release:"
ADD_SELECT_CONDITION = "Selected: {title}\n\nNow choose vinyl condition:"
ADD_SUGGESTED_PRICE = "Suggested price for {full_condition}: ${price_usd:.2f} ≈ {price_gel:.2f} GEL"
ADD_NO_SUGGESTION = "No price suggestion found."
ADD_PRICE_PROMPT = "\n\nSend your own price in GEL or type 'ok' to accept the suggested price."
ADD_PRICE_INVALID = "❌ Invalid price. Please enter a valid number or 'ok' to accept suggested price:"
ADD_QUANTITY_PROMPT = "How many copies do you want to add?"
ADD_QUANTITY_INVALID = "❌ Invalid quantity. Enter a whole number ≥ 1:"
ADD_SELECT_SUPPLIER = "Select supplier:"
ADD_SUPPLIER_PROMPT = "Enter supplier name:"
ADD_SUPPLIER_STALE = "⚠️ This supplier button is from an old /add session. Run /add again."
ADD_SAVED_LOCAL = "✅ Saved locally (ID: {inventory_id}). Syncing to Woo…"
ADD_WOO_NOT_CONFIGURED = "🛒 Woo not configured: set WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET"
ADD_WOO_FAILED = "🛒 Woo sync failed: {error}"
ADD_WOO_OK = "🛒 Woo sync OK. Product id: {woo_id}"
ADD_SAVE_ERROR = "❌ Error saving to inventory: {error}"
ADD_CANCEL = "🚫 Add flow cancelled."

SELL_WELCOME = (
    "💰 Welcome to the Sell Vinyls flow!\n"
    "Please enter the artist or album name you want to sell:"
)
SELL_NOT_FOUND = "❌ No matching records found for: <b>{query}</b>"
SELL_SELECT_PROMPT = "Please select the record you want to sell:"
SELL_SELECTED = (
    "Selected: <b>{artist_album}</b>\n"
    "Condition: {condition}\n"
    "Available: {quantity} copies\n"
    "Listed price: ₾{price:.2f}\n\n"
    "Enter the selling price or type 'ok' to use the listed price:"
)
SELL_PRICE_NEGATIVE = "❌ Price cannot be negative. Please enter a valid price or 'ok':"
SELL_PRICE_INVALID = "❌ Invalid price format. Please enter a valid number or 'ok':"
SELL_ADDED = (
    "Added {artist_album} - ₾{price:.2f} to cart.\n"
    "Add another item or proceed to checkout?"
)
SELL_NEXT_PROMPT = "Enter the artist or album name of the next record:"
SELL_PAYMENT_PROMPT = "Choose payment method:"
SELL_CANCEL = "❌ Sale cancelled."
SELL_CART_EMPTY = "Cart is empty."
SELL_FAILED_ITEM = "Failed to sell {artist_album} (out of stock)"
SELL_ERROR_PROCESSING = "❌ Error processing sale: {error}"
SELL_PAYMENT_LINE = "Payment: {method}"
SELL_TOTAL_LINE = "Total: ₾{total:.2f}"

INVENTORY_SEARCH_PROMPT = (
    "🔍 Inventory Search\n\n"
    "Please enter your search query:\n"
    "• Artist name (e.g., 'Beatles')\n"
    "• Album name (e.g., 'Abbey Road')\n"
    "• Partial match (e.g., 'Dark Side')\n"
    "• Or type 'all' to see everything\n\n"
    "Type /cancel to cancel this operation."
)
INVENTORY_QUERY_INVALID = "❌ Please enter a valid search query or type /cancel to cancel."
INVENTORY_SEARCHING = "🔍 Searching inventory..."
INVENTORY_NO_RESULTS = (
    "❌ No records found\n\n"
    "Search query: {query}\n\n"
    "Try a different search term or use /inventory to search again."
)
INVENTORY_SEARCH_ERROR = (
    "❌ Error searching inventory\n\n"
    "An error occurred: {error}\n\n"
    "Please try again with /inventory"
)
INVENTORY_ALL_TITLE = "📦 All Inventory"
INVENTORY_SEARCH_TITLE = "🔍 Search Results for: {query}"
INVENTORY_SELECT_PROMPT = "Select a record to view details and editing options:"
INVENTORY_FOUND = "Found {count} record(s)\n\n"
INVENTORY_SHOWING = "📄 Showing 1-8 of {total} results"
INVENTORY_USE_AGAIN = "Use /inventory to start a new search."
INVENTORY_CANCEL = "🚫 Inventory search cancelled."

STOCK_EMPTY = "📦 No low stock items found."
STOCK_HEADER = "📦 Low Stock Items\n\n"

WOO_NOT_CONFIGURED_MESSAGE = "🛒 Woo sync is not configured. Set WC_API_URL / WC_CONSUMER_KEY / WC_CONSUMER_SECRET in .env"
WOO_SYNC_NOTE = "New items added via /add will sync automatically in the background."
