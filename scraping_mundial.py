# update_supabase.py (VERSÃO FINAL 4.0 - Integrado com Notificações do Telegram)

import os
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

URL_SCRAPER = 'https://www.placardefutebol.com.br/copa-do-mundo'

# --- CONFIGURAÇÕES DO TELEGRAM ---
# O ideal é salvar estas duas chaves também nas configurações de Secrets do GitHub Actions!
# Se for rodar local, adicione-as no arquivo .env como TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8637465344:AAH4wiKxyFEbU-cu7hsNkHdmyACwVa7vSak")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004342102310")

def enviar_mensagem_telegram(mensagem):
    """
    Função utilitária que faz o disparo HTTP post para a API de Bots do Telegram.
    Usa o parse_mode='HTML' para permitir formatação de negrito e emojis limpos.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print("🔔 Notificação de ranking enviada com sucesso ao Telegram!")
        else:
            print(f"⚠️ Erro ao enviar notificação do Telegram: {res.text}")
    except Exception as e:
        print(f"💥 Falha ao conectar com o serviço do Telegram: {e}")

def buscar_e_formatar_ranking(supabase: Client, pool_id: str, mandante: str, visitante: str, placar_m: int, placar_v: int):
    """
    Busca os dados atualizados das participações do bolão para capturar os 3 líderes
    e o último colocado (lanterna), ignorando administradores e contas de Inteligência Artificial.
    """
    try:
        # Busca os dados ordenados por pontos (decrescente) e desempate por cravadas (exact_scores)
        # Ajustamos os filtros 'is_admin' e 'is_ai' conforme as regras das tabelas customizadas
        res_ranking = supabase.table('participations') \
            .select('points, exact_scores, users_custom(name, is_admin, is_ai)') \
            .eq('pool_id', pool_id) \
            .execute()
        
        if not res_ranking.data:
            print("Aviso: Não foi possível obter dados para montar o ranking do Telegram.")
            return

        # Filtra os participantes reais (removendo robôs de IA e admins da lista)
        participantes_filtrados = []
        for item in res_ranking.data:
            user_info = item.get('users_custom', {})
            if user_info and not user_info.get('is_admin') and not user_info.get('is_ai'):
                participantes_filtrados.append({
                    'name': user_info.get('name', 'Participante'),
                    'points': item.get('points', 0),
                    'exact_scores': item.get('exact_scores', 0)
                })

        # Reordena a lista com base nos critérios oficiais (1º Pontos, 2º Cravadas)
        participantes_filtrados.sort(key=lambda x: (x['points'], x['exact_scores']), reverse=True)

        if len(participantes_filtrados) == 0:
            return

        # Captura o Pódio (Até os 3 primeiros)
        top_3 = participantes_filtrados[:3]
        
        # Captura o Lanterna (Último da lista filtrada)
        lanterna = participantes_filtrados[-1]

        # --- CONSTRUÇÃO DO LAYOUT DA MENSAGEM ---
        mensagem_linhas = [
            "📊 <b>PARCIAIS DO BOLÃO CLUBE FUTURO</b> 📊\n",
            f"⚽ <b>{mandante.upper()} {placar_m} x {placar_v} {visitante.upper()}</b>\n",
            "🏆 <b>Primeiros colocados:</b>"
        ]

        # Adiciona os líderes com medalhas dinâmicas
        medalhas = ["🥇", "🥈", "🥉"]
        for i, participante in enumerate(top_3):
            medalha = medalhas[i] if i < len(medalhas) else "🔹"
            mensagem_linhas.append(f"{medalha} {participante['name']} — {participante['points']} Pontos")

        # Adiciona a cobrança saudável da lanterna
        mensagem_linhas.append("\n🦉 <b>Tá devendo a prenda (por enquanto):</b>")
        mensagem_linhas.append(f"🚨 {lanterna['name']} — {lanterna['points']} Pontos")
        
        mensagem_linhas.append("\n🏃‍♂️ Acesse o app para conferir seus palpites!")

        # Une todas as linhas em uma única string com quebra de página
        mensagem_completa = "\n".join(mensagem_linhas)
        
        # Dispara o Alerta para o grupo do Telegram!
        enviar_mensagem_telegram(mensagem_completa)

    except Exception as err:
        print(f"Erro na geração do layout da mensagem de ranking: {err}")

def obter_jogos_do_site():
    """
    Função principal de scraping. Navega até o site, extrai os dados dos jogos
    e retorna uma lista de dicionários com as informações de cada partida.
    """
    print("-> Iniciando o scraper para buscar jogos...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(URL_SCRAPER)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CLASS_NAME, 'match__md')))
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        lista_jogos = []
        main_container = soup.find('div', id='main')
        cards_jogos = main_container.find_all('a', class_='match__md') if main_container else []

        print(f"-> {len(cards_jogos)} cards de jogos encontrados. Processando...")

        for card in cards_jogos:
            try:
                time_casa_el = card.find('div', class_='match__md_card--ht-name')
                time_fora_el = card.find('div', class_='match__md_card--at-name')
                
                if not time_casa_el or not time_fora_el: continue

                time_casa = time_casa_el.get_text(strip=True)
                time_fora = time_fora_el.get_text(strip=True)
                
                placar_casa, placar_fora = '-', '-'

                # --- LÓGICA DE STATUS HIERÁRQUICA ---
                placar_el = card.find('div', class_='match__md_card--scoreboard')
                status_el = card.find('div', class_='match__md_card--status')
                live_el = card.find('div', class_='match__md_card--live')
                datetime_el = card.find('div', class_='match__md_card--datetime')

                status_text = status_el.get_text(strip=True).lower() if status_el else ""

                TEXTOS_DE_JOGO_FINALIZADO = ['encerrado', 'fim de jogo', 'pên.']
                
                if 'suspenso' in status_text:
                    status = 'Suspenso'
                elif any(termo in status_text for termo in TEXTOS_DE_JOGO_FINALIZADO):
                    status = 'Encerrado'
                elif 'intervalo' in status_text:
                    status = 'Intervalo'
                elif live_el:
                    status = 'Ao Vivo'
                elif placar_el:
                    status = 'Encerrado'
                elif datetime_el:
                    status = 'Não iniciado'
                else:
                    status = 'Não definido'

                if status == 'Encerrado' and placar_el:
                    scores = placar_el.find_all('b')
                    if len(scores) >= 2:
                        try:
                            placar_casa = int(scores[0].get_text(strip=True))
                            placar_fora = int(scores[1].get_text(strip=True))
                        except (ValueError, TypeError):
                            placar_casa = scores[0].get_text(strip=True)
                            placar_fora = scores[1].get_text(strip=True)
                
                lista_jogos.append({
                    'mandante': time_casa,
                    'visitante': time_fora,
                    'placar_mandante': placar_casa,
                    'placar_visitante': placar_fora,
                    'status': status
                })
            except Exception as e:
                print(f"Aviso: Erro ao processar um card de jogo: {e}")
                continue
        
        return lista_jogos
    finally:
        if driver:
            driver.quit()
        print("-> Scraper finalizado.")

def atualizar_plataforma():
    """
    Orquestra todo o processo: busca os jogos do site, conecta ao Supabase,
    e atualiza as partidas que foram finalizadas.
    A pontuação dos utilizadores é calculada automaticamente por Triggers no Supabase.
    """
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_SERVICE_KEY")
    
    if not url or not key:
        print("Erro: Variáveis de ambiente SUPABASE_URL e SUPABASE_SERVICE_KEY não encontradas.")
        return

    try:
        supabase: Client = create_client(url, key)
        print("-> Conectado ao Supabase com sucesso!")
    except Exception as e:
        print(f"Erro ao conectar ao Supabase: {e}")
        return

    jogos_raspados = obter_jogos_do_site()
    if not jogos_raspados:
        print("Nenhum jogo foi encontrado pelo scraper. Encerrando.")
        return

    response = supabase.table('teams').select('id, name').execute()
    if response.data is None:
        print("Erro ao buscar equipas do banco de dados.")
        return
    
    mapeamento_times = {time['name']: time['id'] for time in response.data}
    print(f"-> {len(mapeamento_times)} equipas carregadas do banco.")

    partidas_para_atualizar = []
    for jogo in jogos_raspados:
        if jogo['status'] == 'Encerrado':
            mandante = jogo['mandante']
            visitor = jogo['visitante']

            if mandante in mapeamento_times and visitor in mapeamento_times:
                partidas_para_atualizar.append({
                    'mandante_nome': mandante,
                    'visitante_nome': visitor,
                    'home_team_id': mapeamento_times[mandante],
                    'away_team_id': mapeamento_times[visitor],
                    'home_score': jogo['placar_mandante'],
                    'away_score': jogo['placar_visitante']
                })
            else:
                print(f"Aviso: Jogo '{mandante} vs {visitor}' ignorado (equipa não encontrada no banco).")
    
    if not partidas_para_atualizar:
        print("\nNenhuma partida encerrada para atualizar no momento.")
        return

    print(f"\n-> Encontradas {len(partidas_para_atualizar)} partidas com resultado para processar...")
    for partida in partidas_para_atualizar:
        try:
            # Envia apenas os golos e altera o status para 'finished'
            # O filtro 'status': 'scheduled' garante que só atualizamos jogos que ainda não terminaram.
            res = supabase.table('matches').update({
                'home_score': partida['home_score'],
                'away_score': partida['away_score'],
                'status': 'finished'
            }).match({
                'home_team_id': partida['home_team_id'],
                'away_team_id': partida['away_team_id'],
                'status': 'scheduled' 
            }).execute()
            
            # Verificamos se houve modificação real na linha (res.data trará o objeto alterado)
            if len(res.data) > 0:
                match_id = res.data[0]['id']
                pool_id = res.data[0].get('pool_id') or res.data[0].get('championship_id')
                
                print(f"  - Resultado da partida ID {match_id} atualizado no Supabase.")
                print("  - O banco de dados (Trigger) calculou os pontos. Gerando parcial para o Telegram...")
                
                # Aguarda 2 segundos rápidos para garantir que as triggers concluíram o recálculo
                time.sleep(2)
                
                # Dispara a busca do ranking e envia a formatação para o grupo
                buscar_e_formatar_ranking(
                    supabase=supabase,
                    pool_id=pool_id,
                    mandante=partida['mandante_nome'],
                    visitante=partida['visitante_nome'],
                    placar_m=partida['home_score'],
                    placar_v=partida['away_score']
                )
                
        except Exception as e:
            print(f"Erro no processamento da partida: {e}")

    print("\nProcesso de atualização finalizado com sucesso!")

if __name__ == "__main__":
    atualizar_plataforma()