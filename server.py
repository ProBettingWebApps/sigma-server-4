import asyncio
import json
import random
import copy
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

try:
    import sigma_engine
except ImportError:
    class SigmaEngine:
        def calcola_punteggio_squadra(self, g, m): 
            return round(random.uniform(65.0, 85.0), 1), [{"nome": x["nome"], "ruolo": x["ruolo"], "voto_tattico": round(random.uniform(6.0, 8.0), 1)} for x in g]
        def elabora_turno_mercato(self, d): return d
    sigma_engine = SigmaEngine()

FILE_SALVATAGGIO = "fabbrica_save.json"

stato_gioco = {
    "fase": "MERCATO", "timer": 600, "stagione": 1, "giornata": 1,
    "status_log": "Sistema Protocollo Sigma 4.0 Online", "report_giornata": []
}

users_db = {} 
squadre_campionato = []
database_globale = []
archivio_storico = []

def salva_dati():
    dati = {
        "stato_gioco": stato_gioco, "users_db": users_db,
        "squadre_campionato": squadre_campionato, "database_globale": database_globale,
        "archivio_storico": archivio_storico
    }
    try:
        with open(FILE_SALVATAGGIO, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=4)
    except Exception: pass

def carica_dati():
    global stato_gioco, users_db, squadre_campionato, database_globale, archivio_storico
    if os.path.exists(FILE_SALVATAGGIO):
        try:
            with open(FILE_SALVATAGGIO, "r", encoding="utf-8") as f:
                dati = json.load(f)
                stato_gioco = dati.get("stato_gioco", stato_gioco)
                users_db = dati.get("users_db", users_db)
                squadre_campionato = dati.get("squadre_campionato", squadre_campionato)
                database_globale = dati.get("database_globale", database_globale)
                archivio_storico = dati.get("archivio_storico", [])
            print(">>> ATTENZIONE: DATI VECCHI CARICATI! CAMPIONATO NON AZZERATO! <<<")
            return True
        except Exception: pass
    return False

if not carica_dati():
    aggettivi = ["Real", "Atletico", "Sporting", "United", "Elite", "Pro", "Turbo", "Inter", "Virtus", "Fabbrica"]
    localita = ["Barge", "Envie", "Saluzzo", "Cuneo", "Piemonte", "Alpi", "Valle", "Torino", "Nexus", "Apex"]
    suffissi = ["FC", "Stars", "City", "Rovers", "Academy", "Power", "Calcio", "Team", "Dynamics", "Club"]
    nomi_generati = set()
    while len(squadre_campionato) < 49:
        nome_cand = f"{random.choice(aggettivi)} {random.choice(localita)} {random.choice(suffissi)}"
        if nome_cand not in nomi_generati:
            nomi_generati.add(nome_cand)
            val_rosa_start = random.randint(300000, 750000) 
            squadre_campionato.append({
                "nome": nome_cand, "punti_totali": 0.0, "ultimo_punteggio": 0.0,
                "budget": 1000000 - val_rosa_start, "valore_rosa": val_rosa_start
            })
    
    ruoli_disp = ["Portiere", "Difensore", "Centrocampista", "Attaccante"]
    nomi_base = ["Rossi", "Smith", "Garcia", "Muller", "Silva", "Kovacic", "Esposito", "Johnson", "Martinez", "Bianchi", "Russo", "Ferrari", "Gomez", "Weber", "Fernandez"]
    for i in range(1, 501):
        ruolo_scelto = random.choice(ruoli_disp)
        is_top = random.random() < 0.15
        if ruolo_scelto == "Portiere": val = random.randint(10000, 25000) if not is_top else random.randint(50000, 150000)
        elif ruolo_scelto == "Difensore": val = random.randint(10000, 35000) if not is_top else random.randint(60000, 250000)
        elif ruolo_scelto == "Centrocampista": val = random.randint(15000, 45000) if not is_top else random.randint(80000, 450000)
        else: val = random.randint(20000, 60000) if not is_top else random.randint(100000, 800000)
        val_arrotondato = round(val / 1000) * 1000
        database_globale.append({
            "id": i, "nome": f"{random.choice(nomi_base)} {i}", "ruolo": ruolo_scelto,
            "squadra": "Svincolato", "eta": random.randint(18, 35), 
            "valore": val_arrotondato, "valore_base": val_arrotondato,
            "media_voto": round(random.uniform(5.5, 7.2), 2), "forma_pct": random.randint(40, 100),
            "stelle": round(random.uniform(1.0, 5.0) * 2) / 2, "forza": random.randint(5, 9),
            "destrezza": random.randint(5, 9), "vitalita": random.randint(5, 9),
            "infortunato": 1 if random.random() < 0.02 else 0, "squalificato": 1 if random.random() < 0.01 else 0,
            "eventi": "", "fanta_voto": 0, "trend_valore": 0
        })
    salva_dati()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

connessioni_attive = {}

def costruisci_pacchetto_personale(username):
    my_data = users_db.get(username)
    if not my_data: return {"type": "errore_login", "msg": "Utente non trovato nel sistema"}

    dati_client = copy.deepcopy(database_globale)
    valore_rosa = sum(g["valore"] for g in dati_client if g["id"] in my_data["rosa"])
    
    for g in dati_client:
        g["nella_mia_rosa"] = (g["id"] in my_data["rosa"])
        g["titolare"] = (g["id"] in my_data["formazione"])

    classifica = []
    for u_name, u_data in users_db.items():
        v_rosa_u = sum(g["valore"] for g in dati_client if g["id"] in u_data["rosa"])
        
        # --- TUA REGOLA D'ACCIAIO: SE MENO DI 11 GIOCATORI, SEI MATEMATICAMENTE ULTIMO ---
        if len(u_data.get("formazione", [])) < 11:
            sig = -999999.0
        else:
            sig = (u_data["punti_totali"] * 50) + ((u_data["budget"] + v_rosa_u) / 1000)

        classifica.append({
            "pos": 0, "nome": u_name, "punti": u_data["punti_totali"],
            "record": u_data.get("punti_ultima_giornata", 0.0), "trend": 0.0, "forma_prob": 100,
            "patrimonio": u_data["budget"] + v_rosa_u, "valore_rosa": v_rosa_u,
            "sigma": sig,
            "is_me": (u_name == username), "rank_vip": "oro"
        })

    for s in squadre_campionato:
        classifica.append({
            "pos": 0, "nome": s["nome"], "punti": s["punti_totali"], "record": s.get("ultimo_punteggio", 0.0),
            "trend": round(random.uniform(-2, 4), 1), "forma_prob": random.randint(40, 95),
            "patrimonio": s.get("budget", 550000) + s.get("valore_rosa", 450000), 
            "valore_rosa": s.get("valore_rosa", 450000), 
            "sigma": (s["punti_totali"] * 50) + 1000,
            "is_me": False, "rank_vip": "bronzo"
        })

    classifica.sort(key=lambda x: x["sigma"], reverse=True)
    for idx, c in enumerate(classifica): c["pos"] = idx + 1

    return {
        "type": "stato_globale", "is_vip": True, "budget": my_data["budget"],
        "sponsor_attivo": my_data.get("sponsor", "Nessuno"),
        "scegli_talento": my_data.get("sponsor", "Nessuno") != "Nessuno" and not my_data.get("talento_scelto_mercato", False),
        "mercato_aperto": (stato_gioco["fase"] == "MERCATO"), "timer": stato_gioco["timer"],
        "stato_str": "MERCATO APERTO" if stato_gioco["fase"] == "MERCATO" else "SIMULAZIONE MATCH",
        "dati": dati_client, "classifica": classifica, "archivio": archivio_storico,
        "num_rosa": len(my_data["rosa"]), "num_titolari": len(my_data["formazione"]),
        "modulo": my_data["modulo"], "punti_giornata": my_data.get("punti_ultima_giornata", 0.0),
        "stagione": stato_gioco["stagione"], "giornata": stato_gioco["giornata"],
        "status": stato_gioco["status_log"], "report_giornata": stato_gioco["report_giornata"]
    }

async def aggiorna_tutti_i_client():
    for ws, uname in list(connessioni_attive.items()):
        try: await ws.send_json(costruisci_pacchetto_personale(uname))
        except: pass

@app.websocket("/ws/dashboard_client")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "ping": continue
            
            if action == "login":
                uname = data.get("teamname", "").strip()
                pin = str(data.get("pin", "")).strip()
                if not uname or not pin:
                    await websocket.send_json({"type": "errore_login", "msg": "Nome o PIN mancanti."})
                    continue
                if uname in users_db:
                    if users_db[uname]["pin"] != pin:
                        await websocket.send_json({"type": "errore_login", "msg": "PIN errato."})
                        continue
                else:
                    users_db[uname] = {
                        "pin": pin, "budget": 1000000, "rosa": [], "formazione": [],
                        "modulo": "4-4-2", "punti_totali": 0.0, "punti_ultima_giornata": 0.0,
                        "sponsor": "Nessuno"
                    }
                    salva_dati()
                connessioni_attive[websocket] = uname
                await websocket.send_json(costruisci_pacchetto_personale(uname))
                continue

            if websocket not in connessioni_attive: continue
            uname = connessioni_attive[websocket]
            my_data = users_db[uname]

            if action == "compra" and stato_gioco["fase"] == "MERCATO":
                g_id = data.get("id")
                giocatori = [g for g in database_globale if g["id"] == g_id]
                if giocatori and g_id not in my_data["rosa"] and my_data["budget"] >= giocatori[0]["valore"]:
                    my_data["budget"] -= giocatori[0]["valore"]
                    my_data["rosa"].append(g_id)
                    stato_gioco["status_log"] = f"{uname} ha acquistato {giocatori[0]['nome']}"
                    await aggiorna_tutti_i_client()

            elif action == "seleziona_sponsor":
                sponsor_scelto = data.get("sponsor", "Nessuno")
                if sponsor_scelto in ["Hunterbet Tech", "Sigma Main", "Profezia"]:
                    my_data["sponsor"] = sponsor_scelto
                    if sponsor_scelto == "Hunterbet Tech": my_data["budget"] += 50000
                    elif sponsor_scelto == "Sigma Main": my_data["budget"] += 100000
                    elif sponsor_scelto == "Profezia": my_data["budget"] += 30000
                    stato_gioco["status_log"] = f"{uname} ha siglato un accordo ufficiale con {sponsor_scelto}!"
                    await aggiorna_tutti_i_client()
                    
            elif action == "seleziona_talento":
                talento_scelto = data.get("talento", "Talento A")
                import random
                
                # 1. Creiamo il DNA del prospetto in base a cosa hai cliccato
                id_talento = f"SIGMA_{random.randint(1000, 9999)}"
                
                if talento_scelto == "Talento A":
                    giocatore_sigma = {"id": id_talento, "nome": "Prospetto Alpha", "ruolo": "DIF", "club": "Sigma Acad.", "valore": 15000, "fanta_voto": 6.0}
                elif talento_scelto == "Talento B":
                    giocatore_sigma = {"id": id_talento, "nome": "Prospetto Beta", "ruolo": "CEN", "club": "Sigma Acad.", "valore": 20000, "fanta_voto": 6.0}
                else:
                    giocatore_sigma = {"id": id_talento, "nome": "Prospetto Gamma", "ruolo": "ATT", "club": "Sigma Acad.", "valore": 25000, "fanta_voto": 6.0}
                    
                # 2. Lo inseriamo nel database globale del server
                database_globale.append(giocatore_sigma)
                
                # 3. Lo aggiungiamo fisicamente alla rosa della tua squadra
                if "rosa" not in my_data:
                    my_data["rosa"] = []
                my_data["rosa"].append(id_talento)
                
                # 4. Chiudiamo la porta: registriamo che il talento è stato preso
                my_data["talento_scelto_mercato"] = True 
                
                stato_gioco["status_log"] = f"{uname} ha acquisito {giocatore_sigma['nome']} dal Draft!"
                await aggiorna_tutti_i_client()
            elif action == "vendi" and stato_gioco["fase"] == "MERCATO":
                g_id = data.get("id")
                giocatori = [g for g in database_globale if g["id"] == g_id]
                if giocatori and g_id in my_data["rosa"]:
                    my_data["budget"] += giocatori[0]["valore"]
                    my_data["rosa"].remove(g_id)
                    if g_id in my_data["formazione"]: my_data["formazione"].remove(g_id)
                    await aggiorna_tutti_i_client()
            
            elif action == "schiera":
                g_id = data.get("id")
                if g_id in my_data["rosa"] and g_id not in my_data["formazione"] and len(my_data["formazione"]) < 11:
                    my_data["formazione"].append(g_id)
                    await websocket.send_json(costruisci_pacchetto_personale(uname))
            
            elif action == "panchina":
                g_id = data.get("id")
                if g_id in my_data["formazione"]: my_data["formazione"].remove(g_id)
                await websocket.send_json(costruisci_pacchetto_personale(uname))
            
            elif action == "set_modulo":
                my_data["modulo"] = data.get("modulo", "4-4-2")
                await websocket.send_json(costruisci_pacchetto_personale(uname))
            
            elif action == "admin_skip":
                # Lo skip interviene solo se siamo alla Giornata 1
                if stato_gioco["giornata"] == 1 and stato_gioco["fase"] == "MERCATO":
                    stato_gioco["timer"] = 1
                
            elif action == "prossima_giornata":
                if stato_gioco["fase"] == "ATTESA_GIORNATA":
                    stato_gioco["fase"] = "MERCATO"
                    # La giornata è già scattata a fine simulazione, quindi qui NON la aumentiamo,
                    # ci limitiamo a caricare il timer corretto:
                    
                    if stato_gioco["giornata"] == 1:
                        stato_gioco["timer"] = 600  # 10 minuti per la primissima asta 
                    elif stato_gioco["giornata"] in [6, 12, 18]:
                        stato_gioco["timer"] = 180  # 3 minuti 
                    else:
                        stato_gioco["timer"] = 60   # 1 minuto
                        
                    stato_gioco["status_log"] = f"Iniziata Giornata {stato_gioco['giornata']}. Prepara la formazione."
                    await aggiorna_tutti_i_client()
                
    except WebSocketDisconnect:
        if websocket in connessioni_attive: del connessioni_attive[websocket]

async def game_loop():
    global database_globale, archivio_storico
    while True:
        try:
            await asyncio.sleep(1)
            stato_gioco["timer"] -= 1
            
            if stato_gioco["timer"] <= 0:
                if stato_gioco["fase"] == "MERCATO":
                    stato_gioco["fase"] = "SIMULAZIONE"
                    stato_gioco["timer"] = 15
                    stato_gioco["status_log"] = "Simulazione tattica in corso..."
                    for ws in list(connessioni_attive.keys()):
                        try: await ws.send_json({"type": "simulazione_avvio"})
                        except: pass
                
                elif stato_gioco["fase"] == "SIMULAZIONE":
                    report_completo = [f"=== REPORT GIORNATA {stato_gioco['giornata']} ==="]
                    for u_name, u_data in users_db.items():
                        giocatori_in_campo = [g for g in database_globale if g["id"] in u_data["formazione"]]
                        
                        if len(giocatori_in_campo) < 11:
                            punti = 0.0
                            report_str = f"{u_name}: 0.0 pt | (Formazione Incompleta: Atleti {len(giocatori_in_campo)}/11)"
                        else:
                            voti_dettaglio = []
                            for g in giocatori_in_campo:
                                voto_prestazione = round(random.uniform(5.0, 8.5), 1)
                                g["fanta_voto"] = voto_prestazione
                                cognome = g['nome'].split()[0]
                                voti_dettaglio.append(f"{cognome} {voto_prestazione}")
                            try:
                                punti, _ = sigma_engine.calcola_punteggio_squadra(giocatori_in_campo, u_data.get("modulo", "4-4-2"))
                                modulo_attivo = u_data.get("modulo", "4-4-2")
                                if modulo_attivo == "3-5-2": punti += 2.0
                                elif modulo_attivo == "4-3-3": punti -= 0.5
                            except:
                                punti = round(random.uniform(65.0, 85.0), 1)
                            report_str = f"{u_name}: {punti} pt | Voti: " + ", ".join(voti_dettaglio)
                            
                        u_data["punti_ultima_giornata"] = punti
                        u_data["punti_totali"] += punti
                        report_completo.append(report_str)
                    
                    stato_gioco["report_giornata"] = report_completo
                    
                    try: database_globale = sigma_engine.elabora_turno_mercato(database_globale)
                    except: pass

                    for s in squadre_campionato:
                        punti_avv = round(random.uniform(60, 88), 1)
                        s["ultimo_punteggio"] = punti_avv
                        s["punti_totali"] += punti_avv
                        variazione_mercato = random.randint(-40000, 40000)
                        s["valore_rosa"] += variazione_mercato
                        s["budget"] -= variazione_mercato

                    for g in database_globale:
                        moltiplicatore = random.uniform(0.85, 1.15) 
                        vecchio_valore = g.get("valore", 50000)
                        nuovo_valore = round((vecchio_valore * moltiplicatore) / 1000) * 1000
                        tetto_massimo_personale = g.get("valore_base", 50000) * 3
                        if nuovo_valore < 5000: nuovo_valore = 5000
                        if nuovo_valore > tetto_massimo_personale: nuovo_valore = tetto_massimo_personale
                        g["trend_valore"] = nuovo_valore - vecchio_valore
                        g["valore"] = nuovo_valore
                    
                    # === FINE SIMULAZIONE: AGGIORNIAMO LA GIORNATA E ATTENDIAMO IL CONTINUA ===
                    stato_gioco["fase"] = "ATTESA_GIORNATA"
                    stato_gioco["giornata"] += 1
                    stato_gioco["timer"] = 0 # Aspetta il bottone "Continua la Partita"
                    
                    if stato_gioco["giornata"] > 24:
                        stato_gioco["status_log"] = "Campionato Terminato! WIPE-OUT in corso..."
                        classifica_finale = []
                        for un, ud in users_db.items():
                            v_r = sum(g["valore"] for g in database_globale if g["id"] in ud["rosa"])
                            if len(ud.get("formazione", [])) < 11:
                                sig = -999999.0
                            else:
                                sig = (ud["punti_totali"] * 50) + ((ud["budget"] + v_r) / 1000)
                            classifica_finale.append({"nome": un, "sigma": sig})
                        for s in squadre_campionato:
                            classifica_finale.append({"nome": s["nome"], "sigma": (s["punti_totali"] * 50) + 1000})
                            
                        classifica_finale.sort(key=lambda x: x["sigma"], reverse=True)
                        archivio_storico.append({
                            "stagione": stato_gioco["stagione"],
                            "vincitore": classifica_finale[0]["nome"] if len(classifica_finale)>0 else "-",
                            "secondo": classifica_finale[1]["nome"] if len(classifica_finale)>1 else "-",
                            "terzo": classifica_finale[2]["nome"] if len(classifica_finale)>2 else "-",
                            "sigma": classifica_finale[0]["sigma"] if len(classifica_finale)>0 else 0.0
                        })
                        
                        stato_gioco["giornata"] = 1
                        stato_gioco["stagione"] += 1
                        for u_name, u_data in users_db.items():
                            u_data["rosa"] = []
                            u_data["formazione"] = []
                            u_data["budget"] = 1000000
                            u_data["punti_totali"] = 0.0
                            u_data["punti_ultima_giornata"] = 0.0
                        for s in squadre_campionato:
                            s["punti_totali"] = 0.0
                            s["ultimo_punteggio"] = 0.0
                            s["valore_rosa"] = random.randint(300000, 750000)
                            s["budget"] = 1000000 - s["valore_rosa"]
                        for g in database_globale:
                            g["valore"] = g.get("valore_base", 50000)
                            g["trend_valore"] = 0
                        
                        stato_gioco["status_log"] = "Stagione Conclusa! Nuovo Campionato Pronto."
                    else:
                        stato_gioco["status_log"] = "Turno Concluso! Statistiche aggiornate."

                    salva_dati()
                    await asyncio.sleep(0.5)
                    await aggiorna_tutti_i_client()

            else:
                if stato_gioco["fase"] == "MERCATO":
                    msg = {"type": "tick", "timer": stato_gioco["timer"], "mercato_aperto": True, "stato_str": "MERCATO APERTO"}
                    for ws in list(connessioni_attive.keys()):
                        try: await ws.send_json(msg)
                        except: pass

        except Exception as e:
            print(f"ERRORE CRITICO MOTORE SALVATO: {e}")
            await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    print("\n========================================================")
    print(">>> SERVER AVVIATO. REGOLE SIGMA 4.0 ATTIVATE <<<")
    print("========================================================\n")
    asyncio.create_task(game_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)