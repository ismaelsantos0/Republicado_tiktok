import os
import time
import base64
import random
import json
from typing import Optional

import requests
from playwright.sync_api import sync_playwright, TimeoutError


PROFILE_URL = os.getenv("PROFILE_URL", "https://www.tiktok.com/@cb_oliveira_santos")

# Intervalo de checagem (segundos). Recomendo 12-25s pra ficar mais "humano".
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "15"))

# Headless True/False
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes", "y")

# Se você setar isso no Railway como secret (base64 do tiktok_state.json),
# o app recria o arquivo em runtime sem precisar comitar.
STORAGE_STATE_B64 = os.getenv("STORAGE_STATE_B64", "")

# Opcional: enviar POST quando detectar mudança
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # ex: https://seu-endpoint.com/hook

# Onde salvar o state no container
STATE_PATH = "tiktok_state.json"


def write_storage_state_from_env() -> bool:
    if not STORAGE_STATE_B64.strip():
        return False
    raw = base64.b64decode(STORAGE_STATE_B64.encode("utf-8"))
    with open(STATE_PATH, "wb") as f:
        f.write(raw)
    return True


def safe_post_webhook(payload: dict) -> None:
    if not WEBHOOK_URL.strip():
        return
    try:
        requests.post(
            WEBHOOK_URL,
            json=payload,
            timeout=15,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        print(f"[webhook] erro: {e}")


def click_reposts_tab(page) -> None:
    # "Republicações" como tab costuma ser estável
    page.get_by_role("tab", name="Republicações").click()
    page.wait_for_timeout(1200)


def find_first_video_href(page) -> Optional[str]:
    # Depois de clicar em Republicações, o primeiro card geralmente tem link /video/
    # Tentamos alguns seletores comuns e pegamos o primeiro href válido.
    selectors = [
        '[data-e2e="user-repost-item"] a[href*="/video/"]',
        '[data-e2e="user-post-item"] a[href*="/video/"]',
        'a[href*="/video/"]',
    ]

    for sel in selectors:
        loc = page.locator(sel)
        try:
            loc.first.wait_for(state="visible", timeout=6000)
            href = loc.first.get_attribute("href")
            if href and "/video/" in href:
                return href
        except TimeoutError:
            continue

    return None


def open_first_repost(page) -> None:
    # Abrir o primeiro card (mais à esquerda da primeira linha)
    loc = page.locator('a[href*="/video/"]').first
    loc.wait_for(state="visible", timeout=8000)
    loc.click()


def jitter_sleep(base_seconds: int) -> None:
    # adiciona variação pra parecer menos robótico
    jitter = random.randint(0, 6)
    time.sleep(base_seconds + jitter)


def main():
    wrote = write_storage_state_from_env()
    if wrote:
        print("[init] storage_state carregado do env.")
    else:
        print("[init] STORAGE_STATE_B64 vazio. Você precisa setar isso no Railway (recomendado).")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        # Se tiver state, usa. Se não tiver, abre sem e provavelmente vai bater em login/limitações.
        if os.path.exists(STATE_PATH):
            context = browser.new_context(storage_state=STATE_PATH)
        else:
            context = browser.new_context()

        page = context.new_page()

        print(f"[start] Abrindo perfil: {PROFILE_URL}")
        page.goto(PROFILE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        click_reposts_tab(page)

        last_first_href = find_first_video_href(page)
        print(f"[baseline] primeiro vídeo: {last_first_href}")

        while True:
            jitter_sleep(CHECK_EVERY_SECONDS)

            try:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                click_reposts_tab(page)

                first_href = find_first_video_href(page)
                print(f"[check] primeiro vídeo: {first_href}")

                if first_href and first_href != last_first_href:
                    print("[DETECT] Novo repost detectado! Abrindo primeiro card...")
                    open_first_repost(page)
                    page.wait_for_timeout(1500)

                    payload = {
                        "event": "new_repost_detected",
                        "profile_url": PROFILE_URL,
                        "first_video_href": first_href,
                        "ts": int(time.time()),
                    }
                    safe_post_webhook(payload)

                    last_first_href = first_href
                else:
                    print("[ok] Sem novidade.")

            except Exception as e:
                print(f"[err] {e}")
                # tenta recuperar
                try:
                    page.goto(PROFILE_URL, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    click_reposts_tab(page)
                except Exception as e2:
                    print(f"[recover_err] {e2}")

        # browser.close()


if __name__ == "__main__":
    main()
