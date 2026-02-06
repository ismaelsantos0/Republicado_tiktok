import os
import time
import json
import requests
from playwright.sync_api import sync_playwright

TIKTOK_USER = os.getenv("TIKTOK_USER", "").lstrip("@")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "300"))  # 5 min
STATE_FILE = "state.json"

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)

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

        # TikTok às vezes exige este "jeitinho" pra não travar carregamento
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        })

        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)

        # Tenta clicar na aba de Reposts (ícone ↻) se existir
        # (pode variar, então tentamos algumas formas)
        candidates = [
            "a:has(svg)",          # pega abas com ícone
            "a[href*='repost']",   # se existir algo assim
        ]

        clicked = False
        for sel in candidates:
            try:
                links = page.locator(sel)
                count = links.count()
                for i in range(min(count, 15)):  # evita varrer demais
                    a = links.nth(i)
                    href = a.get_attribute("href") or ""
                    # heuristic: algumas abas têm href relativo do perfil
                    if "@" in href and ("repost" in href.lower() or "reposts" in href.lower()):
                        a.click(timeout=2000)
                        clicked = True
                        break
                if clicked:
                    break
            except Exception:
                pass

        # Mesmo sem clicar, ainda dá pra achar os cards; mas vamos dar um tempo pro conteúdo aparecer
        page.wait_for_timeout(2500)

        # Pega o primeiro link de vídeo que aparecer na área visível
        # TikTok links de vídeo geralmente contém "/video/"
        video_link = page.locator("a[href*='/video/']").first
        if video_link.count() == 0:
            browser.close()
            return None

        href = video_link.get_attribute("href")
        browser.close()

        if href and href.startswith("/"):
            href = "https://www.tiktok.com" + href
        return href

def main():
    if not (TIKTOK_USER and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("Faltam variáveis: TIKTOK_USER, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
        return

    send_telegram("✅ Bot ligado. Vou te avisar quando aparecer repost novo.")
    last = load_last()

    while True:
        try:
            latest = get_latest_repost_url(TIKTOK_USER)
            if latest and latest != last:
                send_telegram(f"↻ Repost novo detectado:\n{latest}")
                last = latest
                save_last(latest)
            else:
                print("Nada novo.")
        except Exception as e:
            print("Erro:", str(e))

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
