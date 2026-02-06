import os
import time
import json
import requests
from playwright.sync_api import sync_playwright

TIKTOK_USER = os.getenv("TIKTOK_USER", "").lstrip("@")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "300"))  # padrão 5 min
STATE_FILE = "state.json"

DEBUG = os.getenv("DEBUG", "1") == "1"


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30)
    if DEBUG:
        print("Telegram status:", r.status_code, r.text[:200])


def load_last():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("last_url")
    except Exception:
        return None


def save_last(url: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_url": url}, f)


def get_latest_repost_url(username: str) -> str | None:
    profile_url = f"https://www.tiktok.com/@{username}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Ajuda o TikTok a não "capar" o carregamento
        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 1) Tenta clicar em alguma aba do topo (Reposts costuma estar ali)
        # A posição pode variar, então tentamos algumas opções de índice.
        try:
            tabs = page.locator("div[role='tablist'] a")
            c = tabs.count()
            if DEBUG:
                print("Tabs encontradas:", c)

            # Tentativas comuns: 2ª, 3ª, 4ª aba
            for idx in [2, 1, 3]:
                if c > idx:
                    try:
                        tabs.nth(idx).click(timeout=2000)
                        page.wait_for_timeout(3500)
                        if DEBUG:
                            print(f"Cliquei na aba idx={idx}")
                        break
                    except Exception:
                        pass
        except Exception as e:
            if DEBUG:
                print("Falha ao clicar em abas:", str(e))

        # 2) Rola para forçar carregar os cards
        try:
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(2500)
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        # 3) Busca links de vídeo
        loc = page.locator("a[href*='/video/']")
        count = loc.count()

        if DEBUG:
            print("QTD links /video/ encontrados:", count)
            # printa alguns pra debug
            for i in range(min(count, 8)):
                href_i = loc.nth(i).get_attribute("href")
                print(" -", i, href_i)

        if count == 0:
            # Se quiser, descomenta pra gerar print (pode pesar no Railway)
            # page.screenshot(path="debug.png", full_page=True)
            browser.close()
            return None

        href = loc.first.get_attribute("href")
        browser.close()

        if href and href.startswith("/"):
            href = "https://www.tiktok.com" + href

        return href


def main():
    if not (TIKTOK_USER and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("Faltam variáveis: TIKTOK_USER, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
        return

    last = load_last()

    # Mensagem inicial só pra confirmar que ligou
    send_telegram("✅ Bot ligado. Vou te avisar quando aparecer repost novo.")

    while True:
        try:
            latest = get_latest_repost_url(TIKTOK_USER)

            if latest and latest != last:
                send_telegram(f"↻ Repost novo detectado:\n{latest}")
                last = latest
                save_last(latest)
            else:
                if DEBUG:
                    print("Nada novo (ou não achei link).")

        except Exception as e:
            print("Erro geral:", str(e))

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
