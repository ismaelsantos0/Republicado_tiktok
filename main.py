import os
import time
import json
import requests
from playwright.sync_api import sync_playwright

TIKTOK_USER = os.getenv("TIKTOK_USER", "").lstrip("@")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "300"))  # teste: 10 / 30 / 60
STATE_FILE = "state.json"

DEBUG = os.getenv("DEBUG", "1") == "1"


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30)
    if DEBUG:
        print("Telegram msg status:", r.status_code, r.text[:200])


def send_telegram_photo(png_bytes: bytes, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("debug.png", png_bytes)}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]}
    r = requests.post(url, files=files, data=data, timeout=60)
    if DEBUG:
        print("Telegram photo status:", r.status_code, r.text[:200])


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def normalize_tiktok_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("/"):
        return "https://www.tiktok.com" + href
    return href


def get_latest_repost_url(username: str) -> str | None:
    profile_url = f"https://www.tiktok.com/@{username}"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ],
        )
        page = browser.new_page()

        # Headers para ajudar o TikTok a carregar melhor
        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)  # espera mais pra carregar

        # Debug básico
        try:
            title = page.title()
        except Exception:
            title = "(sem title)"
        current_url = page.url

        if DEBUG:
            print("TITLE:", title)
            print("URL:", current_url)

        # 1) Tenta clicar na aba de cima (onde pode estar Reposts).
        clicked_any = False
        tab_debug = []
        try:
            tabs = page.locator("div[role='tablist'] a")
            c = tabs.count()
            if DEBUG:
                print("Tabs encontradas:", c)

            # guarda href das primeiras abas pra debug
            for i in range(min(c, 8)):
                href = tabs.nth(i).get_attribute("href") or ""
                tab_debug.append(f"{i}:{href}")

            # tenta alguns índices comuns (varia por layout)
            for idx in [2, 3, 1, 4]:
                if c > idx:
                    try:
                        tabs.nth(idx).click(timeout=2500)
                        page.wait_for_timeout(4000)
                        clicked_any = True
                        if DEBUG:
                            print(f"Cliquei na aba idx={idx}")
                        break
                    except Exception:
                        pass
        except Exception as e:
            if DEBUG:
                print("Falha ao lidar com tabs:", str(e))

        # 2) Rola para forçar os cards aparecerem
        try:
            page.mouse.wheel(0, 1700)
            page.wait_for_timeout(2500)
            page.mouse.wheel(0, 1700)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        # 3) Coletar links de vídeo
        loc = page.locator("a[href*='/video/']")
        count = loc.count()

        if DEBUG:
            print("QTD links /video/ encontrados:", count)

        if count == 0:
            # Se não achou nada, manda PRINT pro Telegram com diagnóstico
            html = ""
            try:
                html = page.content().lower()
            except Exception:
                pass

            flagged = []
            for word in ["captcha", "verify", "verification", "unusual", "suspicious", "access denied", "consent", "cookies"]:
                if word in html:
                    flagged.append(word)

            png = page.screenshot(full_page=True, type="png")

            caption = (
                "⚠️ Não encontrei nenhum link /video/.\n"
                f"Title: {title}\n"
                f"URL: {current_url}\n"
                f"Tabs: {', '.join(tab_debug) if tab_debug else 'nenhuma'}\n"
                f"Cliquei em aba? {'sim' if clicked_any else 'não'}\n"
                f"Sinais: {', '.join(flagged) if flagged else 'nenhum'}"
            )

            send_telegram_photo(png, caption=caption)
            browser.close()
            return None

        # Se achou links, pegamos o primeiro (mais recente na tela)
        href = loc.first.get_attribute("href")
        href = normalize_tiktok_url(href)

        browser.close()
        return href


def main():
    if not (TIKTOK_USER and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("Faltam variáveis: TIKTOK_USER, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
        return

    state = load_state()
    last = state.get("last_url")

    send_telegram("✅ Bot ligado. Vou te avisar quando aparecer repost novo.")

    while True:
        try:
            latest = get_latest_repost_url(TIKTOK_USER)

            if latest and latest != last:
                send_telegram(f"↻ Possível repost novo detectado:\n{latest}")
                last = latest
                state["last_url"] = latest
                save_state(state)
            else:
                if DEBUG:
                    print("Nada novo (ou não achei link).")

        except Exception as e:
            print("Erro geral:", str(e))

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
