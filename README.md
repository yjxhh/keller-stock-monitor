# Keller Stock Monitor

This GitHub Actions workflow checks the three Keller 55 mm product pages every 10 minutes and sends an email when a product changes from out of stock to in stock.

## Configure email

In **Settings → Secrets and variables → Actions**, add these repository secrets:

- `SMTP_HOST`: SMTP server hostname
- `SMTP_PORT`: SMTP port (commonly `587` for STARTTLS)
- `SMTP_USER`: SMTP login name
- `SMTP_PASSWORD`: SMTP password or app password
- `MAIL_FROM`: sender address
- `MAIL_TO`: recipient address

Do not commit SMTP credentials or paste them into chat.

## Run a manual check

Open **Actions → Keller stock monitor → Run workflow**.

The initial state marks all products as out of stock, so the first confirmed in-stock result will trigger an email. Unknown page markup is not treated as in stock. Always confirm availability on the seller's page.
