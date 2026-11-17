# Keller Stock Monitor

This GitHub Actions workflow checks the three Keller 55 mm product pages every 10 minutes and sends an email when a product changes from out of stock to in stock.

## Email configuration

In **Settings → Secrets and variables → Actions**, add these repository secrets:

- `SMTP_HOST`: SMTP server hostname
- `SMTP_PORT`: SMTP port (usually `587` for STARTTLS; port `465` uses SSL)
- `SMTP_USER`: SMTP login name
- `SMTP_PASSWORD`: SMTP password or app password
- `MAIL_FROM`: sender address
- `MAIL_TO`: notification recipient address

Do not commit SMTP credentials or paste them into chat.

## Test email delivery

1. Open **Actions → Keller stock monitor → Run workflow**.
2. In the `run_mode` selector, choose `test_email`.
3. Click **Run workflow**.
4. Open that run and inspect the **Send test email** step.

The test sends a message to `MAIL_TO` without checking products or changing `data/stock_state.json`. The logs identify whether the SMTP connection, authentication, or message submission failed. SMTP credentials are never printed.

## Run a stock check manually

In **Actions → Keller stock monitor → Run workflow**, select `stock_check` (the default) and start the workflow.

The scheduled job checks every 10 minutes. The initial state marks all products as out of stock, so a confirmed in-stock result triggers the first restock notification. Unknown page markup is not treated as available. Always confirm availability on the seller's page.
