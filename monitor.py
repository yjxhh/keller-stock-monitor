#!/usr/bin/env python3
"""Monitor Keller 55 mm product stock and send email notifications."""
from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PRODUCTS = {
    "rollo_blue_25mm": {
        "name": "ROLLO BLUE Micro Slim 55 x 25 mm",
        "url": "https://www.kellerww.de/shop/ROLLO-BLUE-Micro-Slim-weisse-Filterhuelsen-55-x-25-mm-Filter-200-pro-Box-5-Boxen-1-VE",
    },
    "rollo_blue_20mm": {
        "name": "ROLLO BLUE Micro Slim White 55 x 20 mm",
        "url": "https://www.kellerww.de/shop/ROLLO-BLUE-Micro-Slim-White-Zigarettenhuelsen-55-x-20-mm-Filter-200-pro-Box-5-Boxen-1-VE",
    },
    "rollo_red_20mm": {
        "name": "ROLLO RED Micro Slim Full Flavour 55 x 20 mm",
        "url": "https://www.kellerww.de/shop/ROLLO-RED-Micro-Slim-Full-Flavour-Zigarettenhuelsen-55-x-20-mm-200-pro-Box-5-Boxen-1-VE",
    },
}
STATE_FILE = Path("data/stock_state.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KellerStockMonitor/1.1)",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
SOLD_OUT = (
    "ausverkauft", "momentan nicht verfuegbar", "nicht lieferbar",
    "nicht verfuegbar", "out of stock", "sold out",
)


def normalize(value: str) -> str:
    value = value.lower().replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
    return re.sub(r"\s+", " ", value)


def get_jsonld_availability(soup: BeautifulSoup) -> str | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                value = item.get("availability")
                if isinstance(value, str):
                    return value.lower()
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return None


def classify_html(html: str) -> str:
    """Return in_stock, out_of_stock or unknown; unknown never alerts."""
    soup = BeautifulSoup(html, "html.parser")
    availability = get_jsonld_availability(soup)
    if availability:
        if "outofstock" in availability or "soldout" in availability:
            return "out_of_stock"
        if "instock" in availability or "limitedavailability" in availability:
            return "in_stock"

    text = normalize(soup.get_text(" ", strip=True))
    if any(normalize(term) in text for term in SOLD_OUT):
        return "out_of_stock"

    for element in soup.find_all(["button", "a", "input"]):
        label = normalize(" ".join((
            element.get_text(" ", strip=True),
            str(element.get("value", "")),
            str(element.get("aria-label", "")),
        )))
        if any(term in label for term in ("in den warenkorb", "add to cart", "jetzt kaufen")):
            if not element.has_attr("disabled") and element.get("aria-disabled") != "true":
                return "in_stock"

    if any(term in text for term in (
        "in den warenkorb", "jetzt kaufen", "sofort lieferbar",
        "auf lager", "lieferbar", "add to cart",
    )):
        return "in_stock"
    return "unknown"


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {key: "out_of_stock" for key in PRODUCTS}
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {key: saved.get(key, "unknown") for key in PRODUCTS}
    except (OSError, json.JSONDecodeError):
        print("WARNING: Cannot read saved state; previous state is unknown.", file=sys.stderr)
        return {key: "unknown" for key in PRODUCTS}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def email_settings() -> tuple[str, int, str, str, str, str]:
    required = (
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Missing GitHub Actions secrets: " + ", ".join(missing)
        )
    try:
        port = int(os.environ["SMTP_PORT"])
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be a number, for example 587 or 465.") from exc

    return (
        os.environ["SMTP_HOST"],
        port,
        os.environ["SMTP_USER"],
        os.environ["SMTP_PASSWORD"],
        os.environ["MAIL_FROM"],
        os.environ["MAIL_TO"],
    )


def send_email(message: EmailMessage) -> None:
    host, port, username, password, _, _ = email_settings()
    print(f"SMTP: connecting to {host}:{port} ...")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                print("SMTP: SSL connection established; authenticating ...")
                smtp.login(username, password)
                print("SMTP: authentication successful; sending message ...")
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                print("SMTP: STARTTLS connection established; authenticating ...")
                smtp.login(username, password)
                print("SMTP: authentication successful; sending message ...")
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            f"SMTP authentication failed (code {exc.smtp_code}). "
            "Check SMTP_USER and SMTP_PASSWORD; many providers require an app password."
        ) from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(
            f"SMTP connection rejected (code {exc.smtp_code}): {exc.smtp_error!r}"
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise RuntimeError(
            f"SMTP rejected recipient address(es): {list(exc.recipients.keys())}"
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP error while sending email: {exc}") from exc
    print("SMTP: message accepted by the outgoing mail server.")


def send_restock_email(products: list[dict[str, str]]) -> None:
    _, _, _, _, mail_from, mail_to = email_settings()
    message = EmailMessage()
    message["Subject"] = f"Keller 补货提醒：{len(products)} 款商品可能有货"
    message["From"] = mail_from
    message["To"] = mail_to
    lines = ["Keller 监控发现以下商品可能已经恢复库存：", ""]
    for product in products:
        lines.extend((product["name"], product["url"], ""))
    lines.append("请打开商品页面再次确认库存。")
    message.set_content("\n".join(lines))
    send_email(message)


def send_test_email() -> None:
    _, _, _, _, mail_from, mail_to = email_settings()
    message = EmailMessage()
    message["Subject"] = "Keller 库存监控 - 邮件配置测试"
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(
        "这是一封 Keller 库存监控测试邮件。\n\n"
        "如果你收到这封邮件，说明 GitHub Actions 已成功连接 SMTP 并提交邮件。\n"
        "测试邮件不会修改商品库存状态。\n"
    )
    print(f"Test email recipient: {mail_to}")
    send_email(message)


def main() -> int:
    mode = os.getenv("MONITOR_MODE", "stock_check").strip().lower()
    if mode == "test_email":
        send_test_email()
        print("Test email completed successfully. Stock state was not read or changed.")
        return 0
    if mode != "stock_check":
        raise RuntimeError(
            f"Unknown MONITOR_MODE={mode!r}; expected 'stock_check' or 'test_email'."
        )

    session = requests.Session()
    session.headers.update(HEADERS)
    previous = load_state()
    current = dict(previous)
    restocked: list[dict[str, str]] = []
    failures = 0

    for key, product in PRODUCTS.items():
        try:
            response = session.get(product["url"], timeout=35)
            response.raise_for_status()
            status = classify_html(response.text)
            print(f'{product["name"]}: {status} (HTTP {response.status_code})')
            if status == "unknown":
                failures += 1
                continue
            if previous.get(key) == "out_of_stock" and status == "in_stock":
                restocked.append(product)
            current[key] = status
        except requests.RequestException as exc:
            failures += 1
            print(f'ERROR {product["name"]}: {exc}', file=sys.stderr)

    if failures:
        print(
            f"{failures} product check(s) unresolved; state was not changed.",
            file=sys.stderr,
        )
        return 1

    if restocked:
        send_restock_email(restocked)

    save_state(current)
    print("All product checks completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
