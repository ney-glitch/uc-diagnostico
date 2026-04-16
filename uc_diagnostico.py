"""
=============================================================
  UNIVERSO CRIATIVO — COLETA DE DADOS PARA DIAGNÓSTICO v2
  
  Melhorias desta versão:
  - Busca GMN com variações do nome (resolve nomes diferentes)
  - Concorrentes por nicho + cidade integrados
  - Meta Ad Library (anúncios públicos da empresa)
  - Campo trafegoPago do formulário mapeado
  - Dados mais ricos formatados pro Claude
=============================================================

DEPENDÊNCIAS:
    pip install requests beautifulsoup4 flask

USO LOCAL:
    python uc_diagnostico.py --empresa "The Rocks Barbearia" --instagram rocksbarber --cidade "Porto Velho" --nicho "Barbearia"

USO COMO API (Railway):
    Sem argumentos = sobe servidor web na porta 8080
"""

import requests
import re
import time
import json
import argparse
import os
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# =============================================================
# CONFIGURAÇÕES
# =============================================================

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "SUA_CHAVE_AQUI")

# Token público da Meta Ad Library — gratuito
# Gerar em: developers.facebook.com → Ferramentas → Explorador de API
# Permissão necessária: ads_read (pública)
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "SEU_TOKEN_AQUI")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# =============================================================
# UTILITÁRIOS
# =============================================================

def normalizar_arroba(valor):
    if not valor:
        return ""
    return valor.strip().lstrip("@").strip()


def safe_get(url, params=None, timeout=10):
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def gerar_variacoes_nome(nome):
    """
    Gera variações do nome para busca no GMN.
    Ex: "The Rocks Barbearia" → ["The Rocks Barbearia", "The Rocks", "Rocks Barbearia"]
    """
    variacoes = [nome]
    partes = nome.split()

    if len(partes) >= 2:
        variacoes.append(" ".join(partes[1:]))
        variacoes.append(" ".join(partes[:2]))
        if len(partes) >= 3:
            variacoes.append(partes[-1] + " " + partes[0])

    vistos = set()
    resultado = []
    for v in variacoes:
        if v.lower() not in vistos:
            vistos.add(v.lower())
            resultado.append(v)
    return resultado


# =============================================================
# INSTAGRAM
# =============================================================

def coletar_instagram(username):
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
        "observacoes": []
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)

        if resp.status_code == 404:
            resultado["motivo"] = "Perfil não encontrado"
            return resultado

        if resp.status_code != 200:
            resultado["motivo"] = f"Erro HTTP {resp.status_code}"
            return resultado

        html = resp.text

        og_desc = re.search(r'<meta property="og:description" content="([^"]*)"', html)
        if og_desc:
            desc = og_desc.group(1)
            seg_match = re.search(r'([\d,\.]+)\s*Followers?', desc, re.IGNORECASE)
            if seg_match:
                resultado["seguidores"] = seg_match.group(1)
            seg2 = re.search(r'([\d,\.]+)\s*Following', desc, re.IGNORECASE)
            if seg2:
                resultado["seguindo"] = seg2.group(1)
            posts_match = re.search(r'([\d,\.]+)\s*Posts?', desc, re.IGNORECASE)
            if posts_match:
                resultado["total_posts"] = posts_match.group(1)

        og_title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        if og_title:
            resultado["nome_exibicao"] = og_title.group(1).replace(" • Instagram", "").strip()

        if resultado["seguidores"] or resultado["nome_exibicao"]:
            resultado["disponivel"] = True

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
                try:
                    posts_num = int(resultado["total_posts"].replace(",", "").replace(".", ""))
                    if posts_num < 10:
                        resultado["observacoes"].append("Pouquíssimas publicações — perfil pouco ativo")
                    elif posts_num < 30:
                        resultado["observacoes"].append("Baixo volume de publicações")
                    else:
                        resultado["observacoes"].append(f"{posts_num} publicações no perfil")
                except:
                    pass
        else:
            resultado["motivo"] = "Instagram bloqueou a requisição ou perfil privado"
            resultado["observacoes"].append(f"Verificar manualmente: {url}")

    except Exception as e:
        resultado["motivo"] = f"Erro na coleta: {str(e)}"

    return resultado


# =============================================================
# GOOGLE MEU NEGÓCIO — com variações de nome
# =============================================================

def buscar_place_por_query(query):
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "key": GOOGLE_PLACES_API_KEY,
        "language": "pt-BR",
        "region": "br",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return None
    data = resp.json()
    results = data.get("results", [])
    return results[0] if results else None


def buscar_detalhes_place(place_id):
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "key": GOOGLE_PLACES_API_KEY,
        "language": "pt-BR",
        "fields": "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,photos,opening_hours,types",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return {}
    return resp.json().get("result", {})


def coletar_google_meu_negocio(nome_empresa, cidade, nome_gmn=""):
    resultado = {
        "disponivel": False,
        "nome": None,
        "endereco": None,
        "telefone": None,
        "site": None,
        "nota": None,
        "total_avaliacoes": None,
        "tem_fotos": False,
        "horario_funcionamento": None,
        "tentativas": [],
        "observacoes": []
    }

    queries = []
    nome_busca = nome_gmn if nome_gmn else nome_empresa

    for variacao in gerar_variacoes_nome(nome_busca):
        queries.append(f"{variacao} {cidade}")

    if nome_gmn and nome_gmn.lower() != nome_empresa.lower():
        for variacao in gerar_variacoes_nome(nome_empresa):
            q = f"{variacao} {cidade}"
            if q not in queries:
                queries.append(q)

    place_encontrado = None
    for query in queries:
        resultado["tentativas"].append(query)
        place = buscar_place_por_query(query)
        if place:
            place_encontrado = place
            break
        time.sleep(0.3)

    if not place_encontrado:
        resultado["motivo"] = f"Não encontrado após {len(queries)} tentativas"
        resultado["observacoes"].append("Perfil GMN não localizado — verificar nome manualmente")
        resultado["observacoes"].append(f"Tentativas: {', '.join(queries[:3])}")
        return resultado

    det = buscar_detalhes_place(place_encontrado["place_id"])

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

    nota = resultado["nota"] or 0
    avaliacoes = resultado["total_avaliacoes"] or 0

    if avaliacoes == 0:
        resultado["observacoes"].append("Sem avaliações — ponto crítico a trabalhar")
    elif avaliacoes < 10:
        resultado["observacoes"].append(f"Apenas {avaliacoes} avaliações — base muito pequena")
    elif avaliacoes < 50:
        resultado["observacoes"].append(f"{avaliacoes} avaliações — crescimento possível com estratégia")
    else:
        resultado["observacoes"].append(f"{avaliacoes} avaliações — boa presença no Google")

    if nota > 0:
        if nota < 3.5:
            resultado["observacoes"].append(f"Nota {nota} — reputação comprometida, ação urgente")
        elif nota < 4.0:
            resultado["observacoes"].append(f"Nota {nota} — abaixo da média")
        elif nota < 4.5:
            resultado["observacoes"].append(f"Nota {nota} — boa reputação")
        else:
            resultado["observacoes"].append(f"Nota {nota} — excelente reputação")

    if not resultado["site"]:
        resultado["observacoes"].append("Sem site cadastrado no GMN")
    if not resultado["tem_fotos"]:
        resultado["observacoes"].append("Sem fotos no perfil — prejudica conversão")

    return resultado


# =============================================================
# CONCORRENTES
# =============================================================

def buscar_concorrentes(nicho, cidade, limite=5):
    resultado = {
        "disponivel": False,
        "concorrentes": [],
        "observacoes": []
    }

    query = f"{nicho} {cidade}"
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "key": GOOGLE_PLACES_API_KEY,
        "language": "pt-BR",
        "region": "br",
    }

    resp = safe_get(url, params=params)
    if not resp:
        resultado["motivo"] = "Erro ao buscar concorrentes"
        return resultado

    places = resp.json().get("results", [])[:limite]

    for place in places:
        concorrente = {
            "nome": place.get("name"),
            "nota": place.get("rating"),
            "avaliacoes": place.get("user_ratings_total", 0),
            "endereco": place.get("formatted_address", "").split(",")[0],
            "tem_site": False,
        }
        det = buscar_detalhes_place(place.get("place_id", ""))
        concorrente["tem_site"] = bool(det.get("website"))
        resultado["concorrentes"].append(concorrente)
        time.sleep(0.2)

    if resultado["concorrentes"]:
        resultado["disponivel"] = True
        top = resultado["concorrentes"][0]
        resultado["observacoes"].append(
            f"Líder local: {top['nome']} com nota {top['nota']} e {top['avaliacoes']} avaliações"
        )

    return resultado


# =============================================================
# META AD LIBRARY
# =============================================================

def buscar_anuncios_meta(nome_empresa):
    resultado = {
        "disponivel": False,
        "roda_anuncios": False,
        "total_anuncios_ativos": 0,
        "plataformas": [],
        "anuncios": [],
        "observacoes": []
    }

    if not META_ACCESS_TOKEN or META_ACCESS_TOKEN == "SEU_TOKEN_AQUI":
        resultado["motivo"] = "Token Meta não configurado"
        resultado["observacoes"].append("Configure META_ACCESS_TOKEN para buscar anúncios")
        return resultado

    url = "https://graph.facebook.com/v19.0/ads_archive"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "search_terms": nome_empresa,
        "ad_reached_countries": '["BR"]',
        "ad_active_status": "ACTIVE",
        "limit": 10,
        "fields": "ad_creative_body,ad_delivery_start_time,publisher_platforms,page_name",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            resultado["motivo"] = f"Erro API Meta: {data['error'].get('message', '')}"
            return resultado

        anuncios = data.get("data", [])

        if anuncios:
            resultado["disponivel"] = True
            resultado["roda_anuncios"] = True
            resultado["total_anuncios_ativos"] = len(anuncios)

            plataformas_set = set()
            for ad in anuncios[:5]:
                plataformas = ad.get("publisher_platforms", [])
                plataformas_set.update(plataformas)
                resultado["anuncios"].append({
                    "pagina": ad.get("page_name"),
                    "plataformas": plataformas,
                    "inicio": ad.get("ad_delivery_start_time", ""),
                    "texto": (ad.get("ad_creative_body") or "")[:150],
                })

            resultado["plataformas"] = list(plataformas_set)
            resultado["observacoes"].append(
                f"Empresa com {len(anuncios)} anúncio(s) ativo(s) — já investe em tráfego"
            )
        else:
            resultado["disponivel"] = True
            resultado["roda_anuncios"] = False
            resultado["observacoes"].append("Nenhum anúncio ativo encontrado no Meta Ad Library")

    except Exception as e:
        resultado["motivo"] = f"Erro na consulta: {str(e)}"

    return resultado


# =============================================================
# YOUTUBE
# =============================================================

def coletar_youtube(nome_empresa, cidade=""):
    resultado = {
        "disponivel": False,
        "nome_canal": None,
        "url_canal": None,
        "inscricoes": None,
        "total_videos": None,
        "observacoes": []
    }

    url = f"https://www.google.com/search?q={requests.utils.quote(nome_empresa + ' ' + cidade + ' canal youtube')}"
    resp = safe_get(url)
    if not resp:
        resultado["motivo"] = "Não foi possível buscar canal"
        return resultado

    soup = BeautifulSoup(resp.text, "html.parser")
    youtube_url = None

    for a in soup.find_all("a", href=True):
        match = re.search(r'(https?://(?:www\.)?youtube\.com/(?:@|channel/|c/)[^&\s"]+)', a["href"])
        if match:
            youtube_url = match.group(1)
            break

    if not youtube_url:
        resultado["motivo"] = "Canal não encontrado"
        resultado["observacoes"].append("Sem canal no YouTube identificado — oportunidade")
        return resultado

    resultado["url_canal"] = youtube_url
    resultado["disponivel"] = True

    resp_canal = safe_get(youtube_url)
    if resp_canal:
        html = resp_canal.text
        title_match = re.search(r'"channelMetadataRenderer":\{"title":"([^"]+)"', html)
        if title_match:
            resultado["nome_canal"] = title_match.group(1)
        subs_match = re.search(r'"subscriberCountText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"', html)
        if subs_match:
            resultado["inscricoes"] = subs_match.group(1)
        videos_match = re.search(r'"videoCountText":\{"runs":\[\{"text":"([^"]+)"', html)
        if videos_match:
            resultado["total_videos"] = videos_match.group(1)

    return resultado


# =============================================================
# TIKTOK
# =============================================================

def coletar_tiktok(username):
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
        "observacoes": []
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            html = resp.text
            json_match = re.search(
                r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>', html
            )
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    stats = (data
                        .get("__DEFAULT_SCOPE__", {})
                        .get("webapp.user-detail", {})
                        .get("userInfo", {})
                        .get("stats", {})
                    )
                    if stats:
                        resultado["disponivel"] = True
                        resultado["seguidores"] = stats.get("followerCount")
                        resultado["curtidas"] = stats.get("heartCount")
                        resultado["total_videos"] = stats.get("videoCount")
                except:
                    pass

            if not resultado["disponivel"]:
                resultado["motivo"] = "TikTok bloqueou ou perfil não encontrado"
                resultado["observacoes"].append(f"Verificar manualmente: {url}")
    except Exception as e:
        resultado["motivo"] = f"Erro: {str(e)}"

    return resultado


# =============================================================
# SITE
# =============================================================

def coletar_site(url_site):
    if not url_site:
        return {"disponivel": False, "motivo": "URL não informada"}

    if not url_site.startswith("http"):
        url_site = "https://" + url_site

    resultado = {
        "disponivel": False,
        "url": url_site,
        "tem_ssl": url_site.startswith("https"),
        "tem_whatsapp": False,
        "tem_formulario": False,
        "tem_pixel_meta": False,
        "tem_google_analytics": False,
        "titulo": None,
        "observacoes": []
    }

    try:
        resp = requests.get(url_site, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            resultado["disponivel"] = True
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            if soup.title:
                resultado["titulo"] = soup.title.string

            resultado["tem_whatsapp"] = bool(
                re.search(r'wa\.me|whatsapp\.com|api\.whatsapp', html, re.IGNORECASE)
            )
            resultado["tem_formulario"] = bool(soup.find("form"))
            resultado["tem_pixel_meta"] = bool(
                re.search(r'fbq\(|facebook\.net/en_US/fbevents|connect\.facebook\.net', html)
            )
            resultado["tem_google_analytics"] = bool(
                re.search(r'google-analytics\.com|ga\.js|analytics\.js|gtag', html)
            )

            if not resultado["tem_ssl"]:
                resultado["observacoes"].append("Sem SSL — prejudica SEO e confiança")
            if not resultado["tem_whatsapp"]:
                resultado["observacoes"].append("Sem botão WhatsApp — perda de conversão")
            if not resultado["tem_pixel_meta"]:
                resultado["observacoes"].append("Sem Pixel Meta — impossível fazer remarketing")
            if not resultado["tem_google_analytics"]:
                resultado["observacoes"].append("Sem Google Analytics — sem dados de tráfego")
            if not resultado["observacoes"]:
                resultado["observacoes"].append("Boa estrutura básica de conversão")
        else:
            resultado["motivo"] = f"Site retornou erro {resp.status_code}"
    except Exception as e:
        resultado["motivo"] = f"Site inacessível: {str(e)}"
        resultado["observacoes"].append("Site offline ou com erro — problema crítico")

    return resultado


# =============================================================
# COLETA COMPLETA
# =============================================================

def coletar_dados_completos(empresa, instagram, cidade, nicho, nome_gmn="",
                             site="", tiktok_username="", trafego_pago=""):
    print(f"\n🔍 Coletando dados para: {empresa}")
    print("=" * 50)

    dados = {
        "empresa": empresa,
        "cidade": cidade,
        "nicho": nicho,
        "trafego_pago_declarado": trafego_pago,
        "coletado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    print("📸 Instagram...")
    dados["instagram"] = coletar_instagram(instagram) if instagram else {"disponivel": False, "motivo": "Não informado"}

    print("📍 Google Meu Negócio...")
    dados["google_meu_negocio"] = coletar_google_meu_negocio(empresa, cidade, nome_gmn)

    print("🌐 Site...")
    dados["site"] = coletar_site(site) if site else {"disponivel": False, "motivo": "Lead não possui site"}

    print("▶️  YouTube...")
    dados["youtube"] = coletar_youtube(empresa, cidade)

    print("🎵 TikTok...")
    dados["tiktok"] = coletar_tiktok(tiktok_username) if tiktok_username else {"disponivel": False, "motivo": "Não informado"}

    print("🏆 Concorrentes...")
    dados["concorrentes"] = buscar_concorrentes(nicho, cidade)

    print("📢 Meta Ad Library...")
    dados["meta_ads"] = buscar_anuncios_meta(empresa)

    print("\n✅ Coleta concluída!")
    return dados


# =============================================================
# FORMATAÇÃO PARA O CLAUDE
# =============================================================

def formatar_para_claude(dados):
    linhas = [
        "=== DADOS REAIS COLETADOS AUTOMATICAMENTE ===",
        f"Empresa: {dados.get('empresa')}",
        f"Cidade: {dados.get('cidade')}",
        f"Nicho: {dados.get('nicho')}",
        f"Tráfego pago declarado pelo lead: {dados.get('trafego_pago_declarado') or 'Não informado'}",
        f"Coletado em: {dados.get('coletado_em')}",
        "",
    ]

    ig = dados.get("instagram", {})
    linhas.append("--- INSTAGRAM ---")
    if ig.get("disponivel"):
        linhas += [
            f"URL: {ig.get('url')}",
            f"Nome: {ig.get('nome_exibicao') or 'não disponível'}",
            f"Seguidores: {ig.get('seguidores') or 'não disponível'}",
            f"Seguindo: {ig.get('seguindo') or 'não disponível'}",
            f"Total de posts: {ig.get('total_posts') or 'não disponível'}",
        ]
        if ig.get("observacoes"):
            linhas.append("Análise: " + " | ".join(ig["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {ig.get('motivo', '')}")
        if ig.get("observacoes"):
            linhas.append("Nota: " + " | ".join(ig["observacoes"]))
    linhas.append("")

    gmb = dados.get("google_meu_negocio", {})
    linhas.append("--- GOOGLE MEU NEGÓCIO ---")
    if gmb.get("disponivel"):
        linhas += [
            f"Nome encontrado: {gmb.get('nome')}",
            f"Endereço: {gmb.get('endereco')}",
            f"Telefone: {gmb.get('telefone') or 'não cadastrado'}",
            f"Site cadastrado: {gmb.get('site') or 'não cadastrado'}",
            f"Nota Google: {gmb.get('nota') or 'sem nota'}",
            f"Total de avaliações: {gmb.get('total_avaliacoes') or 0}",
            f"Tem fotos: {'Sim' if gmb.get('tem_fotos') else 'Não'}",
        ]
        if gmb.get("horario_funcionamento"):
            linhas.append(f"Horário: {' / '.join(gmb['horario_funcionamento'][:3])}")
        if gmb.get("observacoes"):
            linhas.append("Análise: " + " | ".join(gmb["observacoes"]))
    else:
        linhas.append(f"Status: Não encontrado — {gmb.get('motivo', '')}")
        if gmb.get("observacoes"):
            linhas.append("Nota: " + " | ".join(gmb["observacoes"]))
    linhas.append("")

    site = dados.get("site", {})
    linhas.append("--- SITE ---")
    if site.get("disponivel"):
        linhas += [
            f"URL: {site.get('url')}",
            f"SSL (https): {'Sim' if site.get('tem_ssl') else 'Não'}",
            f"Botão WhatsApp: {'Sim' if site.get('tem_whatsapp') else 'Não'}",
            f"Formulário de contato: {'Sim' if site.get('tem_formulario') else 'Não'}",
            f"Pixel Meta instalado: {'Sim' if site.get('tem_pixel_meta') else 'Não'}",
            f"Google Analytics: {'Sim' if site.get('tem_google_analytics') else 'Não'}",
            f"Título da página: {site.get('titulo') or 'não identificado'}",
        ]
        if site.get("observacoes"):
            linhas.append("Análise: " + " | ".join(site["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {site.get('motivo', '')}")
    linhas.append("")

    yt = dados.get("youtube", {})
    linhas.append("--- YOUTUBE ---")
    if yt.get("disponivel"):
        linhas += [
            f"Canal: {yt.get('url_canal')}",
            f"Nome: {yt.get('nome_canal') or 'não disponível'}",
            f"Inscritos: {yt.get('inscricoes') or 'não disponível'}",
            f"Total de vídeos: {yt.get('total_videos') or 'não disponível'}",
        ]
    else:
        linhas.append(f"Status: Não encontrado — {yt.get('motivo', '')}")
        if yt.get("observacoes"):
            linhas.append("Nota: " + " | ".join(yt["observacoes"]))
    linhas.append("")

    tt = dados.get("tiktok", {})
    linhas.append("--- TIKTOK ---")
    if tt.get("disponivel"):
        linhas += [
            f"URL: {tt.get('url')}",
            f"Seguidores: {tt.get('seguidores') or 'não disponível'}",
            f"Curtidas totais: {tt.get('curtidas') or 'não disponível'}",
            f"Total de vídeos: {tt.get('total_videos') or 'não disponível'}",
        ]
        if tt.get("observacoes"):
            linhas.append("Análise: " + " | ".join(tt["observacoes"]))
    else:
        linhas.append(f"Status: Não disponível — {tt.get('motivo', '')}")
        if tt.get("observacoes"):
            linhas.append("Nota: " + " | ".join(tt["observacoes"]))
    linhas.append("")

    conc = dados.get("concorrentes", {})
    linhas.append("--- ANÁLISE COMPETITIVA LOCAL ---")
    if conc.get("disponivel") and conc.get("concorrentes"):
        for i, c in enumerate(conc["concorrentes"], 1):
            linhas.append(
                f"{i}. {c['nome']} | Nota: {c['nota'] or 'N/A'} | "
                f"Avaliações: {c['avaliacoes']} | Site: {'Sim' if c['tem_site'] else 'Não'}"
            )
        if conc.get("observacoes"):
            linhas.append("Análise: " + " | ".join(conc["observacoes"]))
    else:
        linhas.append("Concorrentes não encontrados")
    linhas.append("")

    meta = dados.get("meta_ads", {})
    linhas.append("--- META AD LIBRARY ---")
    if meta.get("disponivel"):
        if meta.get("roda_anuncios"):
            linhas.append(f"Anúncios ativos: {meta.get('total_anuncios_ativos')}")
            linhas.append(f"Plataformas: {', '.join(meta.get('plataformas', []))}")
            for ad in meta.get("anuncios", [])[:3]:
                if ad.get("texto"):
                    linhas.append(f"Criativo: {ad['texto'][:100]}...")
        else:
            linhas.append("Sem anúncios ativos encontrados no Meta")
        if meta.get("observacoes"):
            linhas.append("Análise: " + " | ".join(meta["observacoes"]))
    else:
        linhas.append(f"Status: {meta.get('motivo', 'não verificado')}")
    linhas.append("")
    linhas.append("=== FIM DOS DADOS COLETADOS ===")

    return "\n".join(linhas)


# =============================================================
# FLASK API
# =============================================================

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servico": "UC Diagnóstico v2"})


@app.route("/coletar", methods=["POST"])
def api_coletar():
    body = request.get_json()
    if not body:
        return jsonify({"erro": "Body JSON não encontrado"}), 400

    empresa = body.get("empresa", "")
    if not empresa:
        return jsonify({"erro": "Campo 'empresa' é obrigatório"}), 400

    dados = coletar_dados_completos(
        empresa=empresa,
        instagram=body.get("instagram", ""),
        cidade=body.get("cidade", "Porto Velho"),
        nicho=body.get("nicho", ""),
        nome_gmn=body.get("google_nome", ""),
        site=body.get("site", ""),
        tiktok_username=body.get("tiktok", ""),
        trafego_pago=body.get("trafego_pago", ""),
    )

    return jsonify({
        "dados_brutos": dados,
        "texto_para_claude": formatar_para_claude(dados),
        "status": "ok"
    })


# =============================================================
# USO LOCAL
# =============================================================

def rodar_local():
    parser = argparse.ArgumentParser(description="UC Diagnóstico v2")
    parser.add_argument("--empresa", required=True)
    parser.add_argument("--instagram", default="")
    parser.add_argument("--cidade", default="Porto Velho")
    parser.add_argument("--nicho", default="")
    parser.add_argument("--google", default="")
    parser.add_argument("--site", default="")
    parser.add_argument("--tiktok", default="")
    parser.add_argument("--trafego", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dados = coletar_dados_completos(
        empresa=args.empresa,
        instagram=args.instagram,
        cidade=args.cidade,
        nicho=args.nicho,
        nome_gmn=args.google,
        site=args.site,
        tiktok_username=args.tiktok,
        trafego_pago=args.trafego,
    )

    print("\n" + formatar_para_claude(dados))

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
    if len(sys.argv) > 1:
        rodar_local()
    else:
        print("🚀 Subindo API UC Diagnóstico v2...")
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
