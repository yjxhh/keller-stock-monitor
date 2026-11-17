#!/usr/bin/env python3
"""Monitor Keller 55 mm product stock and email on restock transitions."""
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
    "User-Agent": "Mozilla/5.0 (compatible; KellerStockMonitor/1.0)",
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


def send_restock_email(products: list[dict[str, str]]) -> None:
    required = (
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing GitHub Actions secrets: " + ", ".join(missing))

    message = EmailMessage()
    message["Subject"] = f"Keller 补货提醒：{len(products)} 款商品可能有货"
    message["From"] = os.environ["MAIL_FROM"]
    message["To"] = os.environ["MAIL_TO"]
    lines = ["Keller 监控发现以下商品可能已经恢复库存：", ""]
    for product in products:
        lines.extend((product["name"], product["url"], ""))
    lines.append("请打开商品页面再次确认库存。")
    message.set_content("\n".join(lines))

    with smtplib.SMTP(
        os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30
    ) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)
    print("Restock notification email sent.")


def main() -> int:
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

    # Preserve all old states if any page could not be checked/classified.
    if failures:
        print(f"{failures} product check(s) unresolved; state was not changed.", file=sys.stderr)
        return 1

    if restocked:
        send_restock_email(restocked)

    save_state(current)
    print("All product checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
