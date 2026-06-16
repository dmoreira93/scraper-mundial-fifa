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

# Carrega as variáveis de ambiente (útil para testes locais)
load_dotenv()

URL_SCRAPER = 'https://www.placardefutebol.com.br/copa-do-mundo'

# --- CONFIGURAÇÕES DE SEGURANÇA ---
# Sem "valor padrão". O script falha na hora se esquecer de por no GitHub Secrets.
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def enviar_mensagem_telegram(mensagem):
    """ Envia o disparo HTTP para a API de Bots do Telegram. """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print("🔔 Resumo enviado com sucesso ao Telegram!")
        else:
            print(f"⚠️ Erro ao enviar notificação do Telegram: {res.text}")
    except Exception as e:
        print(f"💥 Falha ao conectar com o serviço do Telegram: {e}")

def disparar_resumo_telegram(supabase: Client, jogos_formatados: list, championship_id: str):
    """
    Descobre o pool_id correto a partir do campeonato, busca o ranking e envia uma
    mensagem única consolidada com os jogos da rodada e a parcial.
    """
    try:
        # 1. Busca o Bolão (pool_id) vinculado a este campeonato
        pool_res = supabase.table('pools').select('id').eq('championship_id', championship_id).limit(1).execute()
        
        if not pool_res.data:
            print(f"Aviso: Nenhum bolão encontrado para o campeonato {championship_id}.")
            return
            
        pool_id = pool_res.data[0]['id']

        # 2. Busca o Ranking
        res_ranking = supabase.table('participations') \
            .select('points, exact_scores, users_custom(name, is_admin, is_ai)') \
            .eq('pool_id', pool_id) \
            .execute()

        if not res_ranking.data:
            print("Aviso: Nenhum dado de participação encontrado para montar o ranking.")
            return

        participantes_filtrados = []
        for item in res_ranking.data:
            user_info = item.get('users_custom', {})
            if user_info and not user_info.get('is_admin') and not user_info.get('is_ai'):
                participantes_filtrados.append({
                    'name': user_info.get('name', 'Participante'),
                    'points': item.get('points', 0),
                    'exact_scores': item.get('exact_scores', 0)
                })

        # Ordena: 1º Pontos, 2º Cravadas
        participantes_filtrados.sort(key=lambda x: (x['points'], x['exact_scores']), reverse=True)

        if len(participantes_filtrados) == 0:
            return

        top_3 = participantes_filtrados[:3]
        lanterna = participantes_filtrados[-1]

        # 3. Monta o Layout da Mensagem Única
        mensagem_linhas = [
            "🏆 <b>RESULTADOS PROCESSADOS</b> 🏆\n"
        ]
        
        # Adiciona a lista de jogos recém atualizados
        mensagem_linhas.extend(jogos_formatados)
        mensagem_linhas.append("\n📊 <b>PARCIAIS DO BOLÃO</b> 📊")
        
        medalhas = ["🥇", "🥈", "🥉"]
        for i, participante in enumerate(top_3):
            medalha = medalhas[i] if i < len(medalhas) else "🔹"
            mensagem_linhas.append(f"{medalha} {participante['name']} — {participante['points']} pts")

        mensagem_linhas.append("\n🦉 <b>Lanterna:</b>")
        mensagem_linhas.append(f"🚨 {lanterna['name']} — {lanterna['points']} pts")
        mensagem_linhas.append("\n🏃‍♂️ Acesse o app para conferir!")

        # Dispara
        enviar_mensagem_telegram("\n".join(mensagem_linhas))

    except Exception as err:
        print(f"Erro na geração do layout do Telegram: {err}")

def obter_jogos_do_site():
    print("-> Iniciando o scraper para buscar jogos...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
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
                if not time_casa_el or not time_fora_el:
                    continue
                
                time_casa = time_casa_el.get_text(strip=True)
                time_fora = time_fora_el.get_text(strip=True)
                placar_casa, placar_fora = '-', '-'
                
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
                continue
        return lista_jogos
    finally:
        if driver:
            driver.quit()
        print("-> Scraper finalizado.")

def atualizar_plataforma():
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_SERVICE_KEY")
    
    if not url or not key:
        print("Erro: Variáveis SUPABASE_URL e SUPABASE_SERVICE_KEY não encontradas.")
        return

    supabase: Client = create_client(url, key)
    print("-> Conectado ao Supabase com sucesso!")

    jogos_raspados = obter_jogos_do_site()
    if not jogos_raspados:
        print("Nenhum jogo foi encontrado. Encerrando.")
        return

    response = supabase.table('teams').select('id, name').execute()
    if not response.data:
        print("Erro ao buscar equipas.")
        return

    mapeamento_times = {time['name']: time['id'] for time in response.data}
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

    if not partidas_para_atualizar:
        print("\nNenhuma partida encerrada extraída nesta execução.")
        return

    print(f"\n-> Encontradas {len(partidas_para_atualizar)} partidas com resultado extraído.")
    
    jogos_atualizados_texto = []
    campeonato_id_alvo = None

    for partida in partidas_para_atualizar:
        try:
            # 1. Checa EXPLICITAMENTE se o jogo está 'scheduled' e obtém os IDs
            check = supabase.table('matches') \
                .select('id, championship_id') \
                .eq('home_team_id', partida['home_team_id']) \
                .eq('away_team_id', partida['away_team_id']) \
                .eq('status', 'scheduled') \
                .execute()

            # Se achou dados, significa que é um jogo inédito que ainda não foi atualizado!
            if check.data:
                match_data = check.data[0]
                match_id = match_data['id']
                
                if not campeonato_id_alvo:
                    campeonato_id_alvo = match_data.get('championship_id')

                # 2. Faz o update apontando direto para o ID da partida
                supabase.table('matches').update({
                    'home_score': partida['home_score'],
                    'away_score': partida['away_score'],
                    'status': 'finished'
                }).eq('id', match_id).execute()

                linha_jogo = f"⚽ {partida['mandante_nome']} {partida['home_score']} x {partida['away_score']} {partida['visitante_nome']}"
                print(f" - Atualizado no DB: {linha_jogo}")
                jogos_atualizados_texto.append(linha_jogo)

        except Exception as e:
            print(f"Erro no processamento da partida {partida['mandante_nome']}: {e}")

    # Fora do Loop: Se tivemos atualizações reais, mandamos a mensagem unificada
    if jogos_atualizados_texto and campeonato_id_alvo:
        disparar_resumo_telegram(supabase, jogos_atualizados_texto, campeonato_id_alvo)
    else:
        print("\n-> Todos os jogos encontrados já haviam sido marcados como 'finished' anteriormente. Nenhuma ação extra necessária.")

    print("\nProcesso finalizado!")

if __name__ == "__main__":
    atualizar_plataforma()
