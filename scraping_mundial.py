# update_supabase.py (VERSÃO FINAL 2.4 - Lógica com Status "Suspenso")

import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

URL_SCRAPER = 'https://www.placardefutebol.com.br/mundial-clubes-fifa'

def obter_jogos_do_site():
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

                # --- INÍCIO DA LÓGICA DE STATUS ATUALIZADA (v2.4) ---
                
                # 1. Pega todos os elementos relevantes
                placar_el = card.find('div', class_='match__md_card--scoreboard')
                status_el = card.find('div', class_='match__md_card--status')
                live_el = card.find('div', class_='match__md_card--live')
                datetime_el = card.find('div', class_='match__md_card--datetime')

                status_text = ""
                if status_el:
                    status_text = status_el.get_text(strip=True).lower()

                # 2. Define o status baseado em uma hierarquia de verificação
                TEXTOS_DE_JOGO_FINALIZADO = ['encerrado', 'fim de jogo', 'pên.']
                
                # Prioridade 1: Status explícito de "Suspenso"
                if 'suspenso' in status_text:
                    status = 'Suspenso'
                # Prioridade 2: Status explícito de "Finalizado"
                elif any(termo in status_text for termo in TEXTOS_DE_JOGO_FINALIZADO):
                    status = 'Encerrado'
                # Prioridade 3: Status de "Ao Vivo" ou "Intervalo"
                elif 'intervalo' in status_text:
                    status = 'Intervalo'
                elif live_el:
                    status = 'Ao Vivo'
                # Prioridade 4 (Correção principal): Se existe placar, mas não há status explícito, o jogo acabou.
                elif placar_el:
                    status = 'Encerrado'
                # Prioridade 5: Se tem data/hora, não começou
                elif datetime_el:
                    status = 'Não iniciado'
                # Fallback
                else:
                    status = 'Não definido'

                # 3. Processa o placar APENAS se o jogo foi classificado como Encerrado
                if status == 'Encerrado' and placar_el:
                    scores = placar_el.find_all('b')
                    if len(scores) >= 2:
                        try:
                            placar_casa = int(scores[0].get_text(strip=True))
                            placar_fora = int(scores[1].get_text(strip=True))
                        except (ValueError, TypeError):
                            placar_casa = scores[0].get_text(strip=True)
                            placar_fora = scores[1].get_text(strip=True)
                # --- FIM DA LÓGICA ATUALIZADA ---

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

# ... (o resto do seu código, incluindo atualizar_plataforma(), permanece igual) ...

if __name__ == "__main__":
    atualizar_plataforma()

def atualizar_plataforma():
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
        print("Erro ao buscar times do banco de dados.")
        return
    
    mapeamento_times = {time['name']: time['id'] for time in response.data}
    print(f"-> {len(mapeamento_times)} times carregados do banco.")

    partidas_para_atualizar = []
    for jogo in jogos_raspados:
        # A condição de filtro aqui permanece a mesma, pois a lógica de status já foi refinada acima.
        if jogo['status'] == 'Encerrado':
            mandante = jogo['mandante']
            visitante = jogo['visitante']

            if mandante in mapeamento_times and visitante in mapeamento_times:
                partidas_para_atualizar.append({
                    'home_team_id': mapeamento_times[mandante],
                    'away_team_id': mapeamento_times[visitante],
                    'home_score': jogo['placar_mandante'],
                    'away_score': jogo['placar_visitante'],
                    'is_finished': True
                })
            else:
                print(f"Aviso: Jogo '{mandante} vs {visitante}' ignorado (time não encontrado no banco).")
    
    if not partidas_para_atualizar:
        print("\nNenhuma partida encerrada para atualizar no momento.")
        return

    print(f"\n-> Encontradas {len(partidas_para_atualizar)} partidas com resultado para processar...")
    for partida in partidas_para_atualizar:
        try:
            res = supabase.table('matches').update({
                'home_score': partida['home_score'],
                'away_score': partida['away_score'],
                'is_finished': True
            }).match({
                'home_team_id': partida['home_team_id'],
                'away_team_id': partida['away_team_id'],
                'is_finished': False
            }).execute()
            
            if len(res.data) > 0:
                match_id = res.data[0]['id']
                print(f"   - Resultado da partida ID {match_id} atualizado. Disparando cálculo de pontos...")
                
                rpc_res = supabase.rpc('update_user_points_for_match', {'match_id_param': match_id}).execute()
                if rpc_res.error:
                    raise rpc_res.error

                print(f"   - Pontos para a partida ID {match_id} calculados com sucesso!")
        except Exception as e:
            print(f"Erro no processamento da partida: {e}")

    print("\nProcesso de atualização finalizado!")

if __name__ == "__main__":
    atualizar_plataforma()
