import os
import time
import json
import traceback
import shutil
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
    return requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30)


def tg_send_photo(png_bytes: bytes, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("debug.png", png_bytes)}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]}
    return requests.post(url, files=files, data=data, timeout=60)


def telegram_sanity_check() -> bool:
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
        log("Telegram resp:", r.text[:300])
        return r.ok
    except Exception as e:
        log("ERRO Telegram:", str(e))
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


# ====== CHROMIUM (system) ======
def find_system_chromium() -> str | None:
    candidates = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return None


# ====== PAGE HELPERS ======
def page_has_error_overlay(page) -> bool:
    # Detecta a tela "Algo deu errado"
    try:
        return page.locator("text=Algo deu errado").count() > 0
    except Exception:
        return False


def open_reposts_tab(page) -> bool:
    # Tenta clicar pelo texto visível "Republicações"
    try:
        tab = page.locator("text=Republicações").first
        if tab.count() > 0:
            tab.click(timeout=3000)
            page.wait_for_timeout(4500)
            return True
    except Exception:
        pass

    # Fallback por role=tab
    try:
        tab = page.get_by_role("tab", name="Republicações")
        tab.click(timeout=3000)
        page.wait_for_timeout(4500)
        return True
    except Exception:
        return False


def screenshot_to_telegram(page, caption: str):
    try:
        png = page.screenshot(full_page=True, type="png")
        r = tg_send_photo(png, caption=caption)
        log("Telegram photo:", r.status_code, r.text[:200])
    except Exception as e:
        log("Falha ao mandar print:", str(e))


# ====== CORE: PEGAR ÚLTIMO REPOST (LINK) ======
def get_latest_repost_url(username: str) -> str | None:
    profile_url = f"https://www.tiktok.com/@{username}"

    chrome_path = find_system_chromium()
    if not chrome_path:
        raise RuntimeError("Não achei Chromium no sistema. Confirma nixpacks.toml com nixPkgs=['chromium'].")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=chrome_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9",
        })

        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)

        # Debug
        try:
            title = page.title()
        except Exception:
            title = "(sem title)"
        log("TikTok title:", title)
        log("TikTok url:", page.url)
        log("Chromium usado:", chrome_path)

        # Se já veio a tela de erro do TikTok, manda print
        if page_has_error_overlay(page):
            screenshot_to_telegram(page, "⚠️ TikTok web mostrou 'Algo deu errado' (pode ser bloqueio/instabilidade).")
            browser.close()
            return None

        # Clique na aba Republicações
        clicked = open_reposts_tab(page)
        if not clicked:
            screenshot_to_telegram(page, "⚠️ Não consegui clicar em 'Republicações'. Veja o print.")
            browser.close()
            return None

        # Se ao entrar em Republicações der erro, print
        if page_has_error_overlay(page):
            screenshot_to_telegram(page, "⚠️ Após clicar em 'Republicações', apareceu 'Algo deu errado'.")
            browser.close()
            return None

        # Rola pra forçar carregar cards de repost
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(3500)

        # Pega o primeiro link /video/ visível na aba
        loc = page.locator("a[href*='/video/']")
        count = loc.count()
        log("Links /video/ em Republicações:", count)

        if count == 0:
            screenshot_to_telegram(page, "⚠️ Entrei em 'Republicações' mas não encontrei links /video/. Veja o print.")
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

    if not telegram_sanity_check():
        log("❌ Telegram não respondeu OK. Ajuste variáveis e redeploy.")
        return

    if not TIKTOK_USER:
        tg_send("⚠️ TIKTOK_USER está vazio. Coloque seu usuário nas variáveis.")
        return

    # Confirma chromium
    chrome_path = find_system_chromium()
    if not chrome_path:
        tg_send("❌ Não achei Chromium no sistema. Confirme nixpacks.toml com chromium e faça redeploy.")
        log("Chromium não encontrado no PATH.")
        return

    tg_send("✅ Bot rodando. Vou monitorar 'Republicações' e te avisar quando detectar repost novo.")

    state = load_state()
    last = state.get("last_repost_url")

    while True:
        try:
            latest = get_latest_repost_url(TIKTOK_USER)

            if latest and latest != last:
                tg_send(f"↻ Repost novo detectado:\n{latest}")
                last = latest
                state["last_repost_url"] = latest
                save_state(state)
            else:
                log("Nada novo (ou TikTok não carregou).")

        except Exception as e:
            log("ERRO no loop:", str(e))
            log(traceback.format_exc())
            try:
                tg_send(f"❌ Erro no bot:\n{str(e)[:250]}")
            except Exception:
                pass

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
