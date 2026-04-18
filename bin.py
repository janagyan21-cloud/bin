import os
import re
import logging
import asyncio
import html
import aiohttp
from telegram import Update, Document
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ---------- Country code → flag ----------
def country_code_to_flag(code: str) -> str:
    if not code or len(code) != 2:
        return ""
    return chr(ord(code[0].upper()) + 0x1F1E6 - 65) + chr(ord(code[1].upper()) + 0x1F1E6 - 65)


# ---------- Normalize API response ----------
def normalize_api_response(data: dict) -> dict:

    if isinstance(data, list) and len(data):
        data = data[0]

    if isinstance(data, dict) and data.get("data") and isinstance(data["data"], dict):
        data = data["data"]

    def pick(obj, paths, default="N/A"):
        if not obj:
            return default

        for path in paths:

            if "." in path:
                parts = path.split(".")
                cur = obj

                for part in parts:
                    if isinstance(cur, dict) and part in cur:
                        cur = cur[part]
                    else:
                        cur = None
                        break

                if cur not in (None, ""):
                    return cur

            else:
                if path in obj and obj[path] not in (None, ""):
                    return obj[path]

        return default


    bank = pick(data, [
        "Bank", "bank", "bank_name", "Issuer",
        "issuer_name", "name", "bankName",
        "brandName", "BankName"
    ])

    brand = pick(data, [
        "Brand", "brand", "scheme",
        "CardTier", "network", "cardBrand"
    ])

    card_type = pick(data, [
        "Type", "type", "card_type",
        "schemeType", "cardType",
        "paymentType"
    ])

    # FIXED CATEGORY
    category = pick(
        data,
        [
            "Level",
            "level",
            "category",
            "cardCat",
            "category_name",
            "card_category",
            "product",
            "product_name",
            "card_level",
            "CardLevel"
        ]
    )

    country = pick(data, [
        "Country.Name", "country.name",
        "country_name", "country",
        "Country", "CountryName"
    ])

    country_code = pick(
        data,
        [
            "Country.A2",
            "country.a2",
            "country.alpha2",
            "countryCode",
            "country_alpha2",
            "A2"
        ],
        default="xx"
    )

    website = pick(data, [
        "Website",
        "website",
        "url",
        "issuer_website",
        "bank_url"
    ], default="")

    phone = pick(data, [
        "Phone",
        "phone",
        "contact",
        "issuer_contact",
        "bank_phone"
    ], default="")


    if bank in ("N/A", "") and isinstance(data.get("bank"), dict):
        deep_bank = pick(data["bank"], ["name", "bank_name", "display_name", "Bank"], default=None)
        if deep_bank:
            bank = deep_bank


    return {
        "bank": bank,
        "brand": brand,
        "type": card_type,
        "category": category,
        "country": country,
        "country_code": country_code.lower(),
        "website": website,
        "phone": phone,
    }


# ---------- API Fetch ----------
_semaphore = asyncio.Semaphore(10)

async def fetch_bin_info(bin_number: str):

    url = f"https://data.handyapi.com/bin/{bin_number}"

    async with _semaphore:

        async with aiohttp.ClientSession() as session:

            try:

                async with session.get(url, timeout=10) as resp:

                    if resp.status == 200:

                        data = await resp.json()

                        return normalize_api_response(data)

                    else:

                        return {"error": f"HTTP {resp.status}"}

            except Exception as e:

                logger.exception(e)

                return {"error": str(e)}


# ---------- Process BINs ----------
async def process_bins(bins):

    tasks = [fetch_bin_info(b) for b in bins]

    results = await asyncio.gather(*tasks)

    return list(zip(bins, results))


# ---------- Format Output ----------
def format_bin_result(bin_num, info):

    if "error" in info:
        return f"<b>{bin_num}</b>: ❌ Error – {html.escape(info['error'])}"

    flag = country_code_to_flag(info.get("country_code", ""))

    country = info.get("country")

    if flag:
        country = f"{flag} {html.escape(country)}"

    lines = [

        f"<b>BIN {bin_num}</b>",
        f"🏦 <b>Bank:</b> {html.escape(info['bank'])}",
        f"💳 <b>Brand:</b> {html.escape(info['brand'])}",
        f"🔹 <b>Type:</b> {html.escape(info['type'])}",
        f"📂 <b>Category:</b> {html.escape(info['category'])}",
        f"🌍 <b>Country:</b> {country}"

    ]

    if info.get("website"):
        lines.append(f"🌐 <b>Website:</b> {html.escape(info['website'])}")

    if info.get("phone"):
        lines.append(f"📞 <b>Phone:</b> {html.escape(info['phone'])}")

    return "\n".join(lines)


# ---------- Extract BIN ----------
def extract_bins_from_text(text):

    numbers = re.findall(r'\d+', text)

    bins = [n[:6] for n in numbers if len(n) >= 6]

    seen = set()
    unique = []

    for b in bins:
        if b not in seen:
            seen.add(b)
            unique.append(b)

    return unique


# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Send:\n"
        "/bin 457173\n"
        "or multiple BINs",
        parse_mode=ParseMode.HTML
    )


async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text("Example:\n/bin 457173")

        return

    bins = extract_bins_from_text(" ".join(context.args))

    if not bins:

        await update.message.reply_text("No valid BINs")

        return

    await update.message.reply_text(f"Searching {len(bins)} BINs...")

    results = await process_bins(bins)

    for bin_num, info in results:

        msg = format_bin_result(bin_num, info)

        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ---------- Main ----------
def main():

    token = os.environ.get("BOT_TOKEN", "8618570548:AAGhWtjngH17RnPO5noICpyg1cTnbyCaxiA")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bin", bin_command))

    app.run_polling()


if __name__ == "__main__":
    main()