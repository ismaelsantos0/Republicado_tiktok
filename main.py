import os
import time
import json
import traceback
import requests
from playwright.sync_api import sync_playwright

# ====== ENV ======
TIKTOK_USER = os.getenv("TIKTOK_USER", "").lstrip("@")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "60"))
STATE_FILE = "state.json"
DEBUG = os.getenv("DEBUG", "1") == "1"

def log(*args):
    print(*args, flush=True)

# ====== TELEGRAM ======
def tg_send(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30)
    return r

def tg_send_photo(png_bytes: bytes, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("debug.png", png_bytes)}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]}
    r = requests.post(url, files=files, data=data, timeout=60)
    return r

def telegram_sanity_check():
    log("== TELEGRAM SANITY CHECK ==")
    if not TELEGRAM_TOKEN:
        log("ERRO: TELEGRAM_TOKEN vazio")
        return False
    if not TELEGRAM_CHAT_ID:
        log("ERRO: TELEGRAM_CHAT_ID vazio")
        return False

    try:
        r = tg_send("🧪 PING: bot iniciou e está testando Telegram.")
        log("Telegram status:", r.status_code)
        log("Telegram resp:", r.text[:500])
        return r.ok
    except Exception as e:
        log("ERRO ao falar com Telegram:", str(e))
        log(traceback.format_exc())
        return False

# ====== STATE ======
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def normalize_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("/"):
        return "https://www.tiktok.com" + href
    return href

# ====== TIKTOK CHECK ======
def get_latest_video_url_from_page(username: str) -> str | None:
    """Diagnóstico: só tenta achar QUALQUER /video/ no perfil.
    Ainda não é 'reposts'. Primeiro vamos garantir que o TikTok carrega algo.
    """
    profile_url = f"https://www.tiktok.com/@{username}"
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9"
        })

        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(2500)

        try:
            title = page.title()
        except Exception:
            title = "(sem title)"
        log("TikTok title:", title)
        log("TikTok url:", page.url)

        loc = page.locator("a[href*='/video/']")
        count = loc.count()
        log("Encontrados /video/:", count)

        if count == 0:
            # manda print pro telegram (se telegram ok)
            png = page.screenshot(full_page=True, type="png")
            try:
                r = tg_send_photo(png, caption=f"⚠️ Sem /video/ no perfil @{username}\nTitle: {title}\nURL: {page.url}")
                log("Telegram photo status:", r.status_code, r.text[:200])
            except Exception as e:
                log("Falha ao mandar print:", str(e))
            browser.close()
            return None

        href = normalize_url(loc.first.get_attribute("href"))
        browser.close()
        return href

def main():
    log("=== START ===")
    log("TIKTOK_USER:", TIKTOK_USER or "(vazio)")
    log("CHECK_EVERY_SECONDS:", CHECK_EVERY_SECONDS)
    log("DEBUG:", DEBUG)

    tg_ok = telegram_sanity_check()
    if not tg_ok:
        log("❌ Telegram não respondeu OK. Parei aqui pra você ajustar as variáveis.")
        return

    if not TIKTOK_USER:
        tg_send("⚠️ TIKTOK_USER está vazio. Coloca seu usuário nas variáveis.")
        return

    state = load_state()
    last = state.get("last_url")

    tg_send("✅ Bot rodando. Vou checar seu perfil e te avisar quando detectar algo novo.")

    while True:
        try:
            latest = get_latest_video_url_from_page(TIKTOK_USER)

            if latest and latest != last:
                tg_send(f"🔎 Detectei um link de vídeo no seu perfil:\n{latest}\n\n(Obs: isso ainda é diagnóstico, depois ajustamos pra pegar só reposts.)")
                last = latest
                state["last_url"] = latest
                save_state(state)
            else:
                log("Nada novo (ou TikTok não carregou).")

        except Exception as e:
            log("ERRO no loop:", str(e))
            log(traceback.format_exc())
            try:
                tg_send(f"❌ Erro no bot:\n{str(e)[:150]}")
            except Exception:
                pass

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
