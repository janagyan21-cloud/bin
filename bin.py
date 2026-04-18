import os
import re
import logging
import aiohttp
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- LOAD ENV ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not found. Set it in .env or hosting panel.")

# ---------- LOGGING ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- FLAG ----------
def country_flag(code: str) -> str:
    if not code or len(code) != 2:
        return ""
    return chr(ord(code[0].upper()) + 127397) + chr(ord(code[1].upper()) + 127397)

# ---------- FETCH BIN ----------
async def get_bin(session, bin_number: str):
    url = f"https://data.handyapi.com/bin/{bin_number}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json()
            return {"error": f"HTTP {r.status}"}
    except Exception as e:
        return {"error": str(e)}

# ---------- FORMAT ----------
def format_bin(bin_number, data):
    if "error" in data:
        return f"<b>{bin_number}</b>\n❌ {data['error']}"

    country = data.get("Country", "N/A")
    code = data.get("A2", "")
    flag = country_flag(code)

    return f"""
<b>BIN: {bin_number}</b>

🏦 Bank: {data.get('Bank', 'N/A')}
💳 Brand: {data.get('Scheme', 'N/A')}
🔹 Type: {data.get('Type', 'N/A')}
🌍 Country: {flag} {country}
"""

# ---------- EXTRACT ----------
def extract_bins(text):
    nums = re.findall(r'\d+', text)
    return list({n[:6] for n in nums if len(n) >= 6})

# ---------- COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send: /bin 457173")

async def bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bins = extract_bins(" ".join(context.args))

    if not bins:
        await update.message.reply_text("❌ No valid BIN found")
        return

    await update.message.reply_text(f"🔍 Checking {len(bins)} BIN(s)...")

    async with aiohttp.ClientSession() as session:
        for b in bins:
            data = await get_bin(session, b)
            msg = format_bin(b, data)

            await update.message.reply_text(
                msg,
                parse_mode=ParseMode.HTML
            )

# ---------- MAIN ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bin", bin_cmd))

    logger.info("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()