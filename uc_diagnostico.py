"""
=============================================================
  UNIVERSO CRIATIVO — COLETA DE DADOS PARA DIAGNÓSTICO
  Versão: local (rodar no PC) e API (Railway)
  
  Coleta dados reais de:
  - Instagram (perfil público)
  - Google Meu Negócio (Places API)
  - YouTube (Data API)
  - TikTok (dados públicos limitados)
  - Site (análise básica)
=============================================================

DEPENDÊNCIAS:
    pip install requests beautifulsoup4 flask

USO LOCAL:
    python uc_diagnostico.py --empresa "Clínica X" --instagram clinicax --cidade "Porto Velho"

USO COMO API (Railway):
    A função app.run() no final sobe um servidor web.
    O n8n chama via POST em /coletar
"""

import requests
import re
import time
import json
import argparse
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# =============================================================
# CONFIGURAÇÕES
# =============================================================

GOOGLE_PLACES_API_KEY = "SUA_CHAVE_AQUI"  # mesma chave do projeto de prospecção

# User-agent para scraping (simula um navegador real)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# =============================================================
# UTILITÁRIOS
# =============================================================

def normalizar_arroba(valor):
    """Remove @ se presente e espaços extras. Retorna só o username."""
    if not valor:
        return ""
    return valor.strip().lstrip("@").strip()


def safe_get(url, params=None, timeout=10):
    """Faz GET com tratamento de erro."""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        return None


# =============================================================
# INSTAGRAM
# =============================================================

def coletar_instagram(username):
    """
    Coleta dados públicos do perfil do Instagram.
    Funciona para perfis públicos (comerciais ou pessoais).
    """
    if not username:
        return {"disponivel": False, "motivo": "Username não informado"}

    username = normalizar_arroba(username)
    url = f"https://www.instagram.com/{username}/"

    resultado = {
        "disponivel": False,
        "username": username,
        "url": url,
        "seguidores": None,
        "seguindo": None,
        "total_posts": None,
        "nome_exibicao": None,
        "bio": None,
        "tem_link_bio": False,
        "verificado": False,
        "categoria": None,
        "observacoes": []
    }

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if resp.status_code == 404:
            resultado["motivo"] = "Perfil não encontrado"
            return resultado

        if resp.status_code != 200:
            resultado["motivo"] = f"Erro HTTP {resp.status_code}"
            return resultado

        html = resp.text

        # Extrai dados do JSON embutido na página
        # Instagram embute dados no formato window._sharedData ou scripts JSON-LD
        
        # Tenta extrair contagens via meta tags e scripts
        # Seguidores via og:description (ex: "1.234 Followers, 567 Following, 89 Posts")
        og_desc = re.search(r'<meta property="og:description" content="([^"]*)"', html)
        if og_desc:
            desc = og_desc.group(1)
            
            seg_match = re.search(r'([\d,\.]+)\s*Followers?', desc, re.IGNORECASE)
            if seg_match:
                resultado["seguidores"] = seg_match.group(1)
            
            seg_match2 = re.search(r'([\d,\.]+)\s*Following', desc, re.IGNORECASE)
            if seg_match2:
                resultado["seguindo"] = seg_match2.group(1)

            posts_match = re.search(r'([\d,\.]+)\s*Posts?', desc, re.IGNORECASE)
            if posts_match:
                resultado["total_posts"] = posts_match.group(1)

        # Nome de exibição
        og_title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        if og_title:
            resultado["nome_exibicao"] = og_title.group(1).replace(" • Instagram", "").strip()

        # Verifica se encontrou dados mínimos
        if resultado["seguidores"] or resultado["nome_exibicao"]:
            resultado["disponivel"] = True

            # Análise básica de posicionamento
            if resultado["seguidores"]:
                seg_str = resultado["seguidores"].replace(",", "").replace(".", "")
                try:
                    seg_num = int(seg_str)
                    if seg_num < 500:
                        resultado["observacoes"].append("Perfil com poucos seguidores — grande potencial de crescimento")
                    elif seg_num < 2000:
                        resultado["observacoes"].append("Base de seguidores em construção")
                    elif seg_num < 10000:
                        resultado["observacoes"].append("Perfil com engajamento local relevante")
                    else:
                        resultado["observacoes"].append("Perfil com boa base de seguidores")
                except:
                    pass

            if resultado["total_posts"]:
                posts_str = resultado["total_posts"].replace(",", "").replace(".", "")
                try:
                    posts_num = int(posts_str)
                    if posts_num < 10:
                        resultado["observacoes"].append("Pouquíssimas publicações — perfil pouco ativo")
                    elif posts_num < 30:
                        resultado["observacoes"].append("Baixo volume de publicações")
                except:
                    pass
        else:
            resultado["motivo"] = "Instagram pode ter bloqueado a requisição ou perfil privado"
            resultado["observacoes"].append("Verificar manualmente: " + url)

    except Exception as e:
        resultado["motivo"] = f"Erro na coleta: {str(e)}"

    return resultado


# =============================================================
# GOOGLE MEU NEGÓCIO (Places API)
# =============================================================

def coletar_google_meu_negocio(nome_empresa, cidade):
    """
    Busca dados do Google Meu Negócio via Places API.
    Usa nome da empresa + cidade para localizar o perfil correto.
    """
    if not nome_empresa:
        return {"disponivel": False, "motivo": "Nome da empresa não informado"}

    resultado = {
        "disponivel": False,
        "nome": None,
        "endereco": None,
        "telefone": None,
        "site": None,
        "nota": None,
        "total_avaliacoes": None,
        "categorias": [],
        "tem_fotos": False,
        "horario_funcionamento": None,
        "observacoes": []
    }

    # Busca pelo nome + cidade
    query = f"{nome_empresa} {cidade}"
    url_search = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params_search = {
        "query": query,
        "key": GOOGLE_PLACES_API_KEY,
        "language": "pt-BR",
        "region": "br",
    }

    resp = safe_get(url_search, params=params_search)
    if not resp:
        resultado["motivo"] = "Erro ao conectar com Google Places API"
        return resultado

    data = resp.json()
    results = data.get("results", [])

    if not results:
        resultado["motivo"] = "Empresa não encontrada no Google Meu Negócio"
        resultado["observacoes"].append("Empresa sem perfil no Google — oportunidade de configuração")
        return resultado

    # Pega o primeiro resultado (mais relevante)
    place = results[0]
    place_id = place.get("place_id")

    # Busca detalhes completos
    url_details = "https://maps.googleapis.com/maps/api/place/details/json"
    params_details = {
        "place_id": place_id,
        "key": GOOGLE_PLACES_API_KEY,
        "language": "pt-BR",
        "fields": "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,photos,opening_hours,types,editorial_summary",
    }

    resp_details = safe_get(url_details, params=params_details)
    if not resp_details:
        resultado["motivo"] = "Erro ao buscar detalhes do lugar"
        return resultado

    det = resp_details.json().get("result", {})

    resultado["disponivel"] = True
    resultado["nome"] = det.get("name")
    resultado["endereco"] = det.get("formatted_address")
    resultado["telefone"] = det.get("formatted_phone_number")
    resultado["site"] = det.get("website")
    resultado["nota"] = det.get("rating")
    resultado["total_avaliacoes"] = det.get("user_ratings_total", 0)
    resultado["tem_fotos"] = bool(det.get("photos"))
    resultado["categorias"] = det.get("types", [])

    if det.get("opening_hours"):
        resultado["horario_funcionamento"] = det["opening_hours"].get("weekday_text", [])

    # Análise de posicionamento
    nota = resultado["nota"] or 0
    avaliacoes = resultado["total_avaliacoes"] or 0

    if avaliacoes == 0:
        resultado["observacoes"].append("Sem avaliações no Google — ponto crítico a trabalhar")
    elif avaliacoes < 10:
        resultado["observacoes"].append(f"Apenas {avaliacoes} avaliações — base muito pequena")
    elif avaliacoes < 50:
        resultado["observacoes"].append(f"{avaliacoes} avaliações — crescimento possível com estratégia")
    else:
        resultado["observacoes"].append(f"{avaliacoes} avaliações — boa presença no Google")

    if nota > 0:
        if nota < 3.5:
            resultado["observacoes"].append(f"Nota {nota} — reputação comprometida, necessita ação urgente")
        elif nota < 4.0:
            resultado["observacoes"].append(f"Nota {nota} — abaixo da média, espaço para melhoria")
        elif nota < 4.5:
            resultado["observacoes"].append(f"Nota {nota} — boa reputação")
        else:
            resultado["observacoes"].append(f"Nota {nota} — excelente reputação no Google")

    if not resultado["site"]:
        resultado["observacoes"].append("Sem site cadastrado no Google Meu Negócio")

    if not resultado["tem_fotos"]:
        resultado["observacoes"].append("Sem fotos no perfil — prejudica conversão")

    return resultado


# =============================================================
# YOUTUBE
# =============================================================

def coletar_youtube(nome_empresa, cidade=""):
    """
    Busca canal do YouTube da empresa via scraping público.
    """
    if not nome_empresa:
        return {"disponivel": False, "motivo": "Nome não informado"}

    resultado = {
        "disponivel": False,
        "nome_canal": None,
        "url_canal": None,
        "inscricoes": None,
        "total_videos": None,
        "observacoes": []
    }

    # Busca no Google pelo canal
    query = f"{nome_empresa} {cidade} site:youtube.com/channel OR site:youtube.com/@"
    url = f"https://www.google.com/search?q={requests.utils.quote(nome_empresa + ' ' + cidade + ' canal youtube')}"

    resp = safe_get(url)
    if not resp:
        resultado["motivo"] = "Não foi possível buscar canal"
        return resultado

    soup = BeautifulSoup(resp.text, "html.parser")

    # Procura links do YouTube nos resultados
    youtube_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "youtube.com/@" in href or "youtube.com/channel/" in href or "youtube.com/c/" in href:
            # Limpa o href (Google adiciona parâmetros)
            match = re.search(r'(https?://(?:www\.)?youtube\.com/(?:@|channel/|c/)[^&\s"]+)', href)
            if match:
                youtube_url = match.group(1)
                break

    if not youtube_url:
        resultado["motivo"] = "Canal do YouTube não encontrado"
        resultado["observacoes"].append("Empresa sem canal no YouTube identificado — oportunidade")
        return resultado

    resultado["url_canal"] = youtube_url
    resultado["disponivel"] = True

    # Busca dados do canal
    resp_canal = safe_get(youtube_url)
    if resp_canal:
        html = resp_canal.text

        # Nome do canal
        title_match = re.search(r'"channelMetadataRenderer":\{"title":"([^"]+)"', html)
        if title_match:
            resultado["nome_canal"] = title_match.group(1)

        # Inscritos (YouTube não mostra número exato sempre)
        subs_match = re.search(r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"', html)
        if subs_match:
            resultado["inscricoes"] = subs_match.group(1)

        # Vídeos
        videos_match = re.search(r'"videoCountText":\{"runs":\[\{"text":"([^"]+)"', html)
        if videos_match:
            resultado["total_videos"] = videos_match.group(1)

        if not resultado["inscricoes"]:
            resultado["observacoes"].append("Canal encontrado — dados de inscritos não públicos, verificar manualmente")

    return resultado


# =============================================================
# TIKTOK
# =============================================================

def coletar_tiktok(username):
    """
    Coleta dados públicos do TikTok.
    Nota: TikTok tem proteções anti-scraping fortes.
    Retorna o que for possível extrair.
    """
    if not username:
        return {"disponivel": False, "motivo": "Username não informado"}

    username = normalizar_arroba(username)
    url = f"https://www.tiktok.com/@{username}"

    resultado = {
        "disponivel": False,
        "username": username,
        "url": url,
        "seguidores": None,
        "curtidas": None,
        "total_videos": None,
        "observacoes": ["TikTok tem restrições anti-scraping — verificar manualmente: " + url]
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)

        if resp.status_code == 200:
            html = resp.text

            # Tenta extrair via JSON embutido
            json_match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>', html)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    # Navega pela estrutura do TikTok
                    user_data = (data
                        .get("__DEFAULT_SCOPE__", {})
                        .get("webapp.user-detail", {})
                        .get("userInfo", {})
                    )
                    
                    stats = user_data.get("stats", {})
                    user = user_data.get("user", {})

                    if stats:
                        resultado["disponivel"] = True
                        resultado["seguidores"] = stats.get("followerCount")
                        resultado["curtidas"] = stats.get("heartCount")
                        resultado["total_videos"] = stats.get("videoCount")
                        resultado["observacoes"] = []

                        seg = resultado["seguidores"] or 0
                        if seg < 500:
                            resultado["observacoes"].append("Perfil TikTok com poucos seguidores")
                        elif seg > 10000:
                            resultado["observacoes"].append("Boa presença no TikTok")
                except:
                    pass

            if not resultado["disponivel"]:
                resultado["motivo"] = "Perfil não encontrado ou bloqueado pelo TikTok"

    except Exception as e:
        resultado["motivo"] = f"Erro: {str(e)}"

    return resultado


# =============================================================
# SITE
# =============================================================

def coletar_site(url_site):
    """
    Analisa o site da empresa — presença de elementos básicos de conversão.
    """
    if not url_site:
        return {"disponivel": False, "motivo": "URL não informada"}

    # Garante que tem http
    if not url_site.startswith("http"):
        url_site = "https://" + url_site

    resultado = {
        "disponivel": False,
        "url": url_site,
        "carregou": False,
        "tem_ssl": url_site.startswith("https"),
        "tem_whatsapp": False,
        "tem_formulario": False,
        "tem_pixel_meta": False,
        "tem_google_analytics": False,
        "tem_gtag": False,
        "titulo": None,
        "descricao": None,
        "observacoes": []
    }

    try:
        resp = requests.get(url_site, headers=HEADERS, timeout=15, allow_redirects=True)

        if resp.status_code == 200:
            resultado["disponivel"] = True
            resultado["carregou"] = True
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Título e descrição
            if soup.title:
                resultado["titulo"] = soup.title.string

            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                resultado["descricao"] = meta_desc.get("content", "")

            # WhatsApp
            resultado["tem_whatsapp"] = bool(
                re.search(r'wa\.me|whatsapp\.com|api\.whatsapp', html, re.IGNORECASE)
            )

            # Formulário de contato
            resultado["tem_formulario"] = bool(soup.find("form"))

            # Pixel Meta (Facebook)
            resultado["tem_pixel_meta"] = bool(
                re.search(r'fbq\(|facebook\.net/en_US/fbevents|connect\.facebook\.net', html)
            )

            # Google Analytics / GTM
            resultado["tem_google_analytics"] = bool(
                re.search(r'google-analytics\.com|ga\.js|analytics\.js|gtag', html)
            )
            resultado["tem_gtag"] = bool(re.search(r'gtag\(', html))

            # SSL
            if not resultado["tem_ssl"]:
                resultado["observacoes"].append("Site sem SSL (https) — prejudica SEO e confiança")

            if not resultado["tem_whatsapp"]:
                resultado["observacoes"].append("Sem botão de WhatsApp — perda de conversão")

            if not resultado["tem_pixel_meta"]:
                resultado["observacoes"].append("Sem Pixel Meta instalado — impossível fazer remarketing")

            if not resultado["tem_google_analytics"]:
                resultado["observacoes"].append("Sem Google Analytics — sem dados de tráfego")

            if not resultado["tem_formulario"]:
                resultado["observacoes"].append("Sem formulário de captura identificado")

            if not resultado["observacoes"]:
                resultado["observacoes"].append("Site com boa estrutura básica de conversão")

        else:
            resultado["motivo"] = f"Site retornou erro HTTP {resp.status_code}"

    except Exception as e:
        resultado["motivo"] = f"Site inacessível: {str(e)}"
        resultado["observacoes"].append("Site offline ou com erro — problema crítico de presença")

    return resultado


# =============================================================
# COLETA COMPLETA — junta tudo
# =============================================================

def coletar_dados_completos(empresa, instagram, cidade, google_nome, site, youtube_busca=True, tiktok_username=""):
    """
    Roda todas as coletas e retorna um dicionário completo
    pronto para ser enviado ao Claude.
    """
    print(f"\n🔍 Coletando dados para: {empresa}")
    print("=" * 50)

    dados = {
        "empresa": empresa,
        "cidade": cidade,
        "coletado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Instagram
    print("📸 Instagram...")
    if instagram:
        dados["instagram"] = coletar_instagram(instagram)
    else:
        dados["instagram"] = {"disponivel": False, "motivo": "Não informado pelo lead"}

    # Google Meu Negócio
    print("📍 Google Meu Negócio...")
    nome_gmb = google_nome or empresa
    dados["google_meu_negocio"] = coletar_google_meu_negocio(nome_gmb, cidade)

    # Site
    print("🌐 Site...")
    if site:
        dados["site"] = coletar_site(site)
    else:
        dados["site"] = {"disponivel": False, "motivo": "Lead não possui site"}

    # YouTube
    print("▶️  YouTube...")
    if youtube_busca:
        dados["youtube"] = coletar_youtube(empresa, cidade)
    else:
        dados["youtube"] = {"disponivel": False, "motivo": "Não solicitado"}

    # TikTok
    print("🎵 TikTok...")
    if tiktok_username:
        dados["tiktok"] = coletar_tiktok(tiktok_username)
    else:
        dados["tiktok"] = {"disponivel": False, "motivo": "Username não informado"}

    print("\n✅ Coleta concluída!")
    return dados


def formatar_para_claude(dados):
    """
    Formata os dados coletados em texto estruturado
    para ser injetado no prompt do Claude.
    """
    linhas = [
        "=== DADOS REAIS COLETADOS AUTOMATICAMENTE ===",
        f"Empresa: {dados.get('empresa')}",
        f"Cidade: {dados.get('cidade')}",
        f"Coletado em: {dados.get('coletado_em')}",
        "",
    ]

    # Instagram
    ig = dados.get("instagram", {})
    linhas.append("--- INSTAGRAM ---")
    if ig.get("disponivel"):
        linhas.append(f"URL: {ig.get('url')}")
        linhas.append(f"Seguidores: {ig.get('seguidores') or 'não disponível'}")
        linhas.append(f"Seguindo: {ig.get('seguindo') or 'não disponível'}")
        linhas.append(f"Posts: {ig.get('total_posts') or 'não disponível'}")
        linhas.append(f"Nome: {ig.get('nome_exibicao') or 'não disponível'}")
        if ig.get("observacoes"):
            linhas.append("Observações: " + " | ".join(ig["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {ig.get('motivo', '')}")
        if ig.get("observacoes"):
            linhas.append("Observações: " + " | ".join(ig["observacoes"]))
    linhas.append("")

    # Google Meu Negócio
    gmb = dados.get("google_meu_negocio", {})
    linhas.append("--- GOOGLE MEU NEGÓCIO ---")
    if gmb.get("disponivel"):
        linhas.append(f"Nome: {gmb.get('nome')}")
        linhas.append(f"Endereço: {gmb.get('endereco')}")
        linhas.append(f"Telefone: {gmb.get('telefone') or 'não cadastrado'}")
        linhas.append(f"Site: {gmb.get('site') or 'não cadastrado'}")
        linhas.append(f"Nota: {gmb.get('nota') or 'sem avaliações'}")
        linhas.append(f"Total de avaliações: {gmb.get('total_avaliacoes') or 0}")
        linhas.append(f"Tem fotos: {'Sim' if gmb.get('tem_fotos') else 'Não'}")
        if gmb.get("observacoes"):
            linhas.append("Observações: " + " | ".join(gmb["observacoes"]))
    else:
        linhas.append(f"Status: Não encontrado — {gmb.get('motivo', '')}")
        if gmb.get("observacoes"):
            linhas.append("Observações: " + " | ".join(gmb["observacoes"]))
    linhas.append("")

    # Site
    site = dados.get("site", {})
    linhas.append("--- SITE ---")
    if site.get("disponivel"):
        linhas.append(f"URL: {site.get('url')}")
        linhas.append(f"SSL (https): {'Sim' if site.get('tem_ssl') else 'Não'}")
        linhas.append(f"WhatsApp: {'Sim' if site.get('tem_whatsapp') else 'Não'}")
        linhas.append(f"Formulário: {'Sim' if site.get('tem_formulario') else 'Não'}")
        linhas.append(f"Pixel Meta: {'Sim' if site.get('tem_pixel_meta') else 'Não'}")
        linhas.append(f"Google Analytics: {'Sim' if site.get('tem_google_analytics') else 'Não'}")
        linhas.append(f"Título: {site.get('titulo') or 'não identificado'}")
        if site.get("observacoes"):
            linhas.append("Observações: " + " | ".join(site["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {site.get('motivo', '')}")
    linhas.append("")

    # YouTube
    yt = dados.get("youtube", {})
    linhas.append("--- YOUTUBE ---")
    if yt.get("disponivel"):
        linhas.append(f"Canal: {yt.get('url_canal')}")
        linhas.append(f"Inscritos: {yt.get('inscricoes') or 'não disponível'}")
        linhas.append(f"Vídeos: {yt.get('total_videos') or 'não disponível'}")
        if yt.get("observacoes"):
            linhas.append("Observações: " + " | ".join(yt["observacoes"]))
    else:
        linhas.append(f"Status: Não encontrado — {yt.get('motivo', '')}")
        if yt.get("observacoes"):
            linhas.append("Observações: " + " | ".join(yt["observacoes"]))
    linhas.append("")

    # TikTok
    tt = dados.get("tiktok", {})
    linhas.append("--- TIKTOK ---")
    if tt.get("disponivel"):
        linhas.append(f"URL: {tt.get('url')}")
        linhas.append(f"Seguidores: {tt.get('seguidores') or 'não disponível'}")
        linhas.append(f"Curtidas: {tt.get('curtidas') or 'não disponível'}")
        linhas.append(f"Vídeos: {tt.get('total_videos') or 'não disponível'}")
        if tt.get("observacoes"):
            linhas.append("Observações: " + " | ".join(tt["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {tt.get('motivo', '')}")
        if tt.get("observacoes"):
            linhas.append("Observações: " + " | ".join(tt["observacoes"]))

    linhas.append("")
    linhas.append("=== FIM DOS DADOS COLETADOS ===")

    return "\n".join(linhas)


# =============================================================
# FLASK API — para o Railway + n8n
# =============================================================

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servico": "UC Diagnóstico"})


@app.route("/coletar", methods=["POST"])
def api_coletar():
    """
    Endpoint chamado pelo n8n.
    
    Recebe JSON com:
    {
        "empresa": "Nome da Empresa",
        "instagram": "username",
        "cidade": "Porto Velho",
        "google_nome": "Nome no Google (opcional)",
        "site": "https://...",
        "tiktok": "username (opcional)"
    }
    
    Retorna JSON com todos os dados coletados + texto formatado para o Claude.
    """
    body = request.get_json()

    if not body:
        return jsonify({"erro": "Body JSON não encontrado"}), 400

    empresa = body.get("empresa", "")
    instagram = body.get("instagram", "")
    cidade = body.get("cidade", "Porto Velho")
    google_nome = body.get("google_nome", empresa)
    site = body.get("site", "")
    tiktok = body.get("tiktok", "")

    if not empresa:
        return jsonify({"erro": "Campo 'empresa' é obrigatório"}), 400

    dados = coletar_dados_completos(
        empresa=empresa,
        instagram=instagram,
        cidade=cidade,
        google_nome=google_nome,
        site=site,
        youtube_busca=True,
        tiktok_username=tiktok,
    )

    texto_claude = formatar_para_claude(dados)

    return jsonify({
        "dados_brutos": dados,
        "texto_para_claude": texto_claude,
        "status": "ok"
    })


# =============================================================
# USO LOCAL (linha de comando)
# =============================================================

def rodar_local():
    parser = argparse.ArgumentParser(description="UC Diagnóstico — Coleta de dados")
    parser.add_argument("--empresa", required=True, help="Nome da empresa")
    parser.add_argument("--instagram", default="", help="@ do Instagram (com ou sem @)")
    parser.add_argument("--cidade", default="Porto Velho", help="Cidade da empresa")
    parser.add_argument("--google", default="", help="Nome no Google Meu Negócio (se diferente)")
    parser.add_argument("--site", default="", help="URL do site")
    parser.add_argument("--tiktok", default="", help="@ do TikTok")
    parser.add_argument("--json", action="store_true", help="Exporta resultado em JSON")
    args = parser.parse_args()

    dados = coletar_dados_completos(
        empresa=args.empresa,
        instagram=args.instagram,
        cidade=args.cidade,
        google_nome=args.google or args.empresa,
        site=args.site,
        youtube_busca=True,
        tiktok_username=args.tiktok,
    )

    texto = formatar_para_claude(dados)
    print("\n" + texto)

    if args.json:
        nome_arquivo = f"diagnostico_{args.empresa.replace(' ', '_').lower()}.json"
        with open(nome_arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON salvo em: {nome_arquivo}")


# =============================================================
# ENTRY POINT
# =============================================================

if __name__ == "__main__":
    import sys

    # Se passou argumentos = modo local
    # Se não passou = modo API (Railway)
    if len(sys.argv) > 1:
        rodar_local()
    else:
        print("🚀 Subindo API UC Diagnóstico...")
        app.run(host="0.0.0.0", port=8080)
