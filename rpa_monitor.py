import asyncio
import random
import re
import time
import requests
import unicodedata
from difflib import SequenceMatcher
from playwright.async_api import async_playwright

# ==============================================================================
# SITES DISPONÍVEIS — Modo Detalhado (Playwright)
# Removidos: Shopee (captcha), Shein (captcha), Magazine Luiza (403), Mercado Livre (bloqueio total mesmo com delays)
# ==============================================================================

SITES_DISPONIVEIS = {
    "Amazon":         "https://www.amazon.com.br/s?k={query}",
    "Americanas":     "https://www.americanas.com.br/busca/{query}",
    "Google Shopping":"https://www.google.com/search?q={query}&tbm=shop",
    "AliExpress":     "https://www.aliexpress.com/wholesale?SearchText={query}",
}

SELETORES_POR_SITE = {
    "Amazon":         ["span.a-price-whole", "span.a-offscreen"],
    "Americanas":     ["span[class*='priceSales']", "div[class*='Price']"],
    "Google Shopping":["span.T14wmb", "span.a8Pemb"],
    "AliExpress":     ["span[class*='price-sale']", "div[class*='price']"],
}

_PERCENT_MAX = 9999.99
_PERCENT_MIN = -9999.99

# Indicadores de bloqueio REAIS — frases específicas, não palavras soltas
_BLOCK_KEYWORDS = [
    "captcha", "i am not a robot", "acesso negado", "acesso bloqueado",
    "access denied", "403 forbidden", "unusual traffic",
    "verify you are human", "bot detection", "please enable cookies",
]

# ==============================================================================
# FILTRO IQR + HELPERS
# ==============================================================================

def filtrar_precos_inteligente(valores: list) -> list:
    if not valores:
        return []
    if len(valores) <= 2:
        return valores
    valores_ord = sorted(valores)
    n  = len(valores_ord)
    q1 = valores_ord[n // 4]
    q3 = valores_ord[(3 * n) // 4]
    iqr = q3 - q1
    li  = q1 - 2.0 * iqr
    ls  = q3 + 2.0 * iqr
    filtrados = [v for v in valores_ord if li <= v <= ls]
    return filtrados if filtrados else valores_ord


def extrair_precos_html(texto_html: str) -> list:
    valores = []
    for m in re.findall(r'R\$\s*([\d]{1,3}(?:\.[\d]{3})*(?:,\d{2})?|\d+,\d{2})', texto_html):
        try:
            v = float(m.replace(".", "").replace(",", "."))
            if v > 0:
                valores.append(v)
        except ValueError:
            continue
    return valores


def _parsear_preco_br(price_str: str) -> float | None:
    if not price_str:
        return None
    try:
        s = str(price_str).replace("R$","").replace("\xa0","").replace(" ","").strip()
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            partes = s.split(",")
            s = s.replace(",", ".") if len(partes)==2 and len(partes[1])<=2 else s.replace(",","")
        v = float(s)
        return v if v > 0 else None
    except (ValueError, AttributeError):
        return None


def _mediana(valores: list) -> float:
    valores.sort()
    return valores[len(valores) // 2]


# ==============================================================================
# EXTRAÇÃO INTELIGENTE: pares (título, preço) + filtro por relevância
#
# Abordagem de engenharia:
# Em vez de coletar TODOS os preços da página (frete, relacionados, anúncios),
# extraímos pares estruturados (título do produto, preço) de cada card de busca.
# Depois calculamos a similaridade entre o título extraído e a query de busca.
# Apenas preços de produtos suficientemente similares à query são considerados.
# Isso elimina falsos positivos sem depender de thresholds arbitrários de valor.
# ==============================================================================

_VARIANTES_MODELO = {
    "pro",
    "max",
    "plus",
    "ultra",
    "mini",
    "air",
    "lite",
    "fe",
}


def _normalizar_texto_produto(texto: str) -> str:
    texto = str(texto).lower()

    # Remove acentos
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    # Normalizações equivalentes
    texto = texto.replace("+", " plus ")
    texto = texto.replace("-", " ")

    # Português / inglês
    texto = re.sub(r"\bsem\s+fio\b", "wireless", texto)
    texto = re.sub(r"\bcom\s+fio\b", "wired", texto)
    texto = re.sub(r"\bwi\s+fi\b", "wifi", texto)

    # 256 GB → 256gb
    # 1 TB → 1tb
    texto = re.sub(r"(\d+)\s*(gb|tb)\b", r"\1\2", texto)

    # Remove pontuação restante
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def _identificador_presente(
    identificador: str,
    palavras_titulo: set[str],
) -> bool:
    if identificador in palavras_titulo:
        return True

    # Permite casos como KB500 → KB500BR
    if len(identificador) >= 4:
        return any(
            identificador in palavra
            for palavra in palavras_titulo
        )

    return False


def _match_estrutural(titulo: str, query: str) -> bool:
    titulo_norm = _normalizar_texto_produto(titulo)
    query_norm = _normalizar_texto_produto(query)

    palavras_titulo = set(titulo_norm.split())
    palavras_query = set(query_norm.split())

    # Exige números/modelos presentes na busca
    identificadores_query = {
        palavra
        for palavra in palavras_query
        if any(caractere.isdigit() for caractere in palavra)
    }

    for identificador in identificadores_query:
        if not _identificador_presente(
            identificador,
            palavras_titulo,
        ):
            return False

    # Exige a mesma variante do produto
    variantes_query = palavras_query & _VARIANTES_MODELO
    variantes_titulo = palavras_titulo & _VARIANTES_MODELO

    if variantes_query != variantes_titulo:
        return False

    # Evita wireless ↔ wired
    if "wireless" in palavras_query and "wired" in palavras_titulo:
        return False

    if "wired" in palavras_query and "wireless" in palavras_titulo:
        return False

    # Capacidade de armazenamento
    # Ex.: busca 128GB não aceita anúncio "128GB / 256GB / 512GB"
    capacidades_query = {
        palavra
        for palavra in palavras_query
        if re.fullmatch(r"\d+(gb|tb)", palavra)
    }

    capacidades_titulo = {
        palavra
        for palavra in palavras_titulo
        if re.fullmatch(r"\d+(gb|tb)", palavra)
    }

    if capacidades_query:
        # Ignora capacidades muito pequenas que provavelmente são RAM
        capacidades_titulo_armazenamento = {
            capacidade
            for capacidade in capacidades_titulo
            if capacidade.endswith("tb")
            or int(capacidade.removesuffix("gb")) >= 64
        }

        if capacidades_titulo_armazenamento != capacidades_query:
            return False

    return True


def _similaridade_query(titulo: str, query: str) -> float:
    titulo_norm = _normalizar_texto_produto(titulo)
    query_norm = _normalizar_texto_produto(query)

    # Primeiro verifica modelo/variante.
    if not _match_estrutural(titulo_norm, query_norm):
        return 0.0

    # Similaridade geral do texto
    ratio = SequenceMatcher(
        None,
        titulo_norm,
        query_norm,
    ).ratio()

    palavras_query = set(query_norm.split())
    palavras_titulo = set(titulo_norm.split())

    if palavras_query:
        cobertura = (
            len(palavras_query & palavras_titulo)
            / len(palavras_query)
        )
    else:
        cobertura = 0.0

    return max(ratio, cobertura * 0.95)


def _produto_nao_novo(titulo: str) -> bool:
    titulo_norm = _normalizar_texto_produto(titulo)

    termos_nao_novos = {
        "usado",
        "seminovo",
        "semi novo",
        "recondicionado",
        "refurbished",
        "renewed",
        "open box",
        "caixa aberta",
        "como novo",
        "vitrine",
    }

    if any(termo in titulo_norm for termo in termos_nao_novos):
        return True

    # Ex.: "bateria 99%" geralmente indica aparelho usado
    if re.search(r"\bbateria\s*\d{2,3}\s*%", titulo_norm):
        return True

    return False


def _filtrar_precos_por_relevancia(
    pares: list[tuple[str, float]],
    query: str,
    min_sim: float = 0.28,
) -> list[float]:
    if not pares:
        return []

    scored = []

    for titulo, preco in pares:
        if not preco or preco <= 0:
            continue

        # Ignora usados, seminovos e recondicionados
        if _produto_nao_novo(titulo):
            print(f"    [DESCARTADO — não novo] {titulo[:60]!r}")
            continue

        sim = _similaridade_query(titulo, query)
        scored.append((sim, preco))

        print(
            f"    [{sim:.2f}] {titulo[:60]!r} "
            f"→ R$ {preco:.2f}"
        )

    if not scored:
        return []

    best_sim = max(sim for sim, _ in scored)

    if best_sim < min_sim:
        print(
            f"  ⚠️ Melhor similaridade ({best_sim:.2f}) "
            f"abaixo do limiar ({min_sim}). Descartando."
        )
        return []

    threshold = max(min_sim, best_sim * 0.50)

    relevantes = [
        preco
        for sim, preco in scored
        if sim >= threshold
    ]

    print(
        f"  → {len(relevantes)}/{len(scored)} preços "
        f"após filtro de relevância "
        f"(threshold={threshold:.2f})"
    )

    return relevantes

# ==============================================================================
# EXTRAÇÃO DE PARES (TÍTULO, PREÇO) POR SITE VIA JAVASCRIPT
# ==============================================================================

# Scripts JS por site — cada um extrai cards de produto com título e preço juntos.
# Usar JS evaluate é mais confiável que query_selector_all para estruturas aninhadas
# e retorna dados estruturados diretamente, sem precisar de múltiplos awaits.
_JS_EXTRATORES = {
    "Mercado Livre": """
    () => {
        const cards = document.querySelectorAll('li.ui-search-layout__item, .poly-card');
        return Array.from(cards).slice(0, 20).map(card => {
            const tEl = card.querySelector(
                'h2.ui-search-item__title, .poly-component__title, h2[class*="title"]');
            const pEl = card.querySelector(
                'span.andes-money-amount__fraction, .price-tag-fraction');
            return { title: tEl ? tEl.innerText.trim() : '',
                     price: pEl ? pEl.innerText.trim() : '' };
        }).filter(r => r.title && r.price);
    }
    """,
    "Amazon": """
    () => {
        const cards = document.querySelectorAll('div[data-component-type="s-search-result"]');
        return Array.from(cards).slice(0, 20).map(card => {
            const tEl = card.querySelector('h2 span.a-size-base-plus, h2 span.a-size-medium, h2 span');
            const pEl = card.querySelector('span.a-price-whole');
            const pEl2 = card.querySelector('span.a-offscreen');
            return { title: tEl ? tEl.innerText.trim() : '',
                     price: pEl ? pEl.innerText.trim() : (pEl2 ? pEl2.innerText.trim() : '') };
        }).filter(r => r.title && r.price);
    }
    """,
    "Americanas": """
    () => {
        const cards = document.querySelectorAll(
            '[data-testid="product-card"], [class*="ProductCard"], [class*="product-card"], li[class*="item"]');
        return Array.from(cards).slice(0, 20).map(card => {
            const tEl = card.querySelector('h2, h3, [class*="Title"], [class*="Name"], [class*="title"]');
            const pEl = card.querySelector('[class*="Price"], [class*="price"], [class*="valor"]');
            return { title: tEl ? tEl.innerText.trim() : '',
                     price: pEl ? pEl.innerText.trim() : '' };
        }).filter(r => r.title && r.price);
    }
    """,
    "Google Shopping": """
    () => {
        const cards = document.querySelectorAll('.sh-dgr__grid-result, .g, [data-hveid]');
        return Array.from(cards).slice(0, 20).map(card => {
            const tEl = card.querySelector('h4, h3, .Xjkr3b, .sh-np__click-target, [aria-label]');
            const pEl = card.querySelector('.T14wmb, span[aria-label*="R$"], .HRLmOf');
            return { title: tEl ? tEl.innerText.trim() : '',
                     price: pEl ? pEl.innerText.trim() : '' };
        }).filter(r => r.title && r.price);
    }
    """,
    "AliExpress": """
    () => {
        const cards = document.querySelectorAll('[class*="product-card"], [class*="list--gallery"]>div');
        return Array.from(cards).slice(0, 20).map(card => {
            const tEl = card.querySelector('[class*="title"], [class*="Title"]');
            const pEl = card.querySelector('[class*="price-sale"], [class*="Price"]');
            return { title: tEl ? tEl.innerText.trim() : '',
                     price: pEl ? pEl.innerText.trim() : '' };
        }).filter(r => r.title && r.price);
    }
    """,
}


async def _extrair_pares_js(page, site: str) -> list[tuple[str, float]]:
    """
    Executa o extrator JS do site e retorna lista de (título, preço).
    Parsing do preço usa _parsear_preco_br para lidar com formatos brasileiros.
    """
    script = _JS_EXTRATORES.get(site)
    if not script:
        return []

    try:
        results = await page.evaluate(script)
        pares = []
        for r in results:
            titulo    = (r.get("title") or "").strip()
            price_str = (r.get("price") or "").strip()
            if titulo and price_str:
                preco = _parsear_preco_br(price_str)
                if preco and preco > 0:
                    pares.append((titulo, preco))
        return pares
    except Exception as e:
        print(f"  [JS Extract] Erro em {site}: {e}")
        return []


# ==============================================================================
# MODO RÁPIDO — SerpAPI
# ==============================================================================

def _buscar_preco_serpapi(nome_produto: str, api_key: str) -> tuple[float | None, str]:
    """Google Shopping via SerpAPI (gl=br, hl=pt). Retorna (preco, razao)."""
    try:
        params = {
            "engine":  "google_shopping",
            "q":       nome_produto,
            "gl":      "br",
            "hl":      "pt",
            "api_key": api_key,
            "num":     "10",
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)

        if resp.status_code == 401:
            print("[SerpAPI] ❌ Chave inválida.")
            return None, "🚫 Bloqueado"
        if resp.status_code == 429:
            print("[SerpAPI] ⚠️  Limite de requisições atingido.")
            return None, "🚫 Bloqueado"
        if resp.status_code != 200:
            print(f"[SerpAPI] HTTP {resp.status_code}")
            return None, "⚪ Não encontrado"

        data = resp.json()
        if "error" in data:
            print(f"[SerpAPI] Erro API: {data['error']}")
            return None, "⚪ Não encontrado"

        shopping = data.get("shopping_results") or data.get("inline_shopping_results") or []
        if not shopping:
            print(f"[SerpAPI] Sem resultados para '{nome_produto}'")
            return None, "⚪ Não encontrado"

        # SerpAPI já retorna resultados relacionados à query — aplicar relevância também
        pares = []
        for item in shopping:
            titulo = item.get("title", "")
            p = item.get("extracted_price")
            if p and isinstance(p, (int, float)) and p > 0:
                pares.append((titulo, float(p)))
                continue
            p2 = _parsear_preco_br(item.get("price", ""))
            if p2:
                pares.append((titulo, p2))

        print(f"[SerpAPI] '{nome_produto}' → {len(pares)} pares título/preço")

                # Filtra por relevância
        valores = _filtrar_precos_por_relevancia(pares, nome_produto)

        if not valores:
            print(
                f"[SerpAPI] Nenhum resultado compatível com '{nome_produto}'"
            )
            return None, "⚪ Não encontrado"

        valores = filtrar_precos_inteligente(valores)
        if not valores:
            return None, "⚪ Não encontrado"

        resultado = _mediana(valores)
        print(
            f"[SerpAPI] '{nome_produto}' → mediana R$ {resultado:.2f} "
            f"(de {sorted(valores)[:5]})"
        )
        return resultado, "ok"

    except Exception as e:
        print(f"[SerpAPI ERRO] '{nome_produto}': {e}")
        return None, "⚪ Não encontrado"


def testar_serpapi(api_key: str, produto: str = "Logitech MX Master 3S") -> dict:
    """Diagnóstico: testa SerpAPI e retorna resultado bruto."""
    try:
        params = {"engine":"google_shopping","q":produto,"gl":"br","hl":"pt",
                  "api_key":api_key,"num":"5"}
        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = resp.json()
        return {
            "status_http":      resp.status_code,
            "erro_api":         data.get("error"),
            "total_resultados": len(data.get("shopping_results", [])),
            "primeiro_item":    (data.get("shopping_results") or [{}])[0],
            "chaves_resposta":  list(data.keys()),
        }
    except Exception as e:
        return {"erro_exception": str(e)}


def analisar_rapido(produtos: list, margem_minima: float, callback,
                    serpapi_key: str | None = None) -> list:
    """Modo Rápido: usa exclusivamente SerpAPI (Google Shopping Brasil)."""
    resultados = []
    total = len(produtos)

    for i, prod in enumerate(produtos):
        modelo = prod.get("modelo", "")
        nome   = f"{prod['marca']} {modelo}" if modelo else f"{prod['marca']} {prod['tipo']}"
        callback(i + 1, total, nome)

        if serpapi_key:
            preco, razao = _buscar_preco_serpapi(nome, serpapi_key)
            if preco:
                print(f"  ✅ [{nome}] SerpAPI → R$ {preco:.2f}")
            else:
                print(f"  ❌ [{nome}] SerpAPI: {razao}")
        else:
            preco, razao = None, "⚪ Não encontrado"
            print(f"  ❌ [{nome}] SerpAPI não configurada")

        if i < total - 1:
            time.sleep(1.0)

        metricas = _calcular_metricas(
            float(prod["preco_unitario"]), float(prod["custo"]),
            preco, margem_minima, razao=razao
        )
        resultados.append({
            "codigo":            prod["codigo"],
            "nome":              nome,
            "seu_preco":         float(prod["preco_unitario"]),
            "preco_mercado":     metricas["preco_mercado"],
            "diferenca_percent": metricas["diferenca_percent"],
            "margem_percent":    metricas["margem_percent"],
            "status":            metricas["status"],
        })
    return resultados


# ==============================================================================
# MODO DETALHADO — Playwright com extração inteligente de pares
# ==============================================================================

async def _scroll_humano(page):
    """Scroll lento e irregular — simula leitura humana da página."""
    passos = random.randint(5, 10)
    for _ in range(passos):
        await page.mouse.wheel(0, random.randint(150, 450))
        await page.wait_for_timeout(random.randint(600, 1800))
    await page.mouse.wheel(0, -random.randint(100, 300))
    await page.wait_for_timeout(random.randint(800, 1500))


async def _mover_mouse_curva(page):
    """Movimento de mouse com trajetória irregular e pausas."""
    for _ in range(random.randint(5, 9)):
        await page.mouse.move(
            random.randint(100, 1200),
            random.randint(100, 650),
            steps=random.randint(8, 20),
        )
        await page.wait_for_timeout(random.randint(300, 900))


async def _buscar_preco_site(page, nome_produto: str, site: str) -> tuple[float | None, str]:
    """
    Extrai o preço de mercado para nome_produto no site especificado.

    Estratégia (em ordem de prioridade):
      1. JS extrator: obtém pares (título, preço) estruturados dos cards de produto
         → filtra por similaridade com a query → mais preciso, sem falsos positivos
      2. CSS seletores + HTML regex: fallback quando JS não retorna pares suficientes
         → aplica IQR para remover outliers

    Retorna (preco, razao) onde razao é "ok", "🚫 Bloqueado", "⚪ Não encontrado",
    "⚠️ Timeout" ou "⚠️ Erro".
    """
    try:
        url  = SITES_DISPONIVEIS[site].replace("{query}", nome_produto.replace(" ", "+"))
        resp = await page.goto(url, timeout=30000, wait_until="domcontentloaded")

        status_code = resp.status if resp else 0
        if status_code in (403, 429, 503):
            print(f"[Playwright] {site} retornou HTTP {status_code} para '{nome_produto}'")
            return None, "🚫 Bloqueado"

        # Aguarda JS + simula comportamento humano
        await page.wait_for_timeout(random.randint(5000, 9000))
        await _scroll_humano(page)
        await _mover_mouse_curva(page)
        await page.wait_for_timeout(random.randint(3000, 6000))

        html = await page.content()
        if any(kw in html.lower() for kw in _BLOCK_KEYWORDS):
            print(f"[Playwright] Bloqueio detectado no conteúdo para '{nome_produto}'")
            return None, "🚫 Bloqueado"

        # ── Estratégia 1: JS extrator de pares (título, preço) ──────────────
        print(f"[Playwright/{site}] Extraindo pares JS para '{nome_produto}'")
        pares = await _extrair_pares_js(page, site)

        if pares:
            valores = _filtrar_precos_por_relevancia(pares, nome_produto)
            if valores:
                valores = filtrar_precos_inteligente(valores)
                if valores:
                    resultado = _mediana(valores)
                    print(f"  ✅ [JS+Relevância] '{nome_produto}' → R$ {resultado:.2f}")
                    return resultado, "ok"

        # ── Estratégia 2: fallback CSS seletores ────────────────────────────
        print("  ⚠️  JS sem resultados → tentando CSS seletores")
        valores_css = []
        for sel in SELETORES_POR_SITE.get(site, []):
            for el in (await page.query_selector_all(sel))[:15]:
                try:
                    texto = await el.inner_text()
                    v = float(texto.replace("R$","").replace(".","").replace(",",".").strip())
                    if v > 0:
                        valores_css.append(v)
                except Exception:
                    continue
            if valores_css:
                break

        # ── Estratégia 3: regex no HTML completo ────────────────────────────
        if not valores_css:
            valores_css = extrair_precos_html(html)

        valores_css = filtrar_precos_inteligente(valores_css)
        if valores_css:
            resultado = _mediana(valores_css)
            print(f"  ⚠️  [Fallback CSS] '{nome_produto}' → R$ {resultado:.2f} (pode ser impreciso)")
            return resultado, "ok"

        return None, "⚪ Não encontrado"

    except TimeoutError:
        print(f"[Playwright] Timeout para '{nome_produto}' em {site}")
        return None, "⚠️ Timeout"
    except Exception as e:
        print(f"[Playwright ERRO] '{nome_produto}': {e}")
        return None, "⚠️ Erro"


async def _executar_sessao(produtos, margem_minima, site, callback):
    resultados = []
    async with async_playwright() as p:
        async def criar_browser():
            browser = await p.chromium.launch(headless=False, args=["--incognito"])
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="pt-BR", timezone_id="America/Sao_Paulo",
            )
            return browser, ctx, await ctx.new_page()

        browser, ctx, page = await criar_browser()
        for i, prod in enumerate(produtos):
            modelo = prod.get("modelo", "")
            nome   = f"{prod['marca']} {modelo}" if modelo else f"{prod['marca']} {prod['tipo']}"
            callback(i + 1, len(produtos), nome)
            await page.wait_for_timeout(random.randint(18000, 32000))

            try:
                preco, razao = await _buscar_preco_site(page, nome, site)
            except Exception:
                try:
                    await browser.close()
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(6, 12))
                browser, ctx, page = await criar_browser()
                preco, razao = None, "⚠️ Erro"

            metricas = _calcular_metricas(
                float(prod["preco_unitario"]), float(prod["custo"]),
                preco, margem_minima, razao=razao
            )
            resultados.append({
                "codigo":            prod["codigo"],
                "nome":              nome,
                "seu_preco":         float(prod["preco_unitario"]),
                "preco_mercado":     metricas["preco_mercado"],
                "diferenca_percent": metricas["diferenca_percent"],
                "margem_percent":    metricas["margem_percent"],
                "status":            metricas["status"],
            })
            await page.wait_for_timeout(random.randint(8000, 16000))

        try:
            await browser.close()
        except Exception:
            pass
    return resultados


def analisar_detalhado_sessoes(produtos, margem_minima, site,
                                callback_progresso, callback_espera):
    TAMANHO, PAUSA = 5, 120   # 5 itens/sessão; 2 min entre sessões
    sessoes = [produtos[i:i+TAMANHO] for i in range(0, len(produtos), TAMANHO)]
    todos   = []
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    for idx, sessao in enumerate(sessoes):
        sn = idx + 1
        def cb(a, t, n, s=sn, ts=len(sessoes)):
            callback_progresso(a, t, n, s, ts)
        todos.extend(loop.run_until_complete(
            _executar_sessao(sessao, margem_minima, site, cb)))
        if sn < len(sessoes):
            for seg in range(PAUSA, 0, -1):
                callback_espera(sn, len(sessoes), seg)
                time.sleep(1)
    return todos


# ==============================================================================
# MÉTRICAS
# ==============================================================================

def _clamp_percent(v):
    return max(_PERCENT_MIN, min(_PERCENT_MAX, v))


def _calcular_metricas(seu_preco, custo, preco_mercado, margem_minima, razao: str = ""):
    margem = _clamp_percent(
        (seu_preco - custo) / seu_preco * 100 if seu_preco > 0 else 0.0)

    if preco_mercado and preco_mercado > 0:
        diferenca = _clamp_percent((seu_preco - preco_mercado) / preco_mercado * 100)
        if margem < 15 or diferenca > 20:
            status = "🔴 Crítico"
        elif diferenca > 5 or margem < margem_minima:
            status = "⚠️ Moderado"
        else:
            status = "✅ OK"
    else:
        diferenca = 0.0
        status = "🚫 Erro" if ("Bloqueado" in razao or razao.startswith("⚠️")) else "⚪ Sem referência"

    return {
        "diferenca_percent": round(diferenca, 2),
        "margem_percent":    round(margem, 2),
        "status":            status,
        "preco_mercado":     preco_mercado,
    }