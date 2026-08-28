"""
Web app locale Streamlit con Modulo Elastico 4.0.
"""

from __future__ import annotations

import os
import time
os.environ['TZ'] = 'Europe/Rome'
try:
    time.tzset()
except AttributeError:
    pass

import html
import json
import math
import re
import sqlite3
import statistics
import uuid
import pytz
from dataclasses import asdict, dataclass
from datetime import date, datetime
import pandas as pd
import io
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ippica_inserimento import (
    DB_PATH,
    SOGLIA_QUOTA_VINCENTE_SIGMA,
    Corsa,
    SchedaCavallo,
    carica_cavalli_sessione_da_db,
    etichetta_cavallo,
    init_database,
    estrai_dati,
    parse_partenti_testo_grezzo,
    partente_grezzo_a_record_dict,
)

STORICO_GARE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "storico_gare.txt",
)

def ora_italiana():
    return datetime.now(pytz.timezone('Europe/Rome'))

# Funzione di protezione password
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.markdown("### 🔒 Accesso Riservato — IPPICA STAR!")
    pwd_input = st.text_input("Inserisci la Password di Accesso:", type="password")
    
    if st.button("Accedi"):
        if pwd_input == "horse2026":
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Password errata. Riprova.")
    
    return False

# Blocca l'esecuzione se non autenticato
if not check_password():
    st.stop()

st.set_page_config(
    layout="wide",
    page_title="Sigma 4.0 TV",
    initial_sidebar_state="collapsed",
)

st.markdown("""
    <style>
    /* Forza il testo nero e lo sfondo bianco per la text area per contrasto assoluto */
    textarea[data-baseweb="textarea"], div[data-baseweb="base-input"] > textarea, .stTextArea textarea {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        background-color: #ffffff !important;
        font-weight: bold !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(180deg, #2A2D34 0%, #141518 100%) !important;
    }
    [data-testid="stHeader"] {
        background-color: transparent !important;
    }
    .stApp, p, span, h1, h2, h3, h4, h5, h6, label, li {
        color: #F3F4F6 !important;
    }
    </style>
""", unsafe_allow_html=True)




RAW_RESULTS_RE = re.compile(
    r"(?P<posizione>\d|\d{2})\s*"
    r"(?P<data>\d{1,2}/\d{1,2}/\d{2,4})\s*"
    r"(?P<ippodromo>[A-Za-z]+)\s*"
    r"(?P<distanza>\d+)\s*"
    r"(?P<unita>yards|meters)\s*"
    r"(?P<partente>\d+)\s*"
    r"(?P<fantino>[A-Za-z\s.']+?)\s*"
    r"(?P<quota>\d+[.,]\d{2})",
    re.IGNORECASE,
)

PALINSESTO_COLUMNS = [
    "Data Evento",
    "Orario",
    "Numero Corsa",
    "Ippodromo Evento",
    "Numero Partente",
    "Cavallo",
    "Data Prestazione",
    "Posizione",
    "Ippodromo Prestazione",
    "Distanza",
    "Unità",
    "Partenza",
    "Fantino",
    "Quota",
]

DATI_GARA_COLUMNS = [
    "N°",
    "Nome",
    "Età",
    "Rating",
    "Ultimi Arrivi",
    "Forma_Storica",
    "Quote Valide",
]

# Intestazione partente a 3 righe: Numero / Codice gabbia / Nome
NUMERO_PARTENTE_RIGA_RE = re.compile(r"^\s*(?P<numero>\d{1,2})\s*$")
CODICE_GABBIA_RIGA_RE = re.compile(
    r"^\s*(?P<codice>[A-Za-z]\d{1,2}|G\d{1,2})\s*$"
)
NOME_CAVALLO_RIGA_RE = re.compile(
    r"^\s*(?P<nome>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ0-9'\.\- ]{1,80})\s*$"
)
AGE_RE = re.compile(r"(?i)\b(?P<eta>\d{1,2}YO)\b")
RATING_RE = re.compile(r"(?i)Rating\s*:\s*(?P<rating>\d+(?:[.,]\d+)?)")
ULTIMI_ARRIVI_RE = re.compile(
    r"(?i)Ultimi\s+arrivi\s*:?\s*(?P<ultimi>"
    r"(?:\d{1,2}|[A-Za-z]{1,6})(?:\s*-\s*(?:\d{1,2}|[A-Za-z]{1,6}))+"
    r"|\d+"
    r"|[A-Za-z]{1,6})"
)
FORMA_STORICA_SEQUENZA_RE = re.compile(
    r"(?i)\b(?P<form>(?:\d{1,2}|[A-Za-z]{1,6})"
    r"(?:\s*-\s*(?:\d{1,2}|[A-Za-z]{1,6}))+)\b"
)
QUOTA_DECIMALE_RE = re.compile(r"\b\d+[.,]\d{1,2}\b")
ULTIMI_ARRIVI_ETICHETTA_RE = re.compile(r"(?i)ultimi\s+arrivi")
DICITURA_RITIRO_PARTENTE_RE = re.compile(
    r"(?i)(?:\bnon\s+partente\b|\britirat[oa]\b)"
)
PESO_KG_RIGA_RE = re.compile(r"(?i)\bkg\b")
RIGA_METRI_DISTANZA_RE = re.compile(r"(?i)^\s*\d{3,5}\s*metri\s*$")
ULTIMI_ARRIVO_LETTERALE_RE = re.compile(r"(?i)^[A-Z]{1,6}$")
QUANTA_PENALITA_ARRIVO_LETTERALE = 99.0
PUNTI_ARRIVO_FORMA_STORICA = {
    1: 10.0,
    2: 7.0,
    3: 5.0,
    4: 3.0,
    5: 1.0,
}
MAX_PUNTI_ARRIVO_FORMA = 10.0
# Galoppo: massimo 2 colonne utili per partente (Vincente + Piazzato).
MAX_QUOTE_MERCATO_UTILI = 2
IPPODROMO_CORSA_RE = re.compile(
    r"(?P<ippodromo_corsa>[^\n\r]+?\s*/\s*Corsa\s+\d+)",
    re.IGNORECASE,
)
DATA_GARA_INTESTAZIONE_RE = re.compile(
    r"\b(?P<data>\d{1,2}/\d{1,2}/\d{2,4})\b"
)
# Orario gara SOLO subito dopo la data (stessa riga o riga successiva), mai il primo HH:MM del testo.
DATA_ORARIO_GARA_ANCORATO_RE = re.compile(
    r"(?P<data>\d{2}/\d{2}/\d{4})\s+(?P<orario>\d{1,2}:\d{2})\b",
    re.DOTALL,
)
RIGA_DATA_GARA_RE = re.compile(r"^\s*(?P<data>\d{1,2}/\d{1,2}/\d{4})\s*$")
RIGA_ORARIO_GARA_RE = re.compile(r"^\s*(?P<orario>\d{1,2}:\d{2})\s*$")
DISTANZA_GARA_RE = re.compile(
    r"(?is)Distanza\s*(?P<distanza>\d{3,5})"
)
PREMIO_GARA_RE = re.compile(
    r"(?im)^Nome\s+premio\s*\r?\n\s*(?P<premio>.+?)\s*$"
)
PREMIO_RIGA_DIRETTO_RE = re.compile(
    r"(?im)^Premio\s+(?P<premio>.+?)\s*$"
)
RIGA_CORSA_NUMERO_RE = re.compile(r"(?i)^Corsa\s+(?P<numero>\d{1,2})\s*$")
RIGA_TABella_ORARI_PALINSESTO_RE = re.compile(
    r"^\s*(?P<ordine>\d{1,2})\s+(?P<orario>\d{1,2}:\d{2})\s*$"
)
PARTENTE_BLOCCO_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?P<numero>(?:[1-9]|1[0-2]))[ \t]*\r?\n"
    r"(?:[ \t]*\r?\n)*"
    r"(?:(?P<gabbia>G\d{1,2}|[A-Za-z]\d{1,2})[ \t]*\r?\n[ \t]*)?"
)


def estrai_corse_grezze(scheda_testo: str) -> list[Corsa]:
    """Estrae esclusivamente risultati completi dalla stringa fusa."""
    corse_trovate: list[Corsa] = []
    for match in RAW_RESULTS_RE.finditer(scheda_testo.strip()):
        corse_trovate.append(
            Corsa(
                posizione=match.group("posizione"),
                data_gara=match.group("data"),
                ippodromo=match.group("ippodromo"),
                distanza_m=match.group("distanza"),
                unita_misura=match.group("unita").lower(),
                parte=match.group("partente"),
                fantino=" ".join(match.group("fantino").split()),
                quota=match.group("quota").replace(",", "."),
                raw_riga=match.group(0),
            )
        )
    return corse_trovate


def crea_scheda_da_risultati(
    scheda_testo: str,
    numero_partente: int,
) -> SchedaCavallo | None:
    corse = estrai_corse_grezze(scheda_testo)
    if not corse:
        return None
    forma_automatica = ",".join(corsa.posizione for corsa in corse)
    return SchedaCavallo(
        numero_partente=numero_partente,
        nome=etichetta_cavallo(numero_partente),
        note="",
        eta="",
        sesso="",
        allenatore="",
        flatsix=forma_automatica,
        genealogia="",
        proprietario="",
        corse=corse,
    )


def report_risultati_grezzi(scheda: SchedaCavallo) -> str:
    posizioni = [int(c.posizione) for c in scheda.corse]
    quote = [float(c.quota) for c in scheda.corse]
    sotto_sigma = [q for q in quote if q < 1.60]
    risultato = calcola_modulo_elastico(0, scheda)
    recency = (
        f"{risultato.punteggio_temporale:.2f}/100"
        if risultato.punteggio_temporale is not None
        else "non calcolabile"
    )
    regressione = (
        f"{risultato.regressione:+.3f} ({risultato.regression_label})"
        if risultato.regressione is not None
        else risultato.regression_label
    )
    quanta = (
        f"{risultato.quanta * 100:.2f}/100"
        if risultato.quanta is not None
        else "non calcolabile"
    )
    modulo = (
        f"{risultato.coefficiente:.2f}/100"
        if risultato.coefficiente is not None
        else "non calcolabile"
    )
    quota_ponderata = (
        f"{risultato.quota_storica_ponderata:.2f}"
        if risultato.quota_storica_ponderata is not None
        else "non calcolabile"
    )
    lines = [
        f"=== {scheda.nome} ===",
        f"Corse lette: {len(scheda.corse)}",
        f"Posizioni: {', '.join(str(p) for p in posizioni)}",
        f"Media matematica posizioni: {statistics.mean(posizioni):.2f}",
        f"Quota media completa: {statistics.mean(quote):.2f}",
        f"Target Sigma (Quota Storica Ponderata): {quota_ponderata}",
        f"Punteggio Temporale (Recency): {recency}",
        f"Indice Regression: {regressione}",
        f"Indice Quanta: {quanta}",
        f"Modulo Elastico Sigma: {modulo}",
        f"Quote sotto soglia Sigma 1.60: {len(sotto_sigma)} "
        "(importate, ma escluse dal targeting Value Bet)",
        f"Targeting: {risultato.filtro_value_bet}",
    ]
    if risultato.anomalie:
        lines.append("Anomalie Elastiche (prioritarie):")
        lines.extend(f"- {anomalia}" for anomalia in risultato.anomalie)
    else:
        lines.append("Anomalie Elastiche: nessuna rilevata")
    return "\n".join(lines)


@dataclass(frozen=True)
class RisultatoElastico:
    cavallo_id: int
    numero_partente: int
    nome: str
    forma: str
    media_posizioni: float | None
    corse_disputate: int
    regolarita: float | None
    coefficiente: float | None
    semaforo: str
    descrizione_semaforo: str
    quota_media_completa: float | None
    quote_primarie: int
    quote_sotto_soglia: int
    filtro_value_bet: str
    regressione: float | None
    quanta: float | None
    punteggio_temporale: float | None
    regression_label: str
    anomalie: tuple[str, ...]
    quota_storica_ponderata: float | None


def _parse_data_corsa(value: str) -> date | None:
    try:
        giorno, mese, anno = (int(parte) for parte in value.split("/"))
        if anno < 100:
            anno += 2000
        return date(anno, mese, giorno)
    except (TypeError, ValueError):
        return None


def _osservazioni_cronologiche(
    scheda: SchedaCavallo,
) -> list[tuple[date, int, float]]:
    oggi = date.today()
    osservazioni: list[tuple[date, int, float]] = []
    for corsa in scheda.corse:
        data_corsa = _parse_data_corsa(corsa.data_gara)
        try:
            posizione = int(corsa.posizione)
            quota = float(corsa.quota.replace(",", "."))
        except (TypeError, ValueError):
            continue
        # Una data futura viene importata ma non usata come prestazione passata.
        if data_corsa is not None and data_corsa <= oggi and posizione > 0:
            osservazioni.append((data_corsa, posizione, quota))
    return sorted(osservazioni, key=lambda elemento: elemento[0])


def _punteggio_recency(
    osservazioni: list[tuple[date, int, float]],
) -> float | None:
    """70% alle corse entro 60 giorni, 30% a quelle precedenti."""
    if not osservazioni:
        return None
    oggi = date.today()
    recenti = [o for o in osservazioni if (oggi - o[0]).days <= 60]
    storiche = [o for o in osservazioni if (oggi - o[0]).days > 60]

    def punteggio_gruppo(
        gruppo: list[tuple[date, int, float]],
        recente: bool,
    ) -> float:
        valori: list[tuple[float, float]] = []
        for data_corsa, posizione, _quota in gruppo:
            giorni = (oggi - data_corsa).days
            qualita = 1.0 / (1.0 + max(posizione - 1, 0) / 4.0)
            if recente:
                peso = 1.0 if giorni <= 45 else max(0.70, 1.0 - (giorni - 45) / 50)
            else:
                peso = 1.0 / (1.0 + (giorni - 60) / 180.0)
            valori.append((qualita, peso))
        totale_pesi = sum(peso for _qualita, peso in valori)
        return sum(qualita * peso for qualita, peso in valori) / totale_pesi

    if recenti and storiche:
        risultato = (
            0.70 * punteggio_gruppo(recenti, True)
            + 0.30 * punteggio_gruppo(storiche, False)
        )
    elif recenti:
        risultato = punteggio_gruppo(recenti, True)
    else:
        risultato = punteggio_gruppo(storiche, False)
    return risultato * 100.0


def _quota_storica_ponderata(
    osservazioni: list[tuple[date, int, float]],
) -> float | None:
    """Media temporale di sole quote reali >=1.60, senza stime simulate."""
    oggi = date.today()
    quote_pesate: list[tuple[float, float]] = []
    for data_corsa, _posizione, quota in osservazioni:
        if quota < 1.60:
            continue
        giorni = (oggi - data_corsa).days
        if giorni <= 45:
            peso = 1.0
        elif giorni <= 60:
            peso = 0.70
        else:
            peso = 0.30 / (1.0 + (giorni - 60) / 180.0)
        quote_pesate.append((quota, peso))
    if not quote_pesate:
        return None
    totale_pesi = sum(peso for _quota, peso in quote_pesate)
    return (
        sum(quota * peso for quota, peso in quote_pesate)
        / totale_pesi
    )


def _regression_cronologica(
    osservazioni: list[tuple[date, int, float]],
) -> tuple[float | None, float, str]:
    if len(osservazioni) < 2:
        return None, 0.50, "Dati insufficienti per il trend"
    posizioni = [posizione for _data, posizione, _quota in osservazioni]
    x_media = (len(posizioni) - 1) / 2
    y_media = statistics.mean(posizioni)
    denominatore = sum((i - x_media) ** 2 for i in range(len(posizioni)))
    slope = (
        sum(
            (i - x_media) * (posizione - y_media)
            for i, posizione in enumerate(posizioni)
        )
        / denominatore
    )
    indice = max(0.0, min(1.0, 0.50 - slope / 4.0))
    if slope < -0.25:
        label = "Miglioramento"
    elif slope > 0.25:
        label = "Peggioramento"
    else:
        label = "Stabile"
    return slope, indice, label


def _anomalie_elastiche(
    osservazioni: list[tuple[date, int, float]],
) -> tuple[list[str], int]:
    anomalie: list[str] = []
    priorita = 0
    for data_corsa, posizione, quota in osservazioni:
        if posizione == 1 and quota >= 10.0:
            anomalie.append(
                f"POSITIVA {data_corsa:%d/%m/%Y}: vittoria a quota {quota:.2f}"
            )
            priorita = 1
        elif posizione >= 8 and quota <= 3.0:
            anomalie.append(
                f"NEGATIVA {data_corsa:%d/%m/%Y}: posizione {posizione} "
                f"a quota {quota:.2f}"
            )
            priorita = -1
    return anomalie, priorita


def calcola_modulo_elastico(
    cavallo_id: int,
    scheda: SchedaCavallo,
) -> RisultatoElastico:
    """Indice Sigma 4.0 basato su posizioni e quote realmente estratte."""
    osservazioni = _osservazioni_cronologiche(scheda)
    posizioni = [posizione for _data, posizione, _quota in osservazioni]
    media = statistics.mean(posizioni) if posizioni else None
    quote = [quota for _data, _posizione, quota in osservazioni]
    quota_media = statistics.mean(quote) if quote else None
    quote_primarie = [q for q in quote if q >= 1.60]
    quote_sotto_soglia = len(quote) - len(quote_primarie)
    punteggio_temporale = _punteggio_recency(osservazioni)
    regressione, punteggio_regressione, regression_label = (
        _regression_cronologica(osservazioni)
    )
    anomalie, priorita_anomalia = _anomalie_elastiche(osservazioni)
    quota_ponderata = _quota_storica_ponderata(osservazioni)

    if media is None:
        regolarita = None
        quanta = None
        coefficiente = None
        semaforo = "⚪"
        descrizione = "Dati forma insufficienti"
    else:
        deviazione = statistics.pstdev(posizioni) if len(posizioni) > 1 else 0.0
        regolarita = max(0.0, 1.0 - deviazione / max(media, 1.0))

        if len(quote_primarie) > 1:
            media_quote_primarie = statistics.mean(quote_primarie)
            dispersione_quote = statistics.pstdev(quote_primarie)
            stabilita_quote = max(
                0.0,
                1.0 - dispersione_quote / max(media_quote_primarie, 0.01),
            )
        elif len(quote_primarie) == 1:
            stabilita_quote = 0.5
        else:
            stabilita_quote = 0.0

        quanta = (regolarita + stabilita_quote) / 2.0
        esperienza = min(len(posizioni) / 6.0, 1.0)
        componente_temporale = (
            punteggio_temporale / 100.0
            if punteggio_temporale is not None
            else 0.0
        )
        coefficiente_lineare = 100.0 * (
            0.45 * componente_temporale
            + 0.20 * regolarita
            + 0.15 * punteggio_regressione
            + 0.10 * stabilita_quote
            + 0.10 * esperienza
        )

        # L'anomalia più recente prevale sul risultato lineare.
        if priorita_anomalia > 0:
            coefficiente = max(85.0, coefficiente_lineare)
            quanta = min(1.0, quanta + 0.25)
        elif priorita_anomalia < 0:
            coefficiente = min(35.0, coefficiente_lineare)
            quanta = max(0.0, quanta - 0.25)
        else:
            coefficiente = coefficiente_lineare

        if media <= 3.0:
            semaforo = "🟢"
            descrizione = "Luce Verde — forma eccellente e alta elasticità"
        elif media <= 5.5:
            semaforo = "🟡"
            descrizione = "Luce Gialla — condizione intermedia / incerta"
        else:
            semaforo = "🔴"
            descrizione = "Luce Rossa — trend in calo / sconsigliato"

    if not quote:
        filtro_value_bet = "Non valutabile: quote mancanti"
    elif not quote_primarie:
        filtro_value_bet = "⛔ Scarto Sigma: tutte le quote sono sotto 1.60"
    elif coefficiente is not None and coefficiente >= 70.0:
        filtro_value_bet = (
            "🔎 Candidata Value Bet Sigma — richiede verifica della quota attuale"
        )
    else:
        filtro_value_bet = "Non selezionata dal targeting Regression/Quanta"

    return RisultatoElastico(
        cavallo_id=cavallo_id,
        numero_partente=scheda.numero_partente,
        nome=scheda.nome,
        forma="-".join(str(p) for p in posizioni),
        media_posizioni=media,
        corse_disputate=len(scheda.corse),
        regolarita=regolarita,
        coefficiente=coefficiente,
        semaforo=semaforo,
        descrizione_semaforo=descrizione,
        quota_media_completa=quota_media,
        quote_primarie=len(quote_primarie),
        quote_sotto_soglia=quote_sotto_soglia,
        filtro_value_bet=filtro_value_bet,
        regressione=regressione,
        quanta=quanta,
        punteggio_temporale=punteggio_temporale,
        regression_label=regression_label,
        anomalie=tuple(anomalie),
        quota_storica_ponderata=quota_ponderata,
    )


def analizza_modulo_elastico(
    concorrenti: list[tuple[int, SchedaCavallo]],
) -> list[RisultatoElastico]:
    risultati = [calcola_modulo_elastico(cid, scheda) for cid, scheda in concorrenti]
    return sorted(
        risultati,
        key=lambda r: (
            r.coefficiente is not None,
            r.coefficiente if r.coefficiente is not None else -math.inf,
        ),
        reverse=True,
    )


def genera_sintesi_sigma(
    risultati: list[RisultatoElastico],
) -> tuple[RisultatoElastico | None, str, bool]:
    """Elegge un target solo se quote e moduli hanno dati sufficienti."""
    valutabili = [
        risultato
        for risultato in risultati
        if (
            risultato.coefficiente is not None
            and risultato.quota_storica_ponderata is not None
            and risultato.quota_storica_ponderata >= 1.60
            and risultato.corse_disputate >= 2
            and risultato.regressione is not None
            and risultato.quanta is not None
        )
    ]
    if not valutabili:
        return None, "Assenza di dati - Impossibile generare pronostico", False

    anomalie_positive = [
        risultato
        for risultato in valutabili
        if any(
            anomalia.startswith("POSITIVA")
            for anomalia in risultato.anomalie
        )
    ]

    if anomalie_positive:
        # Priorità assoluta Quanta: una anomalia positiva prevale sul ranking
        # lineare; tra più anomalie prevale l'Indice Sigma finale.
        target = max(
            anomalie_positive,
            key=lambda risultato: risultato.coefficiente or 0.0,
        )
        priorita_anomalia = True
    else:
        candidati_lineari = [
            risultato
            for risultato in valutabili
            if (
                not any(
                    anomalia.startswith("NEGATIVA")
                    for anomalia in risultato.anomalie
                )
                and (risultato.coefficiente or 0.0) >= 70.0
                and risultato.quanta >= 0.50
            )
        ]
        if not candidati_lineari:
            return (
                None,
                "Assenza di dati - Impossibile generare pronostico",
                False,
            )
        target = max(
            candidati_lineari,
            key=lambda risultato: risultato.coefficiente or 0.0,
        )
        priorita_anomalia = False

    motivazioni: list[str] = []
    if priorita_anomalia:
        motivazioni.append(
            "il Modulo Quanta rileva un'anomalia elastica positiva, "
            "prioritaria sulla forma lineare"
        )
    motivazioni.append(
        f"il Modulo Regression indica «{target.regression_label.lower()}»"
    )
    motivazioni.append(
        f"il Modulo Quanta è {target.quanta * 100:.1f}/100"
    )
    motivazioni.append(
        f"il Modulo Elastico/Sigma è {target.coefficiente:.1f}/100"
    )
    motivazioni.append(
        "il Target Sigma (Quota Storica Ponderata) è "
        f"{target.quota_storica_ponderata:.2f}"
    )

    quote_filtrate = sum(
        risultato.quote_sotto_soglia for risultato in risultati
    )
    testo = (
        f"Il Cavallo N.{target.numero_partente} è il Top Target Sigma: "
        + "; ".join(motivazioni)
        + ". "
        + f"Quote storiche sotto 1.60 filtrate dal targeting: {quote_filtrate}. "
        + "Il target richiede verifica sulla quota attuale prima di qualsiasi decisione."
    )
    return target, testo, priorita_anomalia


def _elimina_sessione_corsa(sessione_corsa: str) -> int:
    """Elimina cavalli e storico appartenenti alla sessione corrente."""
    with sqlite3.connect(DB_PATH) as conn:
        ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM cavalli WHERE sessione_corsa = ?",
                (sessione_corsa,),
            )
        ]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM ultime_corse WHERE cavallo_id IN ({placeholders})",
                ids,
            )
            conn.execute(
                f"DELETE FROM cavalli WHERE id IN ({placeholders})",
                ids,
            )
        conn.execute(
            "DELETE FROM palinsesto_sigma WHERE sessione_corsa = ?",
            (sessione_corsa,),
        )
        conn.commit()
    return len(ids)


def _riscrivi_corsa_da_memoria(
    sessione_corsa: str,
    cavalli: list[SchedaCavallo],
) -> None:
    """Sostituisce atomicamente i record della corsa con quelli in memoria."""
    with sqlite3.connect(DB_PATH) as conn:
        ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM cavalli WHERE sessione_corsa = ?",
                (sessione_corsa,),
            )
        ]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM ultime_corse WHERE cavallo_id IN ({placeholders})",
                ids,
            )
            conn.execute(
                f"DELETE FROM cavalli WHERE id IN ({placeholders})",
                ids,
            )

        for scheda in cavalli:
            cur = conn.execute(
                """
                INSERT INTO cavalli (
                    nome, note, eta, sesso, allenatore, flatsix, totalsix,
                    genealogia, proprietario, sessione_corsa,
                    numero_partente, inserito_il
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scheda.nome,
                    scheda.note,
                    scheda.eta,
                    scheda.sesso,
                    scheda.allenatore,
                    scheda.flatsix,
                    scheda.flatsix,
                    scheda.genealogia,
                    scheda.proprietario,
                    sessione_corsa,
                    scheda.numero_partente,
                    ora_italiana().isoformat(timespec="seconds"),
                ),
            )
            nuovo_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO ultime_corse (
                    cavallo_id, posizione, data_gara, ippodromo,
                    distanza_m, unita_misura, parte, fantino,
                    quota, raw_riga
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        nuovo_id,
                        corsa.posizione,
                        corsa.data_gara,
                        corsa.ippodromo,
                        corsa.distanza_m,
                        corsa.unita_misura,
                        corsa.parte,
                        corsa.fantino,
                        corsa.quota,
                        corsa.raw_riga,
                    )
                    for corsa in scheda.corse
                ],
            )
        conn.commit()


def _palinsesto_vuoto() -> pd.DataFrame:
    return pd.DataFrame(columns=PALINSESTO_COLUMNS)


def _init_palinsesto_database() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS palinsesto_sigma (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessione_corsa TEXT NOT NULL,
                data_evento TEXT NOT NULL,
                orario TEXT NOT NULL,
                numero_corsa TEXT NOT NULL,
                ippodromo_evento TEXT NOT NULL,
                numero_partente INTEGER NOT NULL,
                cavallo TEXT NOT NULL,
                data_prestazione TEXT NOT NULL,
                posizione INTEGER NOT NULL,
                ippodromo_prestazione TEXT NOT NULL,
                distanza TEXT NOT NULL,
                unita TEXT NOT NULL,
                partenza TEXT NOT NULL,
                fantino TEXT NOT NULL,
                quota REAL NOT NULL,
                inserito_il TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_palinsesto_sigma_sessione
            ON palinsesto_sigma(sessione_corsa)
            """
        )


def _normalizza_data_palinsesto(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    testo = str(value).strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(testo, formato).date()
        except ValueError:
            continue
    return None


def _testo_cella(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _intero_cella(value: object) -> int | None:
    try:
        numero = float(_testo_cella(value).replace(",", "."))
    except ValueError:
        return None
    if not numero.is_integer():
        return None
    return int(numero)


def _quota_cella(value: object) -> float | None:
    try:
        return float(_testo_cella(value).replace(",", "."))
    except ValueError:
        return None


def _carica_palinsesto_sessione(sessione_corsa: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        dati = pd.read_sql_query(
            """
            SELECT
                data_evento AS "Data Evento",
                orario AS "Orario",
                numero_corsa AS "Numero Corsa",
                ippodromo_evento AS "Ippodromo Evento",
                numero_partente AS "Numero Partente",
                cavallo AS "Cavallo",
                data_prestazione AS "Data Prestazione",
                posizione AS "Posizione",
                ippodromo_prestazione AS "Ippodromo Prestazione",
                distanza AS "Distanza",
                unita AS "Unità",
                partenza AS "Partenza",
                fantino AS "Fantino",
                quota AS "Quota"
            FROM palinsesto_sigma
            WHERE sessione_corsa = ?
            ORDER BY numero_partente, data_prestazione
            """,
            conn,
            params=(sessione_corsa,),
        )
    return dati if not dati.empty else _palinsesto_vuoto()


def _salva_righe_palinsesto(
    sessione_corsa: str,
    righe: pd.DataFrame,
) -> None:
    adesso = ora_italiana().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM palinsesto_sigma WHERE sessione_corsa = ?",
            (sessione_corsa,),
        )
        conn.executemany(
            """
            INSERT INTO palinsesto_sigma (
                sessione_corsa, data_evento, orario, numero_corsa,
                ippodromo_evento, numero_partente, cavallo,
                data_prestazione, posizione, ippodromo_prestazione,
                distanza, unita, partenza, fantino, quota, inserito_il
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    sessione_corsa,
                    riga["Data Evento"],
                    riga["Orario"],
                    riga["Numero Corsa"],
                    riga["Ippodromo Evento"],
                    int(riga["Numero Partente"]),
                    riga["Cavallo"],
                    riga["Data Prestazione"],
                    int(riga["Posizione"]),
                    riga["Ippodromo Prestazione"],
                    riga["Distanza"],
                    riga["Unità"],
                    riga["Partenza"],
                    riga["Fantino"],
                    float(riga["Quota"]),
                    adesso,
                )
                for _indice, riga in righe.iterrows()
            ],
        )


def _prepara_palinsesto(
    tabella: pd.DataFrame,
) -> tuple[pd.DataFrame, list[SchedaCavallo], list[str]]:
    oggi = date.today()
    righe_valide: list[dict[str, object]] = []
    esclusioni: list[str] = []

    for indice, riga in tabella.iterrows():
        numero_riga = int(indice) + 1 if isinstance(indice, int) else str(indice)
        if all(not _testo_cella(riga.get(colonna)) for colonna in PALINSESTO_COLUMNS):
            continue

        mancanti = [
            colonna
            for colonna in PALINSESTO_COLUMNS
            if not _testo_cella(riga.get(colonna))
        ]
        if mancanti:
            esclusioni.append(
                f"Riga {numero_riga}: assenza di dati in "
                + ", ".join(mancanti)
            )
            continue

        data_evento = _normalizza_data_palinsesto(riga["Data Evento"])
        data_prestazione = _normalizza_data_palinsesto(
            riga["Data Prestazione"]
        )
        numero_partente = _intero_cella(riga["Numero Partente"])
        posizione = _intero_cella(riga["Posizione"])
        quota = _quota_cella(riga["Quota"])

        if data_evento is None:
            esclusioni.append(f"Riga {numero_riga}: Data Evento non valida")
            continue
        if data_evento < oggi:
            esclusioni.append(f"Riga {numero_riga}: evento terminato")
            continue
        if data_prestazione is None or data_prestazione > oggi:
            esclusioni.append(
                f"Riga {numero_riga}: Data Prestazione non valida"
            )
            continue
        if numero_partente is None or numero_partente <= 0:
            esclusioni.append(
                f"Riga {numero_riga}: Numero Partente non valido"
            )
            continue
        if posizione is None or posizione <= 0:
            esclusioni.append(f"Riga {numero_riga}: Posizione non valida")
            continue
        if quota is None:
            esclusioni.append(f"Riga {numero_riga}: Quota non valida")
            continue
        if quota < 1.60:
            esclusioni.append(
                f"Riga {numero_riga}: quota sotto 1.60 scartata"
            )
            continue

        righe_valide.append(
            {
                "Data Evento": data_evento.isoformat(),
                "Orario": _testo_cella(riga["Orario"]),
                "Numero Corsa": _testo_cella(riga["Numero Corsa"]),
                "Ippodromo Evento": _testo_cella(riga["Ippodromo Evento"]),
                "Numero Partente": numero_partente,
                "Cavallo": _testo_cella(riga["Cavallo"]),
                "Data Prestazione": data_prestazione.strftime("%d/%m/%Y"),
                "Posizione": posizione,
                "Ippodromo Prestazione": _testo_cella(
                    riga["Ippodromo Prestazione"]
                ),
                "Distanza": _testo_cella(riga["Distanza"]),
                "Unità": _testo_cella(riga["Unità"]),
                "Partenza": _testo_cella(riga["Partenza"]),
                "Fantino": _testo_cella(riga["Fantino"]),
                "Quota": quota,
            }
        )

    if not righe_valide:
        return _palinsesto_vuoto(), [], esclusioni

    pulito = pd.DataFrame(righe_valide, columns=PALINSESTO_COLUMNS)
    identita_evento = pulito[
        ["Data Evento", "Orario", "Numero Corsa", "Ippodromo Evento"]
    ].drop_duplicates()
    if len(identita_evento) != 1:
        raise ValueError(
            "La griglia corrente deve contenere una sola corsa. "
            "Data, orario, numero corsa e ippodromo devono coincidere."
        )

    associazioni = pulito[
        ["Numero Partente", "Cavallo"]
    ].drop_duplicates()
    if associazioni["Numero Partente"].duplicated().any():
        raise ValueError(
            "Uno stesso Numero Partente è associato a più cavalli."
        )
    if associazioni["Cavallo"].str.casefold().duplicated().any():
        raise ValueError("Uno stesso cavallo è associato a più numeri.")

    schede: list[SchedaCavallo] = []
    for numero_partente, gruppo in pulito.groupby(
        "Numero Partente",
        sort=True,
    ):
        nome = str(gruppo.iloc[0]["Cavallo"])
        corse = [
            Corsa(
                posizione=str(int(riga["Posizione"])),
                data_gara=str(riga["Data Prestazione"]),
                ippodromo=str(riga["Ippodromo Prestazione"]),
                distanza_m=str(riga["Distanza"]),
                unita_misura=str(riga["Unità"]),
                parte=str(riga["Partenza"]),
                fantino=str(riga["Fantino"]),
                quota=f"{float(riga['Quota']):.2f}",
                raw_riga="",
            )
            for _indice, riga in gruppo.iterrows()
        ]
        schede.append(
            SchedaCavallo(
                numero_partente=int(numero_partente),
                nome=nome,
                note="",
                eta="",
                sesso="",
                allenatore="",
                flatsix="".join(corsa.posizione for corsa in corse),
                genealogia="",
                proprietario="",
                corse=corse,
            )
        )
    return pulito, schede, esclusioni


def _dataframe_dati_gara_vuoto() -> pd.DataFrame:
    return pd.DataFrame(columns=DATI_GARA_COLUMNS)


COLONNE_MODULI_DISTRIBUZIONE_SIGMA = [
    "Regression",
    "Quanta",
    "Elastico",
    "Sigma Value Score",
    "Densità Sigma",
    "Field Tilt",
    "Anomalia",
    "Indice_Confidenza_Sigma",
    "Spread_Elastico",
    "Alert_Anomalia",
    "Global_Star_Rating",
    "Fair_Odds",
    "Value_Bet",
    "Value_Edge",
    "Consiglio_Operativo",
]


def _riga_dati_gara_standard(
    numero: int,
    nome_cavallo: str,
    *,
    eta: str = "",
    rating: object = None,
    ultimi_arrivi: str = "",
    forma_storica: str = "",
    quote_valide: list[float] | None = None,
) -> dict[str, object]:
    """Riga partente con colonne DATI_GARA_COLUMNS (dati mancanti vuoti/NaN)."""
    quote_list = list(quote_valide or [])
    forma = (forma_storica or ultimi_arrivi or "").strip()
    ultimi = (ultimi_arrivi or forma_storica or "").strip()
    return {
        "N°": numero,
        "Nome": f"{numero} - {nome_cavallo.strip()}",
        "Età": eta or "",
        "Rating": pd.NA if rating is None else rating,
        "Ultimi Arrivi": ultimi,
        "Forma_Storica": forma,
        "Quote Valide": (
            " | ".join(f"{float(q):.2f}" for q in quote_list) if quote_list else "N/D"
        ),
    }


def _normalizza_dataframe_partenti(df: pd.DataFrame) -> pd.DataFrame:
    """Allinea il DataFrame alle colonne standard di ingestione partenti."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return _dataframe_dati_gara_vuoto()

    lavoro = df.copy()
    if "N°" not in lavoro.columns and "Numero" in lavoro.columns:
        lavoro["N°"] = pd.to_numeric(lavoro["Numero"], errors="coerce")
    if "Quote Valide" not in lavoro.columns and "Quota" in lavoro.columns:
        quote_numeriche = pd.to_numeric(lavoro["Quota"], errors="coerce")
        lavoro["Quote Valide"] = quote_numeriche.apply(
            lambda q: f"{float(q):.2f}" if pd.notna(q) else "N/D"
        )
    
    if "Quote Valide" in lavoro.columns:
        lavoro["Quote Valide"] = lavoro["Quote Valide"].fillna("N/D").replace("", "N/D")

    for colonna in DATI_GARA_COLUMNS:
        if colonna not in lavoro.columns:
            lavoro[colonna] = pd.NA if colonna == "Rating" else ""

    if "Forma_Storica" in lavoro.columns and "Ultimi Arrivi" in lavoro.columns:
        forme = []
        ultimi_sync = []
        for forma_val, ultimi_val in zip(
            lavoro["Forma_Storica"], lavoro["Ultimi Arrivi"], strict=False
        ):
            forma_txt = str(forma_val).strip() if pd.notna(forma_val) else ""
            if forma_txt.lower() in {"nan", "none", "<na>"}:
                forma_txt = ""
            ultimi_txt = str(ultimi_val).strip() if pd.notna(ultimi_val) else ""
            if ultimi_txt.lower() in {"nan", "none", "<na>"}:
                ultimi_txt = ""
            if not forma_txt and ultimi_txt:
                forma_txt = ultimi_txt
            if not ultimi_txt and forma_txt:
                ultimi_txt = forma_txt
            forme.append(forma_txt)
            ultimi_sync.append(ultimi_txt)
        lavoro["Forma_Storica"] = forme
        lavoro["Ultimi Arrivi"] = ultimi_sync

    if "Nome" in lavoro.columns:
        def _nome_standard(valore: object, numero_riga: object) -> str:
            testo = str(valore or "").strip()
            if not testo:
                return testo
            
            # Se la stringa contiene già il formato col numero, puliscila ed esci
            if " - " in testo:
                # Controlla se la parte prima del trattino è un numero
                parti = testo.split(" - ", 1)
                if parti[0].strip().isdigit():
                    return testo

            try:
                num = int(numero_riga)
            except (TypeError, ValueError):
                return testo
            return f"{num} - {testo}"

        lavoro["Nome"] = [
            _nome_standard(nome, num)
            for nome, num in zip(lavoro["Nome"], lavoro["N°"], strict=False)
        ]

    return lavoro[DATI_GARA_COLUMNS].copy()


def _ensure_colonne_distribuzione_sigma(df: pd.DataFrame) -> pd.DataFrame:
    """Garantisce colonne modulo Distribuzione Sigma (NaN se assenti, nessun placeholder)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    lavoro = df.copy()
    for colonna in COLONNE_MODULI_DISTRIBUZIONE_SIGMA:
        if colonna not in lavoro.columns:
            lavoro[colonna] = pd.NA
    return lavoro


def _intestazione_gara_vuota() -> dict[str, str]:
    return {
        "Ippodromo/Corsa": "",
        "Data": "",
        "Orario": "",
        "Distanza": "",
        "Premio": "",
    }


def _riga_tabella_orari_palinsesto(riga: str) -> bool:
    """Ignora righe palinsesto tipo «1 20:58», «2 21:25»."""
    return RIGA_TABella_ORARI_PALINSESTO_RE.match(riga.strip()) is not None


def _indice_prima_data_gara_linee(linee: list[str]) -> int | None:
    for indice, riga in enumerate(linee):
        if RIGA_DATA_GARA_RE.match(riga) is not None:
            return indice
        if re.match(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$", riga.strip()):
            return indice
    return None


def _linee_dopo_data_ufficiale(linee: list[str]) -> tuple[list[str], int]:
    """Corpo testo dalla data gara in poi (salta tabella orari iniziale)."""
    data_i = _indice_prima_data_gara_linee(linee)
    if data_i is None:
        return linee, 0
    return linee[data_i:], data_i


def _testo_prima_dei_partenti(testo: str) -> str:
    """Intestazione: tutto prima del corpo partenti (ancoraggio PIAZZATO 4 o data gara)."""
    linee = testo.splitlines()
    indice_p4 = _indice_riga_piazzato_4(linee)
    if indice_p4 is not None:
        return "\n".join(linee[: indice_p4 + 1]).strip()
    linee_coda, offset_base = _linee_dopo_data_ufficiale(linee)
    markers = _marker_partenti_nel_testo(linee_coda)
    if markers:
        taglio = offset_base + markers[0][0]
        if taglio > 0:
            return "\n".join(linee[:taglio]).strip()
    primo = _indice_primo_partente_nel_testo(linee_coda)
    if primo is not None:
        taglio = offset_base + primo
        if taglio > 0:
            return "\n".join(linee[:taglio]).strip()
    return testo.strip()


def _corpo_partenti_linee(testo: str) -> list[str]:
    """Solo righe dalla data gara al primo partente incluso."""
    linee = testo.splitlines()
    linee_coda, offset_base = _linee_dopo_data_ufficiale(linee)
    markers = _marker_partenti_nel_testo(linee_coda)
    if markers:
        return linee[offset_base + markers[0][0] :]
    primo = _indice_primo_partente_nel_testo(linee_coda)
    if primo is not None:
        return linee[offset_base + primo :]
    return linee_coda


def _riga_inizio_blocco_cavallo(linee: list[str], indice_numero: int) -> bool:
    """True se la riga con solo il N° partente apre un blocco cavallo reale."""
    if _riga_tabella_orari_palinsesto(linee[indice_numero]):
        return False
    if _numero_in_sequenza_trattini_ultimi_arrivi(linee, indice_numero):
        return False
    if not _conferma_numero_isolato_inizio_partente(linee, indice_numero):
        return False
    non_vuote = 0
    fine = min(indice_numero + 22, len(linee))
    for j in range(indice_numero + 1, fine):
        testo = linee[j].strip()
        if not testo:
            continue
        if _riga_tabella_orari_palinsesto(linee[j]):
            return False
        non_vuote += 1
        if _riga_contiene_eta_cavallo(linee[j]):
            return True
        if CODICE_GABBIA_RIGA_RE.fullmatch(testo) is not None:
            return True
        if _estrai_nome_cavallo_da_riga(linee[j]) is not None:
            return True
        if ULTIMI_ARRIVI_ETICHETTA_RE.search(testo):
            return False
        if re.fullmatch(r"\d+[.,]\d{1,2}", testo):
            return False
        if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
            return False
        if _riga_esclude_peso_kg(testo):
            continue
        if non_vuote >= 5:
            return False
    return False


def _estrai_ippodromo_corsa_preambolo(preambolo: str) -> str:
    match = IPPODROMO_CORSA_RE.search(preambolo)
    if match is not None:
        return " ".join(match.group("ippodromo_corsa").split())
    linee = [riga.strip() for riga in preambolo.splitlines() if riga.strip()]
    for indice, riga in enumerate(linee):
        corsa = RIGA_CORSA_NUMERO_RE.match(riga)
        if corsa is None:
            continue
        numero_corsa = corsa.group("numero")
        for j in range(indice - 1, max(-1, indice - 6), -1):
            candidato = linee[j].strip()
            if not candidato:
                continue
            if _riga_tabella_orari_palinsesto(candidato):
                continue
            if RIGA_DATA_GARA_RE.match(candidato) or RIGA_ORARIO_GARA_RE.match(candidato):
                continue
            if re.match(r"(?i)^(corsa|distanza|nome\s+premio|premio)\b", candidato):
                continue
            if re.fullmatch(r"\d{1,2}", candidato):
                continue
            if re.fullmatch(r"\d{1,2}:\d{2}", candidato):
                continue
            return f"{candidato} / Corsa {numero_corsa}"
    return ""


def _estrai_premio_preambolo(preambolo: str) -> str:
    diretto = PREMIO_RIGA_DIRETTO_RE.search(preambolo)
    if diretto is not None:
        return " ".join(diretto.group("premio").split())
    etichetta = PREMIO_GARA_RE.search(preambolo)
    if etichetta is not None:
        return " ".join(etichetta.group("premio").split())
    return ""


def _estrai_nome_da_blocco_cavallo(blocco: str) -> str | None:
    linee = blocco.splitlines()
    indice_inizio = 0
    if linee and NUMERO_PARTENTE_RIGA_RE.fullmatch(linee[0].strip()) is not None:
        indice_inizio = 1
    for indice in range(indice_inizio, len(linee)):
        if _riga_ancora_sesso_eta(linee[indice]):
            nome = _nome_cavallo_ancora_inversa(linee, indice)
            if nome:
                return nome
    for indice in range(indice_inizio, len(linee)):
        if _riga_contiene_eta_cavallo(linee[indice]):
            break
        if CODICE_GABBIA_RIGA_RE.fullmatch(linee[indice].strip()) is not None:
            continue
        nome = _estrai_nome_cavallo_da_riga(linee[indice])
        if nome:
            return nome
    return None


def _split_blocchi_cavalli_regex(testo_corpo: str) -> list[tuple[int, str, str]]:
    """Split regex dei blocchi partente (1–12 + gabbia opzionale)."""
    blocchi: list[tuple[int, str, str]] = []
    linee = testo_corpo.splitlines()
    corrispondenze = list(PARTENTE_BLOCCO_HEADER_RE.finditer(testo_corpo))
    if not corrispondenze:
        return blocchi

    indici_validi: list[re.Match[str]] = []
    for match in corrispondenze:
        linea_inizio = testo_corpo[: match.start()].count("\n")
        if linea_inizio >= len(linee):
            continue
        if not _riga_inizio_blocco_cavallo(linee, linea_inizio):
            continue
        indici_validi.append(match)

    for pos, match in enumerate(indici_validi):
        numero = int(match.group("numero"))
        inizio = match.start()
        fine = (
            indici_validi[pos + 1].start()
            if pos + 1 < len(indici_validi)
            else len(testo_corpo)
        )
        blocco = testo_corpo[inizio:fine].strip()
        if not blocco:
            continue
        nome = _estrai_nome_da_blocco_cavallo(blocco)
        if not nome:
            continue
        quote = _estrai_quote_valide(blocco)
        if not quote:
            continue
        blocchi.append((numero, nome, blocco))
    return blocchi


def _marker_partenti_nel_testo(linee: list[str]) -> list[tuple[int, int]]:
    """Indici riga e N° partente per split a blocchi (\\n1\\n, \\n2\\n, …)."""
    trovati: dict[int, int] = {}
    for indice_riga, numero, _nome in _raccogli_avvii_partenti(linee):
        if numero not in trovati.values():
            trovati[indice_riga] = numero

    numeri_visti = set(trovati.values())
    for indice, riga in enumerate(linee):
        if indice in trovati:
            continue
        if _riga_tabella_orari_palinsesto(riga):
            continue
        match = NUMERO_PARTENTE_RIGA_RE.fullmatch(riga)
        if match is None:
            continue
        numero = int(match.group("numero"))
        if numero in numeri_visti:
            continue
        if not _riga_inizio_blocco_cavallo(linee, indice):
            continue
        numeri_visti.add(numero)
        trovati[indice] = numero
    return sorted((idx, num) for idx, num in trovati.items())


def _indice_primo_partente_nel_testo(linee: list[str]) -> int | None:
    markers = _marker_partenti_nel_testo(linee)
    if markers:
        return markers[0][0]
    avvii = _raccogli_avvii_partenti(linee)
    if not avvii:
        return None
    return avvii[0][0]


def _riga_contiene_eta_cavallo(riga: str) -> bool:
    return bool(riga.strip()) and AGE_RE.search(riga) is not None


def _riga_esclusa_come_nome(riga: str) -> bool:
    testo = riga.strip()
    if not testo:
        return True
    if re.match(r"(?i)^(rating|ultimi\s+arrivi)\b", testo):
        return True
    if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
        return True
    if _riga_esclude_peso_kg(testo):
        return True
    if NUMERO_PARTENTE_RIGA_RE.fullmatch(testo) is not None:
        return True
    if CODICE_GABBIA_RIGA_RE.fullmatch(testo) is not None:
        return True
    if re.fullmatch(r"\d+[.,]\d{1,2}", testo):
        return True
    return False


def _pulisci_riga_nome_cavallo(riga: str) -> str:
    testo = riga.strip()
    testo = re.sub(r"^\|+\s*", "", testo)
    testo = re.sub(r"\s*\|+$", "", testo)
    testo = re.sub(r"\s*\|\s*", " ", testo)
    return " ".join(testo.split()).strip(" .-:\t")


def _estrai_nome_cavallo_da_riga(riga: str) -> str | None:
    """Nome su riga libera o con pipe (trotto); esclude righe tecniche."""
    if _riga_esclusa_come_nome(riga):
        return None
    pulito = _pulisci_riga_nome_cavallo(riga)
    if not pulito or len(pulito) < 2:
        return None
    if AGE_RE.search(pulito) and not re.search(
        r"(?i)[A-Za-zÀ-ö]{3,}", re.sub(r"\d{1,2}YO", "", pulito, flags=re.I)
    ):
        return None
    nome = _riga_e_nome_cavallo(pulito)
    if nome:
        return nome
    if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", pulito) and not re.fullmatch(
        r"(?i)(castrone|fattrice|intero|gelding|mare|stallion)", pulito
    ):
        return pulito
    return None


def _nome_prima_della_riga_eta(linee: list[str], indice_eta: int) -> str | None:
    indice = indice_eta - 1
    while indice >= 0:
        riga = linee[indice]
        if not riga.strip():
            indice -= 1
            continue
        nome = _estrai_nome_cavallo_da_riga(riga)
        if nome:
            return nome
        if _riga_contiene_eta_cavallo(riga):
            return None
        indice -= 1
    return None


def _indice_numero_partente_prima_nome(
    linee: list[str],
    indice_nome: int,
) -> tuple[int, int] | None:
    indice = indice_nome - 1
    while indice >= 0:
        riga = linee[indice]
        testo = riga.strip()
        if not testo:
            indice -= 1
            continue
        match_numero = NUMERO_PARTENTE_RIGA_RE.fullmatch(riga)
        if match_numero is not None:
            return indice, int(match_numero.group("numero"))
        if CODICE_GABBIA_RIGA_RE.fullmatch(testo) is not None:
            indice -= 1
            continue
        if RIGA_ORARIO_GARA_RE.match(riga) is not None:
            indice -= 1
            continue
        indice -= 1
    return None


def _raccogli_avvii_partenti(linee: list[str]) -> list[tuple[int, int, str]]:
    """
    Avvii partente: formato galoppo (N° + gabbia + nome) o trotto (N° + nome prima di *YO).
    """
    trovati: dict[int, tuple[int, str]] = {}

    indice = 0
    while indice < len(linee) - 2:
        match_numero = NUMERO_PARTENTE_RIGA_RE.fullmatch(linee[indice])
        riga_codice = linee[indice + 1].strip()
        nome = _riga_e_nome_cavallo(linee[indice + 2])
        if (
            match_numero is not None
            and CODICE_GABBIA_RIGA_RE.fullmatch(riga_codice) is not None
            and nome is not None
        ):
            trovati[indice] = (int(match_numero.group("numero")), nome)
            indice += 3
            continue
        indice += 1

    for indice_eta, riga in enumerate(linee):
        if not _riga_contiene_eta_cavallo(riga):
            continue
        nome = _nome_prima_della_riga_eta(linee, indice_eta)
        if not nome:
            continue
        indice_nome = indice_eta - 1
        while indice_nome >= 0 and not linee[indice_nome].strip():
            indice_nome -= 1
        numero_info = _indice_numero_partente_prima_nome(linee, indice_nome)
        if numero_info is None:
            continue
        indice_numero, numero = numero_info
        if indice_numero in trovati:
            continue
        trovati[indice_numero] = (numero, nome)

    return sorted(
        (idx, numero, nome) for idx, (numero, nome) in trovati.items()
    )


def parse_intestazione_gara(testo: str) -> dict[str, str]:
    """
    Estrae solo i campi presenti nell'intestazione reale.
    Campi assenti restano stringa vuota: nessun dato simulato.
    """
    intestazione = _intestazione_gara_vuota()
    preambolo = _testo_prima_dei_partenti(testo)
    if not preambolo:
        return intestazione

    ippodromo_testo = _estrai_ippodromo_corsa_preambolo(preambolo)
    if ippodromo_testo:
        intestazione["Ippodromo/Corsa"] = ippodromo_testo
    else:
        ippodromo = IPPODROMO_CORSA_RE.search(preambolo)
        if ippodromo is not None:
            intestazione["Ippodromo/Corsa"] = " ".join(
                ippodromo.group("ippodromo_corsa").split()
            )

    data_gara, orario_gara = _estrai_data_e_orario_gara(preambolo)
    if data_gara:
        intestazione["Data"] = data_gara
    else:
        data = DATA_GARA_INTESTAZIONE_RE.search(preambolo)
        if data is not None:
            intestazione["Data"] = data.group("data")
    intestazione["Orario"] = orario_gara

    distanza = DISTANZA_GARA_RE.search(preambolo)
    if distanza is not None:
        intestazione["Distanza"] = distanza.group("distanza")

    premio_testo = _estrai_premio_preambolo(preambolo)
    if premio_testo:
        intestazione["Premio"] = premio_testo

    return intestazione


def _etichetta_gara_archivio(
    intestazione: dict[str, str],
    numero_partenti: int,
) -> str:
    pezzi = [
        valore
        for chiave in ("Ippodromo/Corsa", "Data", "Orario", "Premio")
        if (valore := str(intestazione.get(chiave, "")).strip())
    ]
    base = " · ".join(pezzi) if pezzi else "Gara senza intestazione"
    return f"{base} ({numero_partenti} partenti)"


def _riga_e_nome_cavallo(riga: str) -> str | None:
    """Valida la riga Nome: esclude etichette tecniche e quote."""
    testo = riga.strip()
    if not testo:
        return None
    if re.match(r"(?i)^(rating|ultimi\s+arrivi)\b", testo):
        return None
    if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
        return None
    if re.fullmatch(r"\d{1,2}YO", testo, flags=re.IGNORECASE):
        return None
    if re.fullmatch(r"\d+[.,]\d{1,2}", testo):
        return None
    match = NOME_CAVALLO_RIGA_RE.fullmatch(testo)
    if not match:
        return None
    nome = " ".join(match.group("nome").split()).strip(" .-:\t")
    return nome or None


def _split_blocchi_cavalli(testo: str) -> list[tuple[int, str, str]]:
    """
    Corpo partenti dopo data ufficiale: split regex + marker riga (\\n1\\n, G8, …).
    """
    linee_corpo = _corpo_partenti_linee(testo)
    testo_corpo = "\n".join(linee_corpo)

    blocchi_regex = _split_blocchi_cavalli_regex(testo_corpo)
    if blocchi_regex:
        return blocchi_regex

    linee = linee_corpo
    if not linee:
        return []

    markers = _marker_partenti_nel_testo(linee)
    blocchi: list[tuple[int, str, str]] = []

    if markers:
        for pos, (indice_riga, numero) in enumerate(markers):
            fine_riga = (
                markers[pos + 1][0] if pos + 1 < len(markers) else len(linee)
            )
            blocco = "\n".join(linee[indice_riga:fine_riga]).strip()
            nome = _estrai_nome_da_blocco_cavallo(blocco)
            if not nome or not blocco:
                continue
            if not _estrai_quote_valide(blocco):
                continue
            blocchi.append((numero, nome, blocco))
        if blocchi:
            return blocchi

    testo_completo = testo.strip()
    indici_testo: list[int] = []
    cursore = 0
    linee_full = testo_completo.splitlines()
    for riga in linee_full:
        indici_testo.append(cursore)
        cursore += len(riga) + 1

    avvii = _raccogli_avvii_partenti(linee_corpo)
    for posizione, (indice_riga, numero, nome) in enumerate(avvii):
        if indice_riga >= len(linee):
            continue
        fine_riga = (
            avvii[posizione + 1][0]
            if posizione + 1 < len(avvii)
            else len(linee)
        )
        blocco = "\n".join(linee[indice_riga:fine_riga]).strip()
        if nome and blocco and _estrai_quote_valide(blocco):
            blocchi.append((numero, nome, blocco))
    return blocchi


def _riga_esclude_peso_kg(riga: str) -> bool:
    """True se la riga contiene riferimenti al peso del fantino (Kg)."""
    return PESO_KG_RIGA_RE.search(riga) is not None


def _decimali_quota_in_riga(riga: str) -> list[float]:
    """Decimali in riga come candidati quota; ignora righe con Kg."""
    if _riga_esclude_peso_kg(riga):
        return []
    trovati: list[float] = []
    for match in QUOTA_DECIMALE_RE.finditer(riga):
        try:
            trovati.append(float(match.group(0).replace(",", ".")))
        except ValueError:
            continue
    return trovati


def _limita_quote_mercato_utili(quote: list[float]) -> list[float]:
    """
    Galoppo: 1ª quota = Vincente, 2ª = Piazzato (solo primi 2 decimali del blocco).
    Vincente >= 1.60 obbligatorio; Piazzato opzionale se >= 1.60.
    """
    return _quote_vincente_piazzato_galoppo(quote)


def _decimali_quota_riga_senza_soglia(riga: str) -> list[float]:
    """Decimali in riga (ignora Kg); nessun filtro 1.60 in raccolta."""
    if _riga_esclude_peso_kg(riga):
        return []
    trovati: list[float] = []
    for match in QUOTA_DECIMALE_RE.finditer(riga):
        try:
            trovati.append(float(match.group(0).replace(",", ".")))
        except ValueError:
            continue
    return trovati


def _quote_vincente_piazzato_galoppo(decimali_ordinati: list[float]) -> list[float]:
    """Primi 2 decimali trovati; ignora dal 3° in poi (es. 1.00 Galoppo)."""
    if not decimali_ordinati:
        return []
    primi = decimali_ordinati[:MAX_QUOTE_MERCATO_UTILI]
    vincente = primi[0]
    if vincente < 1.60:
        return []
    risultato = [vincente]
    if len(primi) > 1 and primi[1] >= 1.60:
        risultato.append(primi[1])
    return risultato


def _parse_ultimi_arrivi_da_riga(
    righe: list[str],
    indice: int,
) -> tuple[str, int] | None:
    """Ultimi arrivi inline (galoppo) o su riga dedicata (trotto)."""
    if indice >= len(righe):
        return None
    riga = righe[indice]
    if ULTIMI_ARRIVI_ETICHETTA_RE.search(riga) is None:
        return None
    inline = ULTIMI_ARRIVI_RE.search(riga)
    if inline is not None:
        ultimi = _normalizza_testo_ultimi_arrivi(inline.group("ultimi"))
        return ultimi, indice + 1
    if RIGA_ULTIMI_ARRIVI_ESATTA_RE.fullmatch(riga):
        if indice + 1 < len(righe):
            ultimi = _normalizza_testo_ultimi_arrivi(righe[indice + 1])
            return ultimi, indice + 2
        return "", indice + 1
    return None


def _riga_interrompe_blocco_quote(righe: list[str], indice: int) -> bool:
    if indice < 0 or indice >= len(righe):
        return False
    testo = righe[indice].strip()
    if not testo:
        return False
    if _numero_partente_da_riga_contesto(righe, indice) is not None:
        return True
    if (
        NUMERO_PARTENTE_RIGA_RE.fullmatch(righe[indice]) is not None
        and _conferma_numero_isolato_inizio_partente(righe, indice)
        and not _numero_in_sequenza_trattini_ultimi_arrivi(righe, indice)
    ):
        return True
    return False


def _raccogli_quote_partente_da_righe(
    righe: list[str],
    inizio: int,
    fine: int,
) -> list[float]:
    """Primi 2 decimali del blocco quote; regola Vincente/Piazzato Galoppo."""
    decimali: list[float] = []
    for cursore in range(inizio, fine):
        if _riga_interrompe_blocco_quote(righe, cursore):
            break
        testo = righe[cursore].strip()
        if not testo:
            continue
        if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
            continue
        if RATING_RE.search(testo):
            continue
        if _riga_esclusa_quote_index_scan_yo(righe[cursore]):
            continue
        for quota in _decimali_quota_riga_senza_soglia(righe[cursore]):
            decimali.append(quota)
            if len(decimali) >= MAX_QUOTE_MERCATO_UTILI:
                return _quote_vincente_piazzato_galoppo(decimali)
    return _quote_vincente_piazzato_galoppo(decimali)


def _estrai_ultimi_arrivi_e_linee_quote(blocco: str) -> tuple[str, list[str]]:
    """
    «Ultimi arrivi»: valore sulla riga successiva (trotto/RP) o inline numerico (galoppo).
    Quote solo sulle righe dopo il valore arrivi; righe «metri» ignorate.
    """
    linee = blocco.splitlines()
    for indice, riga in enumerate(linee):
        if ULTIMI_ARRIVI_ETICHETTA_RE.search(riga) is None:
            continue
        inline = ULTIMI_ARRIVI_RE.search(riga)
        if inline is not None:
            ultimi = str(inline.group("ultimi") or "").strip()
            return ultimi, linee[indice + 1 :]
        candidato = indice + 1
        while candidato < len(linee):
            testo = linee[candidato].strip()
            if not testo:
                candidato += 1
                continue
            if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
                candidato += 1
                continue
            ultimi = testo
            return ultimi, linee[candidato + 1 :]
        return "", linee[indice + 1 :]
    return "", []


def _normalizza_forma_storica(valore: object) -> str:
    """Normalizza sequenze reali tipo «9 - 1 - 2 - FE - 5» (nessun dato inventato)."""
    testo = " ".join(str(valore or "").split())
    if not testo:
        return ""
    testo = re.sub(r"\s*-\s*", " - ", testo)
    match = FORMA_STORICA_SEQUENZA_RE.search(testo)
    if match is not None:
        pezzi = [
            p.strip().upper() if not p.strip().isdigit() else p.strip()
            for p in re.split(r"\s*-\s*", match.group("form"))
            if p.strip()
        ]
        return " - ".join(pezzi)
    if testo.isdigit():
        return testo
    if ULTIMI_ARRIVO_LETTERALE_RE.fullmatch(testo):
        return testo.upper()
    return ""


def _calcola_quanta_da_arrivi(forma_storica: object) -> float | None:
    """
    Converte la Forma_Storica reale in punteggio 0–100.
    Punti: 1→10, 2→7, 3→5, 4→3, 5→1; oltre il 5 o lettere (FE, NP, …) → 0.
    """
    testo = _normalizza_forma_storica(forma_storica)
    if not testo:
        return None
    if " - " in testo or "-" in testo:
        pezzi = [p.strip() for p in re.split(r"\s*-\s*", testo) if p.strip()]
    elif testo.isdigit() and len(testo) > 1:
        pezzi = list(testo)
    else:
        pezzi = [testo]
    if not pezzi:
        return None
    punti: list[float] = []
    for pezzo in pezzi:
        if pezzo.isdigit():
            punti.append(PUNTI_ARRIVO_FORMA_STORICA.get(int(pezzo), 0.0))
        else:
            punti.append(0.0)
    media_pesata = (sum(punti) / (len(punti) * MAX_PUNTI_ARRIVO_FORMA)) * 100.0
    return max(0.0, min(100.0, media_pesata))


def _estrai_forma_storica_da_righe(
    lines: list[str],
    inizio: int,
    fine: int | None = None,
) -> str:
    """Cerca «Ultimi arrivi» / sequenza a trattini nelle righe del blocco partente."""
    limite = len(lines) if fine is None else min(fine, len(lines))
    start = max(0, inizio)
    for indice in range(start, limite):
        riga = lines[indice]
        if ULTIMI_ARRIVI_ETICHETTA_RE.search(riga):
            inline = ULTIMI_ARRIVI_RE.search(riga)
            if inline is not None:
                forma = _normalizza_forma_storica(inline.group("ultimi"))
                if forma:
                    return forma
            for succ in range(indice + 1, min(indice + 4, limite)):
                forma = _normalizza_forma_storica(lines[succ])
                if forma and (" - " in forma or len(forma) >= 1):
                    if FORMA_STORICA_SEQUENZA_RE.search(forma) or forma.isdigit():
                        return forma
                    if ULTIMI_ARRIVO_LETTERALE_RE.fullmatch(forma):
                        return forma
        forma_riga = _normalizza_forma_storica(riga)
        if forma_riga and FORMA_STORICA_SEQUENZA_RE.search(forma_riga):
            return forma_riga
    return ""


def _normalizza_testo_ultimi_arrivi(valore: str) -> str:
    testo = str(valore or "").strip()
    if not testo:
        return ""
    forma = _normalizza_forma_storica(testo)
    if forma:
        return forma
    if testo.isdigit():
        return testo
    if ULTIMI_ARRIVO_LETTERALE_RE.fullmatch(testo):
        return testo.upper()
    return testo


def _estrai_quote_blocco(blocco: str) -> tuple[list[float], int]:
    """
    Quote valide (>=1.60) solo dopo «Ultimi arrivi»; ignora Kg e righe precedenti.
    """
    quote_valide: list[float] = []
    scartate = 0
    if ULTIMI_ARRIVI_ETICHETTA_RE.search(blocco) is None:
        return quote_valide, scartate

    _ultimi, linee_quote = _estrai_ultimi_arrivi_e_linee_quote(blocco)
    decimali_raw: list[float] = []
    for idx_riga, riga in enumerate(linee_quote):
        testo = riga.strip()
        if not testo:
            continue
        if RIGA_METRI_DISTANZA_RE.fullmatch(testo):
            continue
        if _numero_partente_da_riga_contesto(linee_quote, idx_riga) is not None:
            break
        if _riga_esclude_peso_kg(testo):
            continue
        for quota in _decimali_quota_riga_senza_soglia(riga):
            decimali_raw.append(quota)
            if len(decimali_raw) >= MAX_QUOTE_MERCATO_UTILI:
                break
        if len(decimali_raw) >= MAX_QUOTE_MERCATO_UTILI:
            break
    quote_valide = _quote_vincente_piazzato_galoppo(decimali_raw)
    scartate = max(0, len(decimali_raw) - len(quote_valide))
    return quote_valide, scartate


def _estrai_ultimi_arrivi_blocco(blocco: str) -> str:
    ultimi, _linee = _estrai_ultimi_arrivi_e_linee_quote(blocco)
    return _normalizza_testo_ultimi_arrivi(ultimi)


def _estrai_rating_blocco(blocco: str) -> float | None:
    """Rating opzionale: assente → None (nessun valore inventato)."""
    rating_match = RATING_RE.search(blocco)
    if rating_match is None:
        return None
    try:
        return float(rating_match.group("rating").replace(",", "."))
    except ValueError:
        return None


def _estrai_quote_valide(blocco: str) -> list[float]:
    """Estrae le quote decimali del blocco e scarta subito quelle < 1.60."""
    valide, _scartate = _estrai_quote_blocco(blocco)
    return valide


def _estrai_data_e_orario_gara(preambolo: str) -> tuple[str, str]:
    """
    Data (DD/MM/YYYY) e orario di gara ancorati: solo HH:MM dopo la data.
    Ignora elenchi di orari precedenti (es. 20:08, 20:40…). Se manca → N/D.
    """
    testo = preambolo.strip()
    if not testo:
        return "", "N/D"

    linee = testo.splitlines()
    for indice, riga in enumerate(linee):
        if _riga_tabella_orari_palinsesto(riga):
            continue
        match_data = RIGA_DATA_GARA_RE.match(riga)
        if match_data is None and not re.match(
            r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$", riga.strip()
        ):
            continue
        if match_data is not None:
            data_val = match_data.group("data")
        else:
            data_val = riga.strip()
        for succ in linee[indice + 1 :]:
            candidato = succ.strip()
            if not candidato:
                continue
            if _riga_tabella_orari_palinsesto(succ):
                continue
            match_orario = RIGA_ORARIO_GARA_RE.match(succ)
            if match_orario:
                return data_val, match_orario.group("orario")
            break
        return data_val, "N/D"

    matches = list(DATA_ORARIO_GARA_ANCORATO_RE.finditer(testo))
    if matches:
        ultimo = matches[-1]
        return ultimo.group("data"), ultimo.group("orario")

    for indice, riga in enumerate(linee):
        match_data = re.match(
            r"^\s*(?P<data>\d{1,2}/\d{1,2}/\d{2,4})\s*$",
            riga,
        )
        if match_data is None:
            continue
        data_val = match_data.group("data")
        for succ in linee[indice + 1 :]:
            candidato = succ.strip()
            if not candidato:
                continue
            match_orario = RIGA_ORARIO_GARA_RE.match(succ)
            if match_orario:
                return data_val, match_orario.group("orario")
            break

    return "", "N/D"


def _estrai_orario_dopo_data(preambolo: str) -> str:
    """Compatibilità interna: solo orario ancorato alla data."""
    _data, orario = _estrai_data_e_orario_gara(preambolo)
    return orario if orario != "N/D" else ""


def _statistiche_mercato_da_testo(testo: str) -> dict[str, object]:
    """Quota media e quote scartate (<1.60) solo da testo grezzo incollato."""
    testo_pulito = _testo_gara_preparato(testo)
    if not testo_pulito:
        return {"quota_media": None, "quote_scartate": 0}
    tutte_valide: list[float] = []
    for record in _parse_partenti_index_scan_yo(testo_pulito):
        quote_valide = record.get("quote_valide")
        if isinstance(quote_valide, list):
            tutte_valide.extend(float(q) for q in quote_valide)
    quota_media = statistics.mean(tutte_valide) if tutte_valide else None
    return {
        "quota_media": quota_media,
        "quote_scartate": None,
    }


def _statistiche_mercato_da_dataframe(df: pd.DataFrame) -> dict[str, object]:
    """Ripete quota media dai partenti salvati; scarti non ricostruibili → None."""
    if df is None or df.empty:
        return {"quota_media": None, "quote_scartate": None}
    tutte: list[float] = []
    for _idx, riga in df.iterrows():
        tutte.extend(_parse_quote_valide_cella(riga.get("Quote Valide")))
    quota_media = statistics.mean(tutte) if tutte else None
    return {"quota_media": quota_media, "quote_scartate": None}


RIGA_SOLO_NUMERO_PARTENTE_RE = re.compile(r"^\s*(\d{1,2})\s*$")
RIGA_ULTIMI_ARRIVI_ESATTA_RE = re.compile(r"(?i)^Ultimi\s+arrivi\s*$")
RIGA_ANCORA_SESSO_ETA_RE = re.compile(
    r"\|\s*(Femmina|Maschio|Castrone)\s*\|\s*\d+YO",
    re.IGNORECASE,
)


def _riga_ancora_sesso_eta(testo: str) -> bool:
    """Ancora inversa: sesso ed età (galoppo, trotto, estero)."""
    return bool(RIGA_ANCORA_SESSO_ETA_RE.search(testo.strip()))


def _nome_cavallo_ancora_inversa(linee: list[str], indice_ancora: int) -> str:
    """
    Prima riga non vuota immediatamente precedente l'ancora sesso|YO.
    Ignora solo la riga con il solo numero partente del blocco.
    """
    indice_min = 0
    if linee and NUMERO_PARTENTE_RIGA_RE.fullmatch(linee[0].strip()) is not None:
        indice_min = 1
    for j in range(indice_ancora - 1, indice_min - 1, -1):
        t = linee[j].strip()
        if not t:
            continue
        if _numero_partente_da_riga_contesto(linee, j) is not None:
            continue
        if NUMERO_PARTENTE_RIGA_RE.fullmatch(t) is not None:
            continue
        return t
    return ""


def _nome_cavallo_ancora_inversa_da_blocco(righe_blocco: list[str]) -> str:
    linee = [str(r) for r in righe_blocco]
    for i in range(len(linee) - 1, -1, -1):
        if _riga_ancora_sesso_eta(linee[i]):
            return _nome_cavallo_ancora_inversa(linee, i)
    return ""


def _indice_riga_piazzato_4(linee: list[str]) -> int | None:
    for indice, riga in enumerate(linee):
        if re.fullmatch(r"(?i)PIAZZATO\s+4", riga.strip()):
            return indice
    return None


def _corpo_partenti_dopo_piazzato_4(testo: str) -> str | None:
    """Testo partenti: righe dopo l'ancoraggio «PIAZZATO 4»."""
    linee = testo.splitlines()
    indice = _indice_riga_piazzato_4(linee)
    if indice is None:
        return None
    return "\n".join(linee[indice + 1 :])


def _numero_partente_da_riga(
    testo: str,
    righe: list[str] | None = None,
    indice: int | None = None,
) -> int | None:
    if righe is not None and indice is not None:
        return _numero_partente_da_riga_contesto(righe, indice)
    return None


def _riga_solo_trattino_separatore(testo: str) -> bool:
    """Trattino isolato tipico degli ultimi arrivi in colonna (8 \\n - \\n 5)."""
    candidato = testo.strip()
    if candidato in {"-", "–", "—"}:
        return True
    return bool(re.fullmatch(r"[\-\–\—]+", candidato))


def _numero_in_sequenza_trattini_ultimi_arrivi(righe: list[str], indice: int) -> bool:
    if indice < 0 or indice >= len(righe):
        return False
    testo = righe[indice].strip()
    if not RIGA_SOLO_NUMERO_PARTENTE_RE.fullmatch(testo):
        return False
    if indice > 0 and _riga_solo_trattino_separatore(righe[indice - 1]):
        return True
    if indice + 1 < len(righe) and _riga_solo_trattino_separatore(righe[indice + 1]):
        return True
    return False


def _conferma_numero_isolato_inizio_partente(righe: list[str], indice: int) -> bool:
    """Vero solo se dopo il N° c'è gabbia o nome cavallo (entro 2 righe utili)."""
    for j in range(indice + 1, min(indice + 3, len(righe))):
        testo = righe[j].strip()
        if not testo:
            continue
        if _riga_solo_trattino_separatore(testo):
            return False
        if CODICE_GABBIA_RIGA_RE.fullmatch(testo) is not None:
            return True
        if _estrai_nome_cavallo_da_riga(righe[j]) is not None:
            return True
        if _riga_contiene_eta_cavallo(righe[j]):
            return True
        if RIGA_SOLO_NUMERO_PARTENTE_RE.fullmatch(testo):
            break
        if ULTIMI_ARRIVI_ETICHETTA_RE.search(testo):
            return False
    return False


def _numero_partente_da_riga_contesto(righe: list[str], indice: int) -> int | None:
    """Numero partente solo se confermato da gabbia/nome; ignora cifre tra trattini."""
    if indice < 0 or indice >= len(righe):
        return None
    testo = righe[indice].strip()
    match = RIGA_SOLO_NUMERO_PARTENTE_RE.fullmatch(testo)
    if match is None:
        return None
    numero = int(match.group(1))
    if not (1 <= numero <= 30):
        return None
    if _numero_in_sequenza_trattini_ultimi_arrivi(righe, indice):
        return None
    if not _conferma_numero_isolato_inizio_partente(righe, indice):
        return None
    return numero


def _compatta_righe_verticali_partenti(linee: list[str]) -> list[str]:
    """
    Pre-processing: unisce N° / gabbia / nome sparsi su righe verticali
    in sequenza compatta digeribile dal parser esistente.
    """
    if not linee:
        return []
    compattate: list[str] = []
    indice = 0
    totale = len(linee)
    while indice < totale:
        riga = linee[indice]
        testo = riga.strip()
        if not testo:
            compattate.append(riga)
            indice += 1
            continue

        if NUMERO_PARTENTE_RIGA_RE.fullmatch(testo) is None:
            compattate.append(riga)
            indice += 1
            continue

        segmento: list[str] = [testo]
        cursore = indice + 1
        indice_nome: int | None = None
        while cursore < totale and cursore <= indice + 14:
            riga_c = linee[cursore]
            testo_c = riga_c.strip()
            if not testo_c:
                cursore += 1
                continue
            if NUMERO_PARTENTE_RIGA_RE.fullmatch(testo_c) is not None:
                break
            if _riga_contiene_eta_cavallo(riga_c):
                break
            if ULTIMI_ARRIVI_ETICHETTA_RE.search(testo_c):
                break
            if (
                len(segmento) == 1
                and CODICE_GABBIA_RIGA_RE.fullmatch(testo_c) is not None
            ):
                segmento.append(testo_c)
                cursore += 1
                continue
            nome = _estrai_nome_cavallo_da_riga(riga_c)
            if nome:
                segmento.append(nome)
                indice_nome = cursore
                cursore += 1
                break
            break

        if indice_nome is not None and len(segmento) >= 2:
            compattate.extend(segmento)
            indice = indice_nome + 1
            continue

        compattate.append(riga)
        indice += 1
    return compattate


def _rimuovi_segmenti_yo_ritirati(linee: list[str]) -> list[str]:
    """Scarta blocchi delimitati da righe *YO che contengono ritiro/non partente."""
    indici_yo = [i for i, riga in enumerate(linee) if _riga_firma_yo_cavallo(riga)]
    if not indici_yo:
        return linee
    da_scartare: set[int] = set()
    for pos, indice_yo in enumerate(indici_yo):
        inizio = indici_yo[pos - 1] + 1 if pos > 0 else 0
        fine = indici_yo[pos + 1] if pos + 1 < len(indici_yo) else len(linee)
        blocco = "\n".join(linee[inizio:fine])
        if DICITURA_RITIRO_PARTENTE_RE.search(blocco):
            da_scartare.update(range(inizio, fine))
    if not da_scartare:
        return linee
    return [riga for i, riga in enumerate(linee) if i not in da_scartare]


def _indici_inizio_blocco_partente(linee: list[str]) -> list[int]:
    inizi: list[int] = []
    for indice, riga in enumerate(linee):
        testo = riga.strip()
        if not testo:
            continue
        if NUMERO_PARTENTE_RIGA_RE.fullmatch(testo) is None:
            continue
        if _conferma_numero_isolato_inizio_partente(linee, indice):
            inizi.append(indice)
            continue
        if _riga_inizio_blocco_cavallo(linee, indice):
            inizi.append(indice)
    return inizi


def _rimuovi_blocchi_partenti_ritirati(linee: list[str]) -> list[str]:
    """Elimina dall'estrazione i blocchi cavallo con «Non partente» o «Ritirato»."""
    inizi = _indici_inizio_blocco_partente(linee)
    if not inizi:
        return linee
    composto: list[str] = list(linee[: inizi[0]])
    for pos, start in enumerate(inizi):
        fine = inizi[pos + 1] if pos + 1 < len(inizi) else len(linee)
        blocco = linee[start:fine]
        testo_blocco = "\n".join(blocco)
        if DICITURA_RITIRO_PARTENTE_RE.search(testo_blocco):
            continue
        composto.extend(blocco)
    return composto


def _preprocess_testo_incollato_gara(testo: str) -> str:
    """Normalizzazione pre-parser: compattazione verticale e filtro ritirati."""
    grezzo = testo.strip()
    if not grezzo:
        return ""
    linee = grezzo.splitlines()
    linee = _compatta_righe_verticali_partenti(linee)
    linee = _rimuovi_segmenti_yo_ritirati(linee)
    linee = _rimuovi_blocchi_partenti_ritirati(linee)
    return "\n".join(linee).strip()


def _testo_gara_preparato(testo: str) -> str:
    return _preprocess_testo_incollato_gara(testo.strip())


def _avvisi_dati_statistici_partenti_mancanti(df: pd.DataFrame) -> list[str]:
    """Segnala assenza di campi reali necessari a Regression/Quanta (nessun placeholder)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    avvisi: list[str] = []
    rating = pd.to_numeric(df.get("Rating"), errors="coerce")
    col_ultimi = df.get("Ultimi Arrivi")
    col_forma = df.get("Forma_Storica")
    ultimi_assenti = True
    if col_ultimi is not None:
        ultimi_vuoti = col_ultimi.astype(str).str.strip().eq("") | col_ultimi.isna()
        ultimi_assenti = bool(ultimi_vuoti.all())
    if ultimi_assenti and col_forma is not None:
        forma_vuoti = col_forma.astype(str).str.strip().eq("") | col_forma.isna()
        ultimi_assenti = bool(forma_vuoti.all())
    if rating.isna().all() and ultimi_assenti:
        avvisi.append(
            "Rating e storico assenti nel testo incollato: "
            "il modulo Regression non è calcolabile."
        )
    if ultimi_assenti:
        avvisi.append(
            "Ultimi Arrivi / Forma_Storica assenti nel testo incollato: "
            "il modulo Quanta non è calcolabile."
        )
    return avvisi


def _normalizza_righe_testo_grezzo(testo: str) -> list[str]:
    """Righe strip; scartate quelle completamente vuote."""
    return [riga.strip() for riga in testo.splitlines() if riga.strip()]


def _riga_firma_yo_cavallo(riga: str) -> bool:
    """Firma partente: riga con età in formato *YO (es. | Femmina | 4YO)."""
    return AGE_RE.search(riga) is not None


def _riga_scoria_nome_index_scan_yo(riga: str) -> bool:
    if RIGA_SOLO_NUMERO_PARTENTE_RE.fullmatch(riga.strip()) is not None:
        return True
    if NUMERO_PARTENTE_RIGA_RE.fullmatch(riga) is not None:
        return True
    if CODICE_GABBIA_RIGA_RE.fullmatch(riga.strip()) is not None:
        return True
    if _riga_esclude_peso_kg(riga):
        return True
    if re.search(r"(?i)silks", riga):
        return True
    return False


def _indice_yo_precedente(indici_yo: list[int], posizione: int) -> int:
    return indici_yo[posizione - 1] if posizione > 0 else -1


def _nome_cavallo_index_scan_yo(righe: list[str], indice_yo: int, indice_yo_prec: int) -> str:
    limite = indice_yo_prec + 1 if indice_yo_prec >= 0 else 0
    for j in range(indice_yo - 1, limite - 1, -1):
        if _riga_firma_yo_cavallo(righe[j]):
            break
        candidato = righe[j]
        if _riga_scoria_nome_index_scan_yo(candidato):
            continue
        return candidato
    return ""


def _numero_partente_index_scan_yo(
    righe: list[str], indice_yo: int, indice_yo_prec: int
) -> int | None:
    limite = indice_yo_prec + 1 if indice_yo_prec >= 0 else 0
    for j in range(indice_yo - 1, limite - 1, -1):
        if _riga_firma_yo_cavallo(righe[j]):
            break
        numero = _numero_partente_da_riga_contesto(righe, j)
        if numero is not None:
            return numero
    return None


def _riga_esclusa_quote_index_scan_yo(riga: str) -> bool:
    if _riga_esclude_peso_kg(riga):
        return True
    if re.search(r"(?i)\bmetri\b", riga):
        return True
    if RATING_RE.search(riga):
        return True
    if CODICE_GABBIA_RIGA_RE.fullmatch(riga.strip()) is not None:
        return True
    return False


def _quote_decimali_riga_index_scan_yo(riga: str) -> list[float]:
    if _riga_esclusa_quote_index_scan_yo(riga):
        return []
    trovate: list[float] = []
    for match in QUOTA_DECIMALE_RE.finditer(riga):
        try:
            quota = float(match.group(0).replace(",", "."))
        except ValueError:
            continue
        if quota >= 1.60:
            trovate.append(quota)
    return trovate


def _parse_partenti_index_scan_yo(testo: str) -> list[dict[str, object]]:
    """
    Index Scanning: ogni riga *YO delimita un partente.
    Nome all'indietro (skip numero, gabbia, silks); ultimi e quote in avanti fino al prossimo YO.
    Nessun dato simulato; salva cavalli con quota vincente (1° decimale) ≥ 1.60.
    """
    righe = _normalizza_righe_testo_grezzo(testo.strip())
    if not righe:
        return []

    indici_yo = [i for i, riga in enumerate(righe) if _riga_firma_yo_cavallo(riga)]
    if not indici_yo:
        return []

    lista: list[dict[str, object]] = []
    for pos, indice_yo in enumerate(indici_yo):
        indice_yo_prec = _indice_yo_precedente(indici_yo, pos)
        limite_avanti = indici_yo[pos + 1] if pos + 1 < len(indici_yo) else len(righe)

        nome = _nome_cavallo_index_scan_yo(righe, indice_yo, indice_yo_prec)
        numero = _numero_partente_index_scan_yo(righe, indice_yo, indice_yo_prec)
        if not nome:
            continue

        ultimi = ""
        quote: list[float] = []
        cursore = indice_yo + 1
        while cursore < limite_avanti:
            parsed = _parse_ultimi_arrivi_da_riga(righe, cursore)
            if parsed is not None:
                ultimi, cursore = parsed
                quote = _raccogli_quote_partente_da_righe(
                    righe, cursore, limite_avanti
                )
                break
            cursore += 1

        if not quote:
            continue

        indice_inizio = indice_yo_prec + 1 if indice_yo_prec >= 0 else 0
        for j in range(indice_yo - 1, indice_inizio - 1, -1):
            if _numero_partente_da_riga_contesto(righe, j) is not None:
                indice_inizio = j
                break
        blocco = "\n".join(righe[indice_inizio:limite_avanti])
        eta_match = AGE_RE.search(righe[indice_yo])

        forma_storica = _normalizza_forma_storica(ultimi)
        if not forma_storica:
            forma_storica = _estrai_forma_storica_da_righe(
                blocco.splitlines(), 0
            )
        lista.append(
            {
                "numero": numero,
                "nome": nome,
                "ultimi_arrivi": forma_storica or ultimi,
                "forma_storica": forma_storica or ultimi,
                "quote_valide": quote,
                "blocco": blocco,
                "eta": eta_match.group("eta").upper() if eta_match else "",
                "rating": _estrai_rating_blocco(blocco),
            }
        )

    return lista


def _riga_ignorata_macchina_stati(testo: str) -> bool:
    if not testo:
        return True
    if _riga_esclude_peso_kg(testo):
        return True
    if re.search(r"(?i)\bmetri\b", testo):
        return True
    return False


def _riga_esclusa_da_quote_macchina(testo: str) -> bool:
    """Esclusioni tassative in fase quote (Kg, metri, età YO)."""
    if not testo:
        return False
    if _riga_esclude_peso_kg(testo):
        return True
    if re.search(r"(?i)\bmetri\b", testo):
        return True
    if re.search(r"(?i)\b\d{1,2}YO\b", testo):
        return True
    return False


def _quote_decimali_riga_macchina_stati(riga: str) -> list[float]:
    testo = riga.strip()
    if not testo or _riga_esclusa_da_quote_macchina(testo):
        return []
    trovate: list[float] = []
    for match in QUOTA_DECIMALE_RE.finditer(riga):
        try:
            trovate.append(float(match.group(0).replace(",", ".")))
        except ValueError:
            continue
    return trovate


def _salva_cavallo_macchina_stati(
    lista: list[dict[str, object]],
    cavallo: dict[str, object] | None,
) -> None:
    if not cavallo:
        return
    quote_raw = list(cavallo.get("quote") or [])
    quote: list[float] = []
    for elemento in quote_raw:
        try:
            quote.append(float(elemento))
        except (TypeError, ValueError):
            continue
    quote = _quote_vincente_piazzato_galoppo(quote[:MAX_QUOTE_MERCATO_UTILI])
    nome = str(cavallo.get("nome") or "").strip()
    if not nome or not quote:
        return
    numero = cavallo.get("numero")
    blocco = "\n".join(str(r) for r in cavallo.get("righe_blocco") or [])
    eta_match = AGE_RE.search(blocco)
    ultimi_raw = str(cavallo.get("ultimi") or "").strip()
    forma_storica = _normalizza_forma_storica(ultimi_raw)
    if not forma_storica:
        forma_storica = _estrai_forma_storica_da_righe(blocco.splitlines(), 0)
    lista.append(
        {
            "numero": numero,
            "nome": nome,
            "ultimi_arrivi": forma_storica or ultimi_raw,
            "forma_storica": forma_storica or ultimi_raw,
            "quote_valide": quote,
            "blocco": blocco,
            "eta": eta_match.group("eta").upper() if eta_match else "",
            "rating": _estrai_rating_blocco(blocco),
        }
    )


def _parse_partenti_macchina_stati(testo: str) -> list[dict[str, object]]:
    """
    Parser riga-per-riga: ancoraggio PIAZZATO 4.
    Nome cavallo = ancora inversa su riga | Femmina/Maschio/Castrone | NYO.
    Quote tra valore Ultimi arrivi e prossimo partente (≥ 1.60, nessun dato simulato).
    """
    corpo = _corpo_partenti_dopo_piazzato_4(testo.strip())
    if corpo is None or not corpo.strip():
        return []

    linee = corpo.splitlines()
    lista: list[dict[str, object]] = []
    cavallo: dict[str, object] | None = None
    stato = "cerca_numero"

    indice = 0
    while indice < len(linee):
        riga_raw = linee[indice]
        testo_riga = riga_raw.strip()
        indice += 1

        indice_riga = indice - 1
        numero = _numero_partente_da_riga_contesto(linee, indice_riga)
        if numero is not None and stato in ("cerca_numero", "quote"):
            _salva_cavallo_macchina_stati(lista, cavallo)
            cavallo = {
                "numero": numero,
                "nome": "",
                "ultimi": "",
                "quote": [],
                "righe_blocco": [riga_raw],
            }
            stato = "cerca_ancora_sesso"
            continue

        if not testo_riga:
            if cavallo is not None:
                righe = cavallo.setdefault("righe_blocco", [])
                if isinstance(righe, list):
                    righe.append(riga_raw)
            continue

        if cavallo is not None:
            righe_blocco = cavallo.setdefault("righe_blocco", [])
            if isinstance(righe_blocco, list):
                righe_blocco.append(riga_raw)

        if cavallo is None:
            if stato == "cerca_numero" and _riga_ignorata_macchina_stati(testo_riga):
                continue
            continue

        if stato == "quote":
            if not _riga_esclusa_da_quote_macchina(testo_riga):
                quote_riga = _quote_decimali_riga_macchina_stati(riga_raw)
                if quote_riga:
                    accumulo = cavallo.setdefault("quote", [])
                    if isinstance(accumulo, list):
                        for q in quote_riga:
                            if len(accumulo) >= MAX_QUOTE_MERCATO_UTILI:
                                break
                            accumulo.append(q)
            continue

        if _riga_ignorata_macchina_stati(testo_riga):
            continue

        if stato == "cerca_ancora_sesso":
            if CODICE_GABBIA_RIGA_RE.fullmatch(testo_riga) is not None:
                continue
            if _riga_ancora_sesso_eta(testo_riga):
                righe_b = cavallo.get("righe_blocco")
                if isinstance(righe_b, list):
                    cavallo["nome"] = _nome_cavallo_ancora_inversa_da_blocco(righe_b)
                stato = "cerca_ultimi"
            elif _riga_firma_yo_cavallo(testo_riga):
                righe_b = cavallo.get("righe_blocco")
                if isinstance(righe_b, list):
                    righe_strip = [
                        str(r).strip() for r in righe_b if str(r).strip()
                    ]
                    if righe_strip:
                        nome_yo = _nome_cavallo_index_scan_yo(
                            righe_strip, len(righe_strip) - 1, -1
                        )
                        if nome_yo:
                            cavallo["nome"] = nome_yo
                stato = "cerca_ultimi"
            continue

        if stato == "cerca_ultimi":
            parsed = _parse_ultimi_arrivi_da_riga(linee, indice - 1)
            if parsed is not None:
                cavallo["ultimi"], _ = parsed
                stato = "quote"
            elif RIGA_ULTIMI_ARRIVI_ESATTA_RE.fullmatch(testo_riga):
                stato = "ultimi_valore"
            continue

        if stato == "ultimi_valore":
            cavallo["ultimi"] = _normalizza_testo_ultimi_arrivi(testo_riga)
            stato = "quote"
            continue

    _salva_cavallo_macchina_stati(lista, cavallo)
    return lista


def _parse_partenti_da_blocchi(testo: str) -> list[dict[str, object]]:
    """Fallback split per N° + gabbia opzionale (Galoppo) e trotto."""
    lista: list[dict[str, object]] = []
    for numero, nome, blocco in _split_blocchi_cavalli(testo):
        quote, _scartate = _estrai_quote_blocco(blocco)
        if not quote:
            continue
        eta_match = AGE_RE.search(blocco)
        ultimi_raw = _estrai_ultimi_arrivi_blocco(blocco)
        forma_storica = _normalizza_forma_storica(ultimi_raw)
        if not forma_storica:
            forma_storica = _estrai_forma_storica_da_righe(blocco.splitlines(), 0)
        lista.append(
            {
                "numero": numero,
                "nome": nome,
                "ultimi_arrivi": forma_storica or ultimi_raw,
                "forma_storica": forma_storica or ultimi_raw,
                "quote_valide": quote,
                "blocco": blocco,
                "eta": eta_match.group("eta").upper() if eta_match else "",
                "rating": _estrai_rating_blocco(blocco),
            }
        )
    return lista


def _estrai_partenti_verticali(testo: str) -> pd.DataFrame:
    lines = [line.strip() for line in testo.splitlines() if line.strip()]
    cavalli = []
    i = 0
    while i < len(lines):
        # Cerca un numero (1-40) seguito da un Gate (inizia per G)
        if lines[i].isdigit() and 1 <= int(lines[i]) <= 40:
            if i + 1 < len(lines) and (
                lines[i + 1].startswith("G") or lines[i + 1].isdigit()
            ):
                if i + 2 >= len(lines):
                    i += 1
                    continue
                numero = lines[i]

                offset_nome = 2
                if lines[i + 2].strip().lower() in {"silks", "silk"}:
                    offset_nome = 3
                nome_idx = i + offset_nome
                if nome_idx >= len(lines):
                    i += 1
                    continue
                nome = lines[nome_idx].strip()
                if not nome:
                    i += 1
                    continue

                sesso_eta_idx = nome_idx + 1
                sesso_eta = (
                    lines[sesso_eta_idx].strip()
                    if sesso_eta_idx < len(lines)
                    else ""
                )
                eta = ""
                if sesso_eta and AGE_RE.search(sesso_eta):
                    eta = sesso_eta.strip()
                    eta = re.sub(r"^\|+\s*", "", eta).strip()

                # Controllo ritirati (fino a i+10 per allineamento post-silks)
                ritirato = False
                for j in range(1, 11):
                    if i + j >= len(lines):
                        break
                    testo_check = lines[i + j].lower()
                    if (
                        "non partente" in testo_check
                        or "ritirato" in testo_check
                        or "ritirata" in testo_check
                    ):
                        ritirato = True
                        break

                if not ritirato:
                    # Quota: primo decimale plausibile dopo nome/sesso (fino a i+10)
                    quota_vincente = None
                    limite_quota = min(len(lines), i + 11)
                    for idx_line in range(sesso_eta_idx + 1, limite_quota):
                        riga_quota = lines[idx_line]
                        if re.search(r"kg", riga_quota, re.IGNORECASE):
                            continue
                        match_quota = QUOTA_DECIMALE_RE.search(riga_quota)
                        if match_quota is None:
                            continue
                        try:
                            val = float(match_quota.group(0).replace(",", "."))
                        except ValueError:
                            continue
                        if val >= 1.01:
                            quota_vincente = val
                            break

                    if quota_vincente is not None:
                        forma_storica = _estrai_forma_storica_da_righe(
                            lines, i, min(len(lines), i + 16)
                        )
                        cavalli.append(
                            {
                                "Numero": numero,
                                "Nome": nome,
                                "Quota": quota_vincente,
                                "Età": eta,
                                "Sesso_Eta": eta if eta else sesso_eta.strip(),
                                "Forma_Storica": forma_storica,
                                "Ultimi Arrivi": forma_storica,
                                "Regression": None,
                                "Quanta": None,
                                "Rating": None,
                                "Elastico": None,
                            }
                        )
                i += 2
                continue
        i += 1

    return pd.DataFrame(cavalli) if cavalli else pd.DataFrame()


def _dataframe_partenti_verticali_standard(testo: str) -> pd.DataFrame:
    """DataFrame partenti verticali allineato a DATI_GARA_COLUMNS."""
    tabella = _estrai_partenti_verticali(testo)
    if tabella.empty:
        return _dataframe_dati_gara_vuoto()

    righe: list[dict[str, object]] = []
    for _idx, riga in tabella.iterrows():
        try:
            numero = int(riga["Numero"])
        except (TypeError, ValueError, KeyError):
            continue
        nome = _testo_cella_riga(riga, "Nome")
        if not nome:
            continue
        try:
            quota = float(riga["Quota"])
        except (TypeError, ValueError, KeyError):
            quota = None

        quote_valide: list[float] = []
        if quota is not None and not math.isnan(quota):
            quote_valide.append(float(quota))

        eta_riga = _testo_cella_riga(riga, "Età")
        if not eta_riga:
            eta_riga = _testo_cella_riga(riga, "Sesso_Eta")
        forma_storica = _testo_cella_riga(riga, "Forma_Storica")
        if not forma_storica:
            forma_storica = _testo_cella_riga(riga, "Ultimi Arrivi")
        forma_storica = _normalizza_forma_storica(forma_storica)
        righe.append(
            _riga_dati_gara_standard(
                numero,
                nome,
                eta=eta_riga,
                rating=pd.NA,
                ultimi_arrivi=forma_storica,
                forma_storica=forma_storica,
                quote_valide=quote_valide,
            )
        )

    if not righe:
        return _dataframe_dati_gara_vuoto()
    return _normalizza_dataframe_partenti(pd.DataFrame(righe))


def _records_da_partenti_verticali(testo: str) -> list[dict[str, object]]:
    """Adatta l'estrazione verticale al formato record del parser principale."""
    df = _dataframe_partenti_verticali_standard(testo)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def _record_da_macchina_stati(record: dict[str, object]) -> dict[str, object]:
    quote_valide = record.get("quote_valide")
    if not isinstance(quote_valide, list):
        quote_valide = []
    rating = record.get("rating")
    forma_raw = record.get("forma_storica") or record.get("ultimi_arrivi") or ""
    forma_storica = _normalizza_forma_storica(forma_raw)
    if not forma_storica:
        forma_storica = _normalizza_testo_ultimi_arrivi(str(forma_raw or ""))
    return {
        "N°": record.get("numero"),
        "Nome": f"{record.get('numero')} - {record.get('nome')}",
        "Età": str(record.get("eta") or ""),
        "Rating": rating if rating is not None else pd.NA,
        "Ultimi Arrivi": forma_storica,
        "Forma_Storica": forma_storica,
        "Quote Valide": (
            " | ".join(f"{float(q):.2f}" for q in quote_valide) if quote_valide else ""
        ),
    }


def _dataframe_partenti_orizzontale(testo: str) -> pd.DataFrame:
    """Parser standard (index scan / macchina stati / blocchi) → DataFrame."""
    testo_lavoro = testo.strip()
    if not testo_lavoro:
        return _dataframe_dati_gara_vuoto()
    testo_pulito = _testo_gara_preparato(testo_lavoro)

    records: list[dict[str, object]] = []
    for parser in (
        _parse_partenti_index_scan_yo,
        _parse_partenti_macchina_stati,
        _parse_partenti_da_blocchi,
    ):
        records = parser(testo_pulito)
        if records:
            break

    if not records:
        return _dataframe_dati_gara_vuoto()

    righe: list[dict[str, object]] = []
    for record in records:
        if isinstance(record, dict) and "N°" in record:
            righe.append(record)
        else:
            righe.append(_record_da_macchina_stati(record))
    if not righe:
        return _dataframe_dati_gara_vuoto()
    return _normalizza_dataframe_partenti(pd.DataFrame(righe))


def _inietta_moduli_da_forma_storica(df: pd.DataFrame) -> pd.DataFrame:
    """
    Se Regression/Quanta sono assenti ma esiste Forma_Storica reale,
    inietta il punteggio matematico derivato dagli arrivi (nessuna simulazione).
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return _dataframe_dati_gara_vuoto()
    lavoro = _normalizza_dataframe_partenti(df)
    if "Forma_Storica" not in lavoro.columns:
        lavoro["Forma_Storica"] = ""
    if "Quanta" not in lavoro.columns:
        lavoro["Quanta"] = pd.NA
    if "Regression" not in lavoro.columns:
        lavoro["Regression"] = pd.NA

    quanta_vals: list[object] = []
    regression_vals: list[object] = []
    forme: list[str] = []
    ultimi_vals: list[str] = []

    for _idx, riga in lavoro.iterrows():
        forma = _normalizza_forma_storica(riga.get("Forma_Storica"))
        if not forma:
            forma = _normalizza_forma_storica(riga.get("Ultimi Arrivi"))
        ultimi = str(riga.get("Ultimi Arrivi") or "").strip()
        if ultimi.lower() in {"nan", "none", "<na>"}:
            ultimi = ""
        if not ultimi and forma:
            ultimi = forma
        forme.append(forma)
        ultimi_vals.append(ultimi)

        score = _calcola_quanta_da_arrivi(forma) if forma else None
        quanta_raw = riga.get("Quanta")
        regression_raw = riga.get("Regression")
        quanta_ok = False
        regression_ok = False
        try:
            quanta_ok = quanta_raw is not None and pd.notna(quanta_raw)
        except (TypeError, ValueError):
            quanta_ok = False
        try:
            regression_ok = regression_raw is not None and pd.notna(regression_raw)
        except (TypeError, ValueError):
            regression_ok = False

        if not quanta_ok and score is not None:
            quanta_vals.append(score)
        else:
            quanta_vals.append(quanta_raw if quanta_ok else pd.NA)
        if not regression_ok and score is not None:
            regression_vals.append(score)
        else:
            regression_vals.append(regression_raw if regression_ok else pd.NA)

    lavoro["Forma_Storica"] = forme
    lavoro["Ultimi Arrivi"] = ultimi_vals
    lavoro["Quanta"] = quanta_vals
    lavoro["Regression"] = regression_vals
    return lavoro


def parse_dati_gara_grezzi(testo: str) -> pd.DataFrame:
    """
    Parser Blindato Universale: usa prima il parser condiviso di
    ippica_inserimento, preservando Rating, forma e quote per ogni partente.
    Le quote sotto la soglia Sigma vengono escluse prima di ogni calcolo.
    """
    testo_originale = testo.strip()
    if not testo_originale:
        return _dataframe_dati_gara_vuoto()

    righe_condivise: list[dict[str, object]] = []
    for partente in parse_partenti_testo_grezzo(testo_originale):
        record = partente_grezzo_a_record_dict(partente)
        righe_condivise.append(_record_da_macchina_stati(record))

    if righe_condivise:
        df_blindato = pd.DataFrame(righe_condivise)
    else:
        # I parser locali coprono impaginazioni bookmaker alternative, ma
        # producono lo stesso schema completo del parser condiviso.
        df_blindato = _dataframe_partenti_orizzontale(testo_originale)
        if df_blindato.empty:
            df_blindato = _dataframe_partenti_verticali_standard(testo_originale)
        if df_blindato.empty:
            df_blindato = estrai_dati(testo_originale)

    if df_blindato.empty:
        return _dataframe_dati_gara_vuoto()

    df_normalizzato = _normalizza_dataframe_partenti(df_blindato)
    righe_valide: list[pd.Series] = []
    for _indice, riga in df_normalizzato.iterrows():
        quote = _parse_quote_valide_cella(riga.get("Quote Valide"))
        if not quote:
            continue
        riga_filtrata = riga.copy()
        riga_filtrata["Quote Valide"] = " | ".join(f"{q:.2f}" for q in quote)
        righe_valide.append(riga_filtrata)

    if not righe_valide:
        return _dataframe_dati_gara_vuoto()
    filtrato = pd.DataFrame(righe_valide).reset_index(drop=True)
    return _inietta_moduli_da_forma_storica(filtrato)


def parse_gara_completa(
    testo: str,
) -> tuple[dict[str, str], pd.DataFrame]:
    """Intestazione gara + partenti estratti dallo stesso blocco grezzo."""
    testo_grezzo = testo.strip()
    if not testo_grezzo:
        return _intestazione_gara_vuota(), _dataframe_dati_gara_vuoto()
    testo_pulito = _testo_gara_preparato(testo_grezzo)
    return (
        parse_intestazione_gara(testo_pulito),
        parse_dati_gara_grezzi(testo_grezzo),
    )


def _init_archivio_gare_sigma() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gare_sigma_archivio (
                id TEXT PRIMARY KEY,
                data_evento TEXT,
                orario TEXT,
                ippodromo_corsa TEXT,
                distanza TEXT,
                premio TEXT,
                partenti_json TEXT NOT NULL,
                salvato_il TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordini_arrivo_gare (
                gara_id TEXT PRIMARY KEY,
                ordine_arrivo TEXT NOT NULL,
                salvato_il TEXT NOT NULL,
                FOREIGN KEY (gara_id) REFERENCES gare_sigma_archivio(id)
            )
            """
        )
        try:
            conn.execute(
                "ALTER TABLE gare_sigma_archivio ADD COLUMN classifica_json TEXT"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "ALTER TABLE gare_sigma_archivio ADD COLUMN pronostico_json TEXT"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()


def _costruisci_pronostico_generato(classifica: pd.DataFrame) -> dict[str, object]:
    """Fotografia Top 4: 2 Vincenti · 1 Piazzato · 1 Sorpresa elastica."""
    classifica_ord = _classifica_ordinata(classifica)
    valutabili = classifica_ord[
        classifica_ord["Sigma Value Score"].notna()
    ].reset_index(drop=True)
    sel = _seleziona_quattro_target_sigma(valutabili)
    return {
        "generato_il": ora_italiana().isoformat(timespec="seconds"),
        "top4": sel["top4"].copy(),
        "vincenti": sel["vincenti"].copy(),
        "piazzato": sel["piazzato"].copy(),
        "sorpresa": sel["sorpresa"].copy(),
        "piazzati": sel["piazzato"].copy(),
    }


def _serializza_pronostico_generato(pronostico: dict[str, object]) -> str:
    def records(df: object) -> list[dict]:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return []
        return json.loads(
            df.to_json(orient="records", force_ascii=False, date_format="iso")
        )

    piazzato_df = pronostico.get("piazzato")
    if piazzato_df is None:
        piazzato_df = pronostico.get("piazzati")

    payload = {
        "generato_il": str(pronostico.get("generato_il") or ""),
        "top4": records(pronostico.get("top4")),
        "vincenti": records(pronostico.get("vincenti")),
        "piazzato": records(pronostico.get("piazzato")),
        "sorpresa": records(pronostico.get("sorpresa")),
        "piazzati": records(piazzato_df),
    }
    return json.dumps(payload, ensure_ascii=False)


def _deserializza_pronostico_generato(payload: str | None) -> dict[str, object] | None:
    if not payload:
        return None
    try:
        dati = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(dati, dict):
        return None

    def dataframe(records: object) -> pd.DataFrame:
        if not isinstance(records, list) or not records:
            return pd.DataFrame()
        return pd.read_json(io.StringIO(json.dumps(records)), orient="records")

    piazzato = dataframe(dati.get("piazzato"))
    sorpresa = dataframe(dati.get("sorpresa"))
    piazzati_legacy = dataframe(dati.get("piazzati"))
    if piazzato.empty and not piazzati_legacy.empty:
        piazzato = piazzati_legacy.iloc[0:1].copy()
    if sorpresa.empty and len(piazzati_legacy) >= 2:
        sorpresa = piazzati_legacy.iloc[1:2].copy()

    return {
        "generato_il": dati.get("generato_il", ""),
        "top4": dataframe(dati.get("top4")),
        "vincenti": dataframe(dati.get("vincenti")),
        "piazzato": piazzato,
        "sorpresa": sorpresa,
        "piazzati": piazzato,
    }


def _carica_ordini_arrivo_gare() -> dict[str, str]:
    with sqlite3.connect(DB_PATH) as conn:
        righe = conn.execute(
            "SELECT gara_id, ordine_arrivo FROM ordini_arrivo_gare"
        ).fetchall()
    return {str(gara_id): str(ordine) for gara_id, ordine in righe}


def _serializza_partenti(partenti: pd.DataFrame) -> str:
    return partenti.to_json(orient="records", force_ascii=False, date_format="iso")


def _accoda_gara_storico_testo(
    gara_id: str,
    intestazione: dict[str, str],
    partenti: pd.DataFrame,
    classifica: pd.DataFrame,
    salvato_il: str,
) -> None:
    """Accoda una gara reale in formato JSON Lines nel file storico locale."""
    record = {
        "id": gara_id,
        "salvato_il": salvato_il,
        "intestazione": dict(intestazione),
        "partenti": json.loads(
            partenti.to_json(orient="records", force_ascii=False, date_format="iso")
        ),
        "classifica_sigma": json.loads(
            classifica.to_json(
                orient="records",
                force_ascii=False,
                date_format="iso",
            )
        ),
    }
    with open(STORICO_GARE_PATH, "a", encoding="utf-8") as storico:
        storico.write(json.dumps(record, ensure_ascii=False) + "\n")


def _salva_gara_corrente_storico_testo() -> None:
    gara = _gara_selezionata()
    if gara is None:
        raise ValueError("Nessuna gara disponibile da salvare.")
    partenti = gara.get("partenti")
    classifica = gara.get("classifica")
    if not isinstance(partenti, pd.DataFrame) or partenti.empty:
        raise ValueError("La gara corrente non contiene partenti.")
    if not isinstance(classifica, pd.DataFrame) or classifica.empty:
        raise ValueError("La gara corrente non contiene la classifica Sigma.")
    _accoda_gara_storico_testo(
        str(gara["id"]),
        dict(gara.get("intestazione") or {}),
        partenti,
        classifica,
        str(gara.get("salvata_il") or ora_italiana().isoformat(timespec="seconds")),
    )


def _deserializza_partenti(payload: str) -> pd.DataFrame:
    if not payload:
        return _dataframe_dati_gara_vuoto()
    dati = pd.read_json(io.StringIO(payload), orient="records")
    if dati.empty:
        return _dataframe_dati_gara_vuoto()
    for colonna in DATI_GARA_COLUMNS:
        if colonna not in dati.columns:
            dati[colonna] = pd.NA if colonna == "Rating" else ""
    return dati[DATI_GARA_COLUMNS]


def _deserializza_classifica(payload: str | None) -> pd.DataFrame | None:
    if not payload:
        return None
    try:
        dati = pd.read_json(io.StringIO(payload), orient="records")
    except ValueError:
        return None
    if dati.empty:
        return None
    return dati


def _salva_gara_sqlite(
    gara_id: str,
    intestazione: dict[str, str],
    partenti: pd.DataFrame,
    classifica: pd.DataFrame | None,
    pronostico: dict[str, object] | None,
    salvato_il: str,
) -> None:
    classifica_json = (
        classifica.to_json(orient="records", force_ascii=False, date_format="iso")
        if classifica is not None and not classifica.empty
        else ""
    )
    pronostico_json = (
        _serializza_pronostico_generato(pronostico)
        if pronostico
        else ""
    )
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO gare_sigma_archivio (
                id, data_evento, orario, ippodromo_corsa,
                distanza, premio, partenti_json, classifica_json,
                pronostico_json, salvato_il
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gara_id,
                intestazione.get("Data", ""),
                intestazione.get("Orario", ""),
                intestazione.get("Ippodromo/Corsa", ""),
                intestazione.get("Distanza", ""),
                intestazione.get("Premio", ""),
                _serializza_partenti(partenti),
                classifica_json,
                pronostico_json,
                salvato_il,
            ),
        )
        conn.commit()


def _carica_archivio_gare_sqlite() -> list[dict]:
    ordini_map = _carica_ordini_arrivo_gare()
    with sqlite3.connect(DB_PATH) as conn:
        righe = conn.execute(
            """
            SELECT id, data_evento, orario, ippodromo_corsa,
                   distanza, premio, partenti_json, classifica_json,
                   pronostico_json, salvato_il
            FROM gare_sigma_archivio
            ORDER BY salvato_il ASC
            """
        ).fetchall()
    archivio: list[dict] = []
    for row in righe:
        pronostico_json = None
        if len(row) == 10:
            (
                gara_id,
                data_evento,
                orario,
                ippodromo_corsa,
                distanza,
                premio,
                partenti_json,
                classifica_json,
                pronostico_json,
                salvato_il,
            ) = row
        elif len(row) == 9:
            (
                gara_id,
                data_evento,
                orario,
                ippodromo_corsa,
                distanza,
                premio,
                partenti_json,
                classifica_json,
                salvato_il,
            ) = row
        else:
            (
                gara_id,
                data_evento,
                orario,
                ippodromo_corsa,
                distanza,
                premio,
                partenti_json,
                salvato_il,
            ) = row
            classifica_json = None
        intestazione = {
            "Ippodromo/Corsa": ippodromo_corsa or "",
            "Data": data_evento or "",
            "Orario": orario or "",
            "Distanza": distanza or "",
            "Premio": premio or "",
        }
        partenti = _deserializza_partenti(partenti_json or "")
        classifica = _deserializza_classifica(classifica_json)
        if classifica is None and not partenti.empty:
            classifica = calcola_value_bet(partenti)
        pronostico = _deserializza_pronostico_generato(pronostico_json)
        if pronostico is None and isinstance(classifica, pd.DataFrame) and not classifica.empty:
            pronostico = _costruisci_pronostico_generato(classifica)
        archivio.append(
            {
                "id": gara_id,
                "etichetta": _etichetta_gara_archivio(intestazione, len(partenti)),
                "intestazione": intestazione,
                "partenti": partenti,
                "classifica": classifica,
                "pronostico_generato": pronostico,
                "ordine_arrivo": ordini_map.get(str(gara_id), ""),
                "salvata_il": salvato_il,
            }
        )
    return archivio


def _archivia_gara_in_memoria(
    intestazione: dict[str, str],
    partenti: pd.DataFrame,
    classifica: pd.DataFrame,
    mercato: dict[str, object] | None = None,
) -> str:
    """Salvataggio istantaneo dopo calcolo Distribuzione Sigma."""
    gara_id = str(uuid.uuid4())
    salvato_il = ora_italiana().isoformat(timespec="seconds")
    stats_mercato = mercato or _statistiche_mercato_da_dataframe(partenti)
    pronostico_generato = _costruisci_pronostico_generato(classifica)
    record = {
        "id": gara_id,
        "etichetta": _etichetta_gara_archivio(intestazione, len(partenti)),
        "intestazione": dict(intestazione),
        "partenti": partenti.copy(),
        "classifica": classifica.copy(),
        "pronostico_generato": pronostico_generato,
        "mercato": stats_mercato,
        "ordine_arrivo": "",
        "salvata_il": salvato_il,
    }
    archivio = list(st.session_state.get("database_corse", []))
    archivio.append(record)
    st.session_state.database_corse = archivio
    st.session_state.gara_selezionata_id = gara_id
    st.session_state.dati_gara_dataframe = partenti.copy()
    st.session_state.sigma_value_bet = classifica.copy()
    st.session_state.intestazione_gara_corrente = dict(intestazione)
    return gara_id


def _gara_selezionata() -> dict | None:
    if st.session_state.get("dashboard_live_vuota"):
        return None
    archivio = st.session_state.get("database_corse", [])
    if not archivio:
        return None
    gara_id = st.session_state.get("gara_selezionata_id")
    if gara_id in (None, "", "__nuova_corsa__"):
        return None
    for gara in archivio:
        if gara.get("id") == gara_id:
            return gara
    return archivio[-1]


def _fmt_nd(valore: object) -> str:
    if valore is None or (isinstance(valore, float) and math.isnan(valore)):
        return "N/D"
    try:
        if pd.isna(valore):
            return "N/D"
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(valore):.1f}"
    except (TypeError, ValueError):
        testo = str(valore).strip()
        return testo if testo else "N/D"


def _fmt_score(valore: object) -> str:
    return _fmt_nd(valore)


def _valore_cella_presente(valore: object) -> bool:
    """True se il valore di cella è utilizzabile (evita ambiguità su pd.NA)."""
    if valore is None:
        return False
    try:
        if pd.isna(valore):
            return False
    except (TypeError, ValueError):
        pass
    testo = str(valore).strip()
    return testo != "" and testo.lower() not in {"nan", "none", "<na>"}


def _testo_cella_riga(riga: pd.Series, chiave: str, default: str = "") -> str:
    valore = riga.get(chiave)
    if not _valore_cella_presente(valore):
        return default
    return str(valore).strip()


def _testo_cella_riga_nd(riga: pd.Series, chiave: str) -> str:
    return _testo_cella_riga(riga, chiave, default="N/D")


def _float_cella_riga(riga: pd.Series, chiave: str, default: float = 0.0) -> float:
    valore = riga.get(chiave)
    if not _valore_cella_presente(valore):
        return default
    try:
        if pd.isna(valore):
            return default
        return float(valore)
    except (TypeError, ValueError):
        return default


def _bool_cella_riga(riga: pd.Series, chiave: str) -> bool:
    valore = riga.get(chiave)
    if not _valore_cella_presente(valore):
        return False
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, (int, float)):
        try:
            if pd.isna(valore):
                return False
        except (TypeError, ValueError):
            pass
        return bool(valore)
    testo = str(valore).strip().lower()
    return testo in {"1", "true", "yes", "si", "sì"}


def _classifica_ordinata(df_calcolato: pd.DataFrame) -> pd.DataFrame:
    if df_calcolato is None or df_calcolato.empty:
        return _dataframe_dati_gara_vuoto()
    if "Sigma Value Score" not in df_calcolato.columns:
        return df_calcolato
    valutabili = df_calcolato[df_calcolato["Sigma Value Score"].notna()].copy()
    altri = df_calcolato[df_calcolato["Sigma Value Score"].isna()].copy()
    if valutabili.empty:
        return df_calcolato.reset_index(drop=True)
    valutabili = valutabili.sort_values(
        by=["Sigma Value Score", "Elastico", "Regression"],
        ascending=[False, False, False],
    )
    return pd.concat([valutabili, altri], ignore_index=True)


def _html_pronto_streamlit(fragment: str) -> str:
    """
    Streamlit interpreta righe indentate (>=4 spazi) come codice Markdown.
    Rimuove l'indentazione così l'HTML viene renderizzato e non mostrato come testo.
    """
    return "\n".join(line.lstrip() for line in fragment.strip().splitlines())


def _st_html(fragment: str) -> None:
    st.markdown(_html_pronto_streamlit(fragment), unsafe_allow_html=True)


def _sigma_value_to_rating_5(sigma: object) -> float | None:
    """Converte Sigma Value Score (0–100, 1 dec.) in rating stelline 2.0–5.0."""
    if sigma is None or (isinstance(sigma, float) and math.isnan(sigma)):
        return None
    try:
        if pd.isna(sigma):
            return None
        valore = round(float(sigma), 1)
    except (TypeError, ValueError):
        return None
    if valore >= 95.0:
        return 5.0
    if valore >= 85.0:
        return 4.5
    if valore >= 75.0:
        return 4.0
    if valore >= 65.0:
        return 3.5
    if valore >= 55.0:
        return 3.0
    if valore >= 45.0:
        return 2.5
    return 2.0


def _sigma_value_score_per_stelle(riga: pd.Series) -> float | None:
    """Solo Sigma Value Score elaborato (mai Rating grezzo del parser)."""
    grezzo = riga.get("Sigma Value Score")
    if grezzo is None or (isinstance(grezzo, float) and math.isnan(grezzo)):
        return None
    try:
        if pd.isna(grezzo):
            return None
        return round(float(grezzo), 1)
    except (TypeError, ValueError):
        return None


def _probabilita_distribuzione_sigma_moduli(
    regression: float | None,
    quanta: float | None,
) -> float | None:
    """Probabilità implicita (0–1) dai moduli Regression/Quanta — benchmark assoluto."""
    moduli: list[tuple[float, float]] = []
    if regression is not None:
        moduli.append((float(regression), 0.30))
    if quanta is not None:
        moduli.append((float(quanta), 0.25))
    if not moduli:
        return None
    peso_tot = sum(peso for _val, peso in moduli)
    base = sum(val * peso for val, peso in moduli) / peso_tot
    return max(0.0, min(1.0, base / 100.0))


def _calcola_global_star_rating(
    spread_elastico: float | None,
    regression: float | None,
    quanta: float | None,
    quote_valide: list[float],
) -> float | None:
    """
    Indice di forza globale assoluto (0–100) per le stelline UI.
    Spread Elastico puro + scarto prob. Distribuzione Sigma vs quota reale ≥ 1.60.
    """
    if not quote_valide:
        return None
    quota_media = statistics.mean(quote_valide)
    if quota_media < 1.60:
        return None
    p_mercato = min(1.0, max(0.0, 1.0 / quota_media))
    p_sigma = _probabilita_distribuzione_sigma_moduli(regression, quanta)

    spread_pts = 0.0
    if spread_elastico is not None:
        spread_pts = max(0.0, min(45.0, float(spread_elastico))) / 45.0 * 45.0

    edge_pts = 0.0
    if p_sigma is not None:
        scarto_prob = p_sigma - p_mercato
        edge_pts = max(0.0, min(0.28, scarto_prob)) / 0.28 * 55.0

    if spread_elastico is None and p_sigma is None:
        return None

    return max(0.0, min(100.0, spread_pts + edge_pts))


def _global_star_rating_to_rating_5(indice: object) -> float | None:
    """Scala universale severa sull'Indice di Forza Globale (0–100)."""
    if indice is None or (isinstance(indice, float) and math.isnan(indice)):
        return None
    try:
        if pd.isna(indice):
            return None
        valore = float(indice)
    except (TypeError, ValueError):
        return None
    if valore >= 88.0:
        return 5.0
    if valore >= 74.0:
        return 4.5
    if valore >= 60.0:
        return 4.0
    if valore >= 48.0:
        return 3.5
    if valore >= 36.0:
        return 3.0
    if valore >= 24.0:
        return 2.5
    return 2.0


def _global_star_rating_riga(riga: pd.Series) -> float | None:
    """Indice globale dalla riga (o ricalcolo da moduli reali se assente in archivio)."""
    grezzo = riga.get("Global_Star_Rating")
    if grezzo is not None:
        try:
            if not pd.isna(grezzo):
                return float(grezzo)
        except (TypeError, ValueError):
            pass
    spread = riga.get("Spread_Elastico")
    regression = riga.get("Regression")
    quanta = riga.get("Quanta")
    try:
        if spread is not None and pd.isna(spread):
            spread = None
        if regression is not None and pd.isna(regression):
            regression = None
        if quanta is not None and pd.isna(quanta):
            quanta = None
    except TypeError:
        pass
    quote = _parse_quote_valide_cella(riga.get("Quote Valide"))
    return _calcola_global_star_rating(
        float(spread) if spread is not None else None,
        float(regression) if regression is not None else None,
        float(quanta) if quanta is not None else None,
        quote,
    )


def _html_stelle_sigma_rating(
    rating_5: float | None,
    colore_stelle: str = "#FFD700",
) -> str:
    """Stelle visive (★/½/☆) da Rating assoluto unificato (Rating ufficiale + Quanta)."""
    if rating_5 is None:
        return (
            "<div class='sigma-star-rating' style='display:flex;align-items:center;"
            "flex-wrap:nowrap;gap:0.15rem;margin:0 0 0.35rem 0;'>"
            "<span style='color:#666;font-size:1rem;letter-spacing:2px;line-height:1;'>"
            "☆☆☆☆☆</span>"
            "<span style='font-size:0.75rem;color:#888;'>N/D</span></div>"
        )
    val = max(2.0, min(5.0, float(rating_5)))
    colore = html.escape(colore_stelle)
    chunks: list[str] = []
    for star_idx in range(1, 6):
        if val >= star_idx:
            chunks.append(
                f"<span style='display:inline-flex;align-items:center;justify-content:center;"
                f"width:1.15em;height:1.15em;color:{colore};font-size:1.08rem;line-height:1;"
                f"-webkit-text-fill-color:{colore};text-shadow:0 0 8px {colore};'>★</span>"
            )
        elif val >= star_idx - 0.5:
            chunks.append(
                f"<span style='position:relative;display:inline-flex;align-items:center;"
                f"justify-content:flex-start;width:1.15em;height:1.15em;"
                f"font-size:1.08rem;line-height:1;flex-shrink:0;'>"
                f"<span style='color:#555;-webkit-text-fill-color:#555;'>★</span>"
                f"<span style='position:absolute;left:0;top:0;width:50%;height:100%;"
                f"overflow:hidden;display:flex;align-items:center;color:{colore};"
                f"-webkit-text-fill-color:{colore};text-shadow:0 0 8px {colore};'>★</span></span>"
            )
        else:
            chunks.append(
                "<span style='display:inline-flex;align-items:center;justify-content:center;"
                "width:1.15em;height:1.15em;color:#555;font-size:1.08rem;line-height:1;"
                "-webkit-text-fill-color:#555;'>☆</span>"
            )
    label = (
        f"<span style='color:#00FFCC;font-size:0.78rem;font-weight:700;"
        f"margin-left:0.2rem;line-height:1;white-space:nowrap;'>{val:.1f}/5</span>"
    )
    return (
        "<div class='sigma-star-rating' style='display:flex;align-items:center;"
        "flex-wrap:nowrap;gap:0.1rem;margin:0 0 0.35rem 0;'>"
        + "".join(chunks)
        + label
        + "</div>"
    )


def _quota_massima_valida_riga(riga: pd.Series) -> float | None:
    quote = _parse_quote_valide_cella(riga.get("Quote Valide"))
    if not quote:
        return None
    return float(max(quote))


def _quota_minima_valida_riga(riga: pd.Series) -> float | None:
    quote = _parse_quote_valide_cella(riga.get("Quote Valide"))
    if not quote:
        return None
    return float(min(quote))


def _testo_target_operativo(posizione_top: int) -> str:
    """Top 4 operativi: 1–2 Vincente, 3 Piazzato, 4 Sorpresa elastica (quota max)."""
    if posizione_top in (1, 2):
        return "🔥 TARGET: VINCENTE"
    if posizione_top == 3:
        return "🎯 TARGET: PIAZZATO"
    if posizione_top == 4:
        return "⚡ TARGET: SORPRESA ELASTICA"
    return ""


def _numero_cavalli_con_quote_valide(df: pd.DataFrame) -> int:
    """Partenti con almeno una quota valida (≥1.60) — nessun dato simulato."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    return sum(
        1
        for _idx, riga in df.iterrows()
        if _quota_massima_valida_riga(riga) is not None
    )


def _valore_numerico_cella(valore: object) -> float | None:
    if valore is None:
        return None
    try:
        if pd.isna(valore):
            return None
        return float(valore)
    except (TypeError, ValueError):
        return None


def _quota_passa_filtri_anti_lavagna_target3(riga: pd.Series) -> float | None:
    """
    Quota reale utilizzabile per Target 3 Elastico Premium:
    > 1.60 e non oltre soglia outsider anti-lavagna (≤ 25.0).
    """
    quota_max = _quota_massima_valida_riga(riga)
    if quota_max is None:
        return None
    if quota_max <= 1.60 or quota_max > 25.0:
        return None
    return quota_max


def _score_elastico_premium_riga(riga: pd.Series) -> float | None:
    """
    Anomalia elastica rilevante (Distribuzione Sigma):
    priorità al Modulo Elastico > 0; altrimenti gap Quanta−Regression > 0
    (forma recente superiore al Regression).
    """
    elastico = _valore_numerico_cella(riga.get("Elastico"))
    if elastico is not None and elastico > 0.0:
        return elastico
    regression = _valore_numerico_cella(riga.get("Regression"))
    quanta = _valore_numerico_cella(riga.get("Quanta"))
    if regression is None or quanta is None:
        return None
    gap_forma = quanta - regression
    if gap_forma > 0.0:
        return gap_forma
    return None


def _seleziona_target3_elastico_premium(resto: pd.DataFrame) -> pd.DataFrame:
    """
    Target 3 — Elastico Premium: dal 3° Sigma in giù, anomalia elastica
    positiva più alta (quota > 1.60 e filtri anti-lavagna).
    """
    if resto is None or resto.empty:
        return pd.DataFrame()

    migliore_indice = None
    migliore_score = float("-inf")
    for indice, riga in resto.iterrows():
        if _quota_passa_filtri_anti_lavagna_target3(riga) is None:
            continue
        score = _score_elastico_premium_riga(riga)
        if score is None:
            continue
        if score > migliore_score:
            migliore_score = score
            migliore_indice = indice

    if migliore_indice is None:
        return pd.DataFrame()
    return resto.loc[[migliore_indice]].copy()


def _seleziona_sorpresa_elastica(resto: pd.DataFrame) -> pd.DataFrame:
    """Dal resto dopo Top 3: quota ≥6.00, poi Elastico e Sigma Value Score."""
    if resto is None or resto.empty:
        return pd.DataFrame()

    candidati: list[tuple[object, float]] = []
    for indice, riga in resto.iterrows():
        quota_max = _quota_massima_valida_riga(riga)
        if quota_max is None or quota_max < 6.00:
            continue
        candidati.append((indice, quota_max))

    if not candidati:
        return pd.DataFrame()

    def _chiave_ordinamento(item: tuple[object, float]) -> tuple[float, float]:
        indice, _quota = item
        riga = resto.loc[indice]
        elastico = _valore_numerico_cella(riga.get("Elastico"))
        sigma = _valore_numerico_cella(riga.get("Sigma Value Score"))
        return (
            elastico if elastico is not None else float("-inf"),
            sigma if sigma is not None else float("-inf"),
        )

    candidati.sort(key=_chiave_ordinamento, reverse=True)
    indice_scelto, quota_scelta = candidati[0]
    scelta = resto.loc[[indice_scelto]].copy()
    scelta["Quota_Sorpresa_Elastica"] = quota_scelta
    return scelta


def _seleziona_quattro_target_sigma(valutabili: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Target 1–2: Sigma Value Score più alti.
    Target 3: Elastico Premium (anomalia positiva max dal 3° in giù).
    Target 4: Sorpresa elastica (quota ≥6) sul resto.
    """
    if valutabili is None or valutabili.empty:
        vuoto = pd.DataFrame()
        return {
            "vincenti": vuoto,
            "piazzato": vuoto,
            "sorpresa": vuoto,
            "top4": vuoto,
        }

    vincenti = valutabili.iloc[0:2].copy()
    pool_dal_terzo = valutabili.iloc[2:].copy()

    piazzato = _seleziona_target3_elastico_premium(pool_dal_terzo)
    if piazzato.empty:
        piazzato = (
            valutabili.iloc[2:3].copy() if len(valutabili) >= 3 else pd.DataFrame()
        )
        resto = valutabili.iloc[3:].copy()
    else:
        n_scelto = piazzato.iloc[0].get("N°")
        resto = pool_dal_terzo[
            pool_dal_terzo["N°"].astype(str) != str(n_scelto)
        ].copy()

    sorpresa = pd.DataFrame()
    if _numero_cavalli_con_quote_valide(valutabili) >= 4:
        sorpresa = _seleziona_sorpresa_elastica(resto)

    pezzi = [df for df in (vincenti, piazzato, sorpresa) if not df.empty]
    top4 = pd.concat(pezzi, ignore_index=True) if pezzi else pd.DataFrame()
    return {
        "vincenti": vincenti,
        "piazzato": piazzato,
        "sorpresa": sorpresa,
        "top4": top4,
    }


def _numeri_target_operativi(sel: dict[str, pd.DataFrame]) -> dict[object, str]:
    """Mappa N° partente → etichetta target per Consiglio_Operativo."""
    mappa: dict[object, str] = {}
    vincenti = sel.get("vincenti")
    if isinstance(vincenti, pd.DataFrame) and not vincenti.empty:
        if len(vincenti) >= 1:
            mappa[vincenti.iloc[0].get("N°")] = _testo_target_operativo(1)
        if len(vincenti) >= 2:
            mappa[vincenti.iloc[1].get("N°")] = _testo_target_operativo(2)
    piazzato = sel.get("piazzato")
    if isinstance(piazzato, pd.DataFrame) and not piazzato.empty:
        mappa[piazzato.iloc[0].get("N°")] = _testo_target_operativo(3)
    sorpresa = sel.get("sorpresa")
    if isinstance(sorpresa, pd.DataFrame) and not sorpresa.empty:
        mappa[sorpresa.iloc[0].get("N°")] = _testo_target_operativo(4)
    return mappa


def _html_etichetta_target_cima(testo: str) -> str:
    if not str(testo or "").strip():
        return ""
    testo_safe = html.escape(str(testo).strip())
    if "SORPRESA" in testo:
        colore, sfondo = "#FF00FF", "rgba(255,0,255,0.16)"
    elif "PIAZZATO" in testo:
        colore, sfondo = "#00E5FF", "rgba(0,229,255,0.18)"
    else:
        colore, sfondo = "#00FF66", "rgba(0,255,102,0.16)"
    return _html_pronto_streamlit(
        f"""
        <div style="margin:0 0 0.55rem 0;padding:0.5rem 0.6rem;border-radius:10px;
            border:2px solid {colore};background:{sfondo};color:{colore};
            font-weight:900;font-size:0.95rem;letter-spacing:0.03em;
            text-shadow:0 0 10px {colore};text-align:center;">
            {testo_safe}
        </div>
        """
    )


def _html_blocco_consiglio_operativo(testo: str) -> str:
    if not str(testo or "").strip():
        return ""
    testo_safe = html.escape(str(testo).strip())
    if "SORPRESA" in testo:
        colore, sfondo = "#E040FB", "rgba(224,64,251,0.14)"
    elif "PIAZZATO" in testo:
        colore, sfondo = "#00E5FF", "rgba(0,229,255,0.12)"
    else:
        colore, sfondo = "#00FF66", "rgba(0,255,102,0.14)"
    return _html_pronto_streamlit(
        f"""
        <div style="margin-top:0.45rem;padding:0.45rem 0.55rem;border-radius:8px;
            border:1px solid {colore};background:{sfondo};color:{colore};
            font-weight:800;font-size:0.82rem;text-shadow:0 0 8px {colore};">
            {testo_safe}
        </div>
        """
    )


def _applica_target_operativi_top4(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Sigma Value Score" not in df.columns:
        return df
    lavoro = df.copy()
    valutabili = lavoro[lavoro["Sigma Value Score"].notna()].reset_index(drop=True)
    sel = _seleziona_quattro_target_sigma(valutabili)
    mappa = _numeri_target_operativi(sel)
    consigli: list[str] = []
    for _idx, riga in lavoro.iterrows():
        consigli.append(str(mappa.get(riga.get("N°"), "") or ""))
    lavoro["Consiglio_Operativo"] = consigli
    return lavoro


def _quota_sorpresa_elastica_riga(riga: pd.Series) -> float | None:
    quota_alert = riga.get("Quota_Sorpresa_Elastica")
    if quota_alert is not None:
        try:
            if not pd.isna(quota_alert):
                return float(quota_alert)
        except (TypeError, ValueError):
            pass
    return _quota_massima_valida_riga(riga)


def _html_box_sorpresa_elastica_dedicato(card_html: str, quota: float) -> str:
    quota_txt = html.escape(f"{quota:.2f}")
    return _html_pronto_streamlit(
        f"""
        <div style="width:100%;box-sizing:border-box;margin:0.5rem 0 1rem 0;
            padding:1rem 1.1rem 1.15rem;border-radius:16px;
            border:2px solid #E040FB;
            background:linear-gradient(145deg,rgba(18,8,28,0.96),rgba(8,12,22,0.94));
            box-shadow:0 0 28px rgba(255,0,255,0.35), inset 0 0 40px rgba(224,64,251,0.08);">
            <div style="text-align:center;color:#FF66FF;font-weight:900;font-size:1rem;
                letter-spacing:0.06em;text-shadow:0 0 14px #FF00FF;margin-bottom:0.55rem;">
                ⚡ TARGET SPECIALE: SORPRESA ELASTICA ALTA QUOTA
            </div>
            <div style="text-align:center;margin-bottom:0.75rem;">
                <div style="color:#B8A0C8;font-size:0.72rem;font-weight:700;
                    letter-spacing:0.12em;text-transform:uppercase;">
                    Quota massima rilevata · Distribuzione Sigma
                </div>
                <div style="color:#39FF14;font-size:2.65rem;font-weight:900;line-height:1.05;
                    text-shadow:0 0 22px #39FF14, 0 0 36px rgba(255,0,255,0.45);
                    margin-top:0.15rem;">
                    {quota_txt}
                </div>
            </div>
            <div style="width:100%;">{card_html}</div>
        </div>
        """
    )


def _render_box_sorpresa_elastica_separato(sorpresa_df: pd.DataFrame) -> None:
    if sorpresa_df is None or sorpresa_df.empty:
        return
    st.markdown(
        "<hr style='border: 1px solid #333; margin: 1.1rem 0;'>",
        unsafe_allow_html=True,
    )
    for _idx, riga in sorpresa_df.iterrows():
        quota = _quota_sorpresa_elastica_riga(riga)
        if quota is None:
            continue
        card = _card_cavallo_html(
            riga,
            4,
            target_principale=True,
            include_barre_densita=False,
            nascondi_etichetta_target=True,
        )
        _st_html(_html_box_sorpresa_elastica_dedicato(card, quota))


def _split_top4_target(
    valutabili: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """2 Vincenti · 1 Piazzato · 1 Sorpresa elastica (quota max tra i restanti)."""
    sel = _seleziona_quattro_target_sigma(valutabili)
    return sel["vincenti"], sel["piazzato"], sel["sorpresa"]


def _render_griglia_pronostico_target(
    vincenti_df: pd.DataFrame,
    piazzato_df: pd.DataFrame,
    sorpresa_df: pd.DataFrame,
    targets_df: pd.DataFrame,
    *,
    mostra_barre_densita: bool = True,
) -> None:
    """Card HTML target Vincenti / Piazzato / Sorpresa elastica."""
    if not vincenti_df.empty:
        st.markdown("#### 🔥 TARGET VINCENTE")
        cards_v: list[str] = []
        # Converti il DataFrame in una lista di (idx, riga) per manipolare l'ordine
        vincenti_list = list(vincenti_df.iterrows())
        
        # Swap visivo dei primi due cavalli
        if len(vincenti_list) >= 2:
            vincenti_list[0], vincenti_list[1] = vincenti_list[1], vincenti_list[0]
            
        for i, (_idx, riga) in enumerate(vincenti_list):
            posizione = i + 1
            cards_v.append(
                _card_cavallo_html(
                    riga,
                    posizione,
                    target_principale=True,
                    include_barre_densita=False,
                    mostra_gattino=(posizione == 1),
                )
            )
        cols = 2 if len(cards_v) > 1 else 1
        _st_html(
            f"<div style='display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));"
            f"gap:0.75rem;margin-bottom:0.75rem;'>{''.join(cards_v)}</div>"
        )

    if not piazzato_df.empty:
        st.markdown("#### 🎯 TARGET PIAZZATO")
        cards_p: list[str] = []
        for (_idx, riga) in piazzato_df.iterrows():
            cards_p.append(
                _card_cavallo_html(
                    riga,
                    3,
                    target_principale=True,
                    include_barre_densita=False,
                )
            )
        _st_html(
            f"<div style='display:grid;grid-template-columns:minmax(0,1fr);"
            f"gap:0.75rem;margin-bottom:0.75rem;'>{''.join(cards_p)}</div>"
        )

    if not sorpresa_df.empty:
        _render_box_sorpresa_elastica_separato(sorpresa_df)

    if mostra_barre_densita and not targets_df.empty:
        st.markdown("### Densità Sigma e Field Tilt — Target Operativi (Top 4)")
        for posizione, (_idx, riga) in enumerate(targets_df.iterrows(), start=1):
            numero = str(riga.get("N°", riga.get("Numero", ""))).strip()
            nome = str(riga.get("Nome", "N/D")).strip()
            etichetta = f"{numero} - {nome}" if numero else nome
            ruolo = str(riga.get("Consiglio_Operativo") or "").strip()
            titolo = f"{posizione}° · {etichetta}"
            if ruolo:
                titolo = f"{titolo} ({ruolo})"
            _st_html(_html_barre_densita_target(riga, titolo))


def _render_storico_pronostico_sigma(gara: dict) -> None:
    st.markdown("### Storico Pronostico Sigma")
    pronostico = gara.get("pronostico_generato")
    if not isinstance(pronostico, dict):
        classifica = gara.get("classifica")
        if isinstance(classifica, pd.DataFrame) and not classifica.empty:
            pronostico = _costruisci_pronostico_generato(classifica)
        else:
            st.warning("Assenza di dati - Nessun pronostico archiviato per questa corsa")
            return

    vincenti_df = pronostico.get("vincenti")
    piazzato_df = pronostico.get("piazzato")
    sorpresa_df = pronostico.get("sorpresa")
    if not isinstance(piazzato_df, pd.DataFrame) or piazzato_df.empty:
        legacy = pronostico.get("piazzati")
        if isinstance(legacy, pd.DataFrame) and not legacy.empty:
            piazzato_df = legacy.iloc[0:1]
    if not isinstance(vincenti_df, pd.DataFrame):
        vincenti_df = pd.DataFrame()
    if not isinstance(piazzato_df, pd.DataFrame):
        piazzato_df = pd.DataFrame()
    if not isinstance(sorpresa_df, pd.DataFrame):
        sorpresa_df = pd.DataFrame()
    top4_df = pronostico.get("top4")
    if not isinstance(top4_df, pd.DataFrame) or top4_df.empty:
        top4_df = pd.concat(
            [vincenti_df, piazzato_df, sorpresa_df], ignore_index=True
        )

    generato_il = str(pronostico.get("generato_il") or "").strip()
    if generato_il:
        st.caption(f"Fotografia pronostico Sigma: {html.escape(generato_il)}")

    _render_griglia_pronostico_target(
        vincenti_df,
        piazzato_df,
        sorpresa_df,
        top4_df,
        mostra_barre_densita=True,
    )

    ordine = str(gara.get("ordine_arrivo") or "").strip()
    if not ordine:
        with sqlite3.connect(DB_PATH) as conn:
            riga = conn.execute(
                "SELECT ordine_arrivo FROM ordini_arrivo_gare WHERE gara_id = ?",
                (str(gara.get("id")),),
            ).fetchone()
        if riga:
            ordine = str(riga[0] or "").strip()
    if ordine:
        fotofinish_html = _html_esito_fotofinish_ufficiale(gara, ordine)
        if fotofinish_html:
            _st_html(fotofinish_html)
    else:
        st.caption("Ordine di Arrivo reale: N/D (non ancora registrato)")


def _html_barra_progresso(etichetta: str, percentuale: float, colore: str) -> str:
    pct = max(0.0, min(100.0, percentuale))
    etichetta_safe = html.escape(etichetta)
    return _html_pronto_streamlit(
        f"""
        <div style="margin:0.35rem 0 0.65rem 0;">
            <div style="color:#00FFCC;font-size:0.78rem;margin-bottom:0.2rem;">
                {etichetta_safe} {pct:.1f}%
            </div>
            <div style="background:rgba(255,255,255,0.08);border-radius:8px;height:10px;overflow:hidden;">
                <div style="width:{pct:.1f}%;height:100%;background:{colore};
                    box-shadow:0 0 10px {colore};"></div>
            </div>
        </div>
        """
    )


def _html_micro_barra(
    etichetta: str,
    percentuale: float | None,
    colore: str,
    valore_testo: str,
) -> str:
    if percentuale is None:
        pct = 0.0
        fill = "0"
    else:
        pct = max(0.0, min(100.0, percentuale))
        fill = f"{pct:.1f}"
    etichetta_safe = html.escape(etichetta)
    valore_safe = html.escape(valore_testo)
    return _html_pronto_streamlit(
        f"""
        <div style="margin:0.2rem 0 0.35rem 0;">
            <div style="display:flex;justify-content:space-between;color:#9FE;font-size:0.72rem;">
                <span>{etichetta_safe}</span><span>{valore_safe}</span>
            </div>
            <progress value="{fill}" max="100" style="width:100%;height:7px;accent-color:{colore};"></progress>
        </div>
        """
    )


def _eta_anni(valore: object) -> float | None:
    testo = str(valore or "").strip().upper()
    match = re.fullmatch(r"(\d{1,2})YO", testo)
    if not match:
        return None
    return float(match.group(1))


def _indice_confidenza_sigma_quote(quote: list[float]) -> float | None:
    """Confidenza da dispersione quote valide del singolo partente (solo dati reali)."""
    if len(quote) < 2:
        return None
    media = statistics.mean(quote)
    if media <= 0:
        return None
    deviazione = statistics.pstdev(quote)
    rapporto = deviazione / media
    return max(0.0, min(100.0, 100.0 * (1.0 - min(1.0, rapporto))))


def _parse_quote_valide_cella(valore: object) -> list[float]:
    testo = str(valore or "").strip()
    if not testo or testo.lower() in {"nan", "none", "<na>", "n/d"}:
        return []
    quote: list[float] = []
    for pezzo in re.split(r"[|;\s]+", testo):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        try:
            quota = float(pezzo.replace(",", "."))
        except ValueError:
            continue
        if quota >= SOGLIA_QUOTA_VINCENTE_SIGMA:
            quote.append(quota)
    return quote[:MAX_QUOTE_MERCATO_UTILI]


def _punteggio_ultimi_arrivi(valore: object) -> float | None:
    """Quanta: sequenze Forma_Storica, cifre compatte o codici letterali reali."""
    testo = str(valore or "").strip()
    if not testo:
        return None
    if FORMA_STORICA_SEQUENZA_RE.search(testo) or " - " in testo or (
        "-" in testo and not QUOTA_DECIMALE_RE.search(testo)
    ):
        score = _calcola_quanta_da_arrivi(testo)
        if score is not None:
            return score
    if testo.isdigit():
        cifre = [int(c) for c in testo]
        if not cifre:
            return None
        media = statistics.mean(cifre)
        return max(0.0, min(100.0, (10.0 - media) / 10.0 * 100.0))
    if ULTIMI_ARRIVO_LETTERALE_RE.fullmatch(testo):
        media = QUANTA_PENALITA_ARRIVO_LETTERALE
        return max(0.0, min(100.0, (10.0 - media) / 10.0 * 100.0))
    return _calcola_quanta_da_arrivi(testo)


def _overround_lavagna_corsa(df: pd.DataFrame) -> float | None:
    """Somma probabilità implicite (quota max per partente); None se quote assenti."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    quote_massime_corsa_valide: list[float] = []
    for _idx, riga in df.iterrows():
        quota_max = _quota_massima_valida_riga(riga)
        if quota_max is not None and quota_max > 0:
            quote_massime_corsa_valide.append(quota_max)
    if not quote_massime_corsa_valide:
        return None
    overround = sum(1.0 / q for q in quote_massime_corsa_valide)
    if overround < 1.0:
        overround = 1.0
    return overround


def _fair_odds_da_sigma(sigma_score: float | None) -> float | None:
    """Quota equa derivata dalla probabilità Sigma, non dalla quota bookmaker."""
    if sigma_score is None or sigma_score <= 0:
        return None
    probabilita_sigma = max(0.01, min(1.0, sigma_score / 100.0))
    return 1.0 / probabilita_sigma


def calcola_value_bet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Protocollo Sigma 4.0 sul DataFrame del parser.
    Usa esclusivamente i campi reali presenti; niente dati inventati.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return _dataframe_dati_gara_vuoto()

    lavoro = df.copy()
    rating_numerici = pd.to_numeric(lavoro.get("Rating"), errors="coerce")
    rating_max = float(rating_numerici.max()) if rating_numerici.notna().any() else None

    regression_scores: list[float | None] = []
    quanta_scores: list[float | None] = []
    elastico_scores: list[float] = []
    sigma_scores: list[float | None] = []
    densita_sigma: list[float] = []
    field_tilt: list[float] = []
    anomalie: list[str] = []
    indice_confidenza: list[float | None] = []
    spread_elastico: list[float | None] = []
    alert_anomalia: list[bool] = []
    global_star_rating: list[float | None] = []
    fair_odds_scores: list[float | None] = []
    value_bet_scores: list[bool] = []
    value_edge_scores: list[float | None] = []

    overround_lavagna = _overround_lavagna_corsa(lavoro)

    def _quote_da_cella_soglia(valore: object, soglia: float) -> list[float]:
        testo = str(valore or "").strip()
        if not testo or testo.lower() in {"nan", "none", "<na>", "n/d"}:
            return []
        quote_soglia: list[float] = []
        for pezzo in re.split(r"[|;\s]+", testo):
            pezzo = pezzo.strip()
            if not pezzo:
                continue
            try:
                quota = float(pezzo.replace(",", "."))
            except ValueError:
                continue
            if quota >= soglia:
                quote_soglia.append(quota)
        return quote_soglia[:MAX_QUOTE_MERCATO_UTILI]

    def _quota_massima_soglia_riga(riga: pd.Series, soglia: float) -> float | None:
        quote_soglia = _quote_da_cella_soglia(riga.get("Quote Valide"), soglia)
        if not quote_soglia:
            return None
        return float(max(quote_soglia))

    per_indice_quota_std: dict[object, float | None] = {}
    quote_massime_valide: list[float] = []
    for indice_pre, riga_pre in lavoro.iterrows():
        quota_std = _quota_massima_valida_riga(riga_pre)
        per_indice_quota_std[indice_pre] = quota_std
        if quota_std is not None:
            quote_massime_valide.append(quota_std)

    quota_favorito_assoluto: float | None = (
        min(quote_massime_valide) if quote_massime_valide else None
    )
    for indice, riga in lavoro.iterrows():
        quota_std_riga = per_indice_quota_std.get(indice)
        is_favorito_assoluto = False
        if quota_favorito_assoluto is not None:
            quota_confronto = quota_std_riga
            if (
                quota_confronto is not None
                and abs(quota_confronto - quota_favorito_assoluto) < 1e-6
            ):
                is_favorito_assoluto = True

        rating = rating_numerici.loc[indice]
        eta = _eta_anni(riga.get("Età"))
        quote = _parse_quote_valide_cella(riga.get("Quote Valide"))
        quota_max = _quota_massima_valida_riga(riga)

        forma_txt = ""
        for chiave_forma in ("Forma_Storica", "Ultimi Arrivi"):
            val_forma = riga.get(chiave_forma)
            try:
                if val_forma is not None and pd.notna(val_forma):
                    cand = str(val_forma).strip()
                    if cand and cand.lower() not in {"nan", "none", "<na>"}:
                        forma_txt = cand
                        break
            except (TypeError, ValueError):
                continue
        score_forma = _calcola_quanta_da_arrivi(forma_txt) if forma_txt else None

        quanta = _punteggio_ultimi_arrivi(riga.get("Ultimi Arrivi"))
        if quanta is None:
            quanta = score_forma
        if quanta is None:
            try:
                quanta_pre = riga.get("Quanta")
                if quanta_pre is not None and pd.notna(quanta_pre):
                    quanta = float(quanta_pre)
            except (TypeError, ValueError):
                quanta = None

        # Modulo Regression: Rating alto = meglio, bilanciato con l'età reale.
        if pd.isna(rating):
            regression = None
        else:
            base = float(rating)
            if rating_max and rating_max > 0:
                base = (base / rating_max) * 100.0
            if eta is not None:
                # Età più giovane sostiene leggermente il rating lineare.
                bilanciamento = max(0.85, min(1.15, 1.0 + (5.0 - eta) / 20.0))
                base *= bilanciamento
            regression = max(0.0, min(100.0, base))
        if regression is None:
            try:
                reg_pre = riga.get("Regression")
                if reg_pre is not None and pd.notna(reg_pre):
                    regression = float(reg_pre)
            except (TypeError, ValueError):
                regression = None
        if regression is None and score_forma is not None:
            regression = score_forma

        # Modulo Quanta da Ultimi Arrivi / Forma_Storica reale.
        confidenza = _indice_confidenza_sigma_quote(quote)
        if regression is not None and quanta is not None:
            spread_reg_quanta = float(regression) - float(quanta)
        else:
            spread_reg_quanta = None

        # Modulo Elastico: priorità assoluta su anomalia Rating alto + quota alta.
        elastico = 0.0
        label_anomalia = "Assenza di dati"
        alert_elastico = False
        if not pd.isna(rating) and quote:
            quota_media = statistics.mean(quote)
            rating_alto = (
                rating_max is not None
                and rating_max > 0
                and float(rating) >= 0.75 * rating_max
            )
            if rating_alto and quota_media >= 5.0:
                # Anomalia elastica positiva: Value Bet potenzialmente sotto-prezzata.
                elastico = min(
                    100.0,
                    (float(rating) / max(rating_max, 1.0)) * 55.0
                    + min(quota_media, 20.0) / 20.0 * 45.0,
                )
                label_anomalia = "Anomalia elastica positiva"
                alert_elastico = True
            elif rating_alto and quota_media >= 1.60:
                elastico = min(60.0, (float(rating) / max(rating_max, 1.0)) * 40.0)
                label_anomalia = "Discrepanza lieve"
            else:
                label_anomalia = "Nessuna anomalia"
        elif not quote:
            label_anomalia = "Assenza di quote valide ≥ 1.60"

        moduli_validi: list[tuple[float, float]] = []
        if regression is not None:
            moduli_validi.append((regression, 0.30))
        if quanta is not None:
            moduli_validi.append((quanta, 0.25))

        if not moduli_validi and elastico <= 0:
            sigma = None
            densita = 0.0
            tilt = 0.0
        else:
            if moduli_validi:
                peso_tot = sum(peso for _val, peso in moduli_validi)
                base_sigma = (
                    sum(val * peso for val, peso in moduli_validi) / peso_tot
                )
            else:
                base_sigma = 0.0
            sigma = base_sigma
            if elastico > base_sigma:
                sigma = (base_sigma * 0.45) + (elastico * 0.55)
            else:
                sigma = base_sigma + (elastico * 0.15)
            sigma = max(0.0, min(100.0, sigma))
            if is_favorito_assoluto:
                sigma = min(100.0, sigma + 12.0)
            # Smart Money Fusion — incrocio statistica-mercato (Distribuzione Sigma)
            if quota_max is not None and quota_max > 0:
                quota_ideale_sigma = (
                    100.0 / base_sigma if base_sigma > 1.0 else 999.0
                )
                if (
                    quota_max < quota_ideale_sigma
                    and base_sigma >= 45.0
                    and quota_max <= 15.0
                ):
                    rapporto_paura = quota_ideale_sigma / quota_max
                    bonus_insider = 12.0 + (rapporto_paura * 8.0)
                    sigma = min(100.0, sigma + bonus_insider)
            # Taglio Netto Outsider — filtro probabilità (Distribuzione Sigma)
            if quota_max is not None:
                if quota_max > 40.0:
                    sigma = min(sigma, 25.0)
                elif quota_max > 25.0:
                    sigma = min(sigma, 45.0)
            sigma = max(0.0, min(100.0, sigma))
            densita = sigma / 100.0
            tilt = (
                (statistics.mean(quote) - 1.60) / 18.40
                if quote
                else 0.0
            )
            tilt = max(0.0, min(1.0, tilt))

        fair_odds = _fair_odds_da_sigma(sigma)
        if quota_max is not None and fair_odds is not None:
            value_edge = (quota_max / fair_odds) - 1.0
            is_value_bet = value_edge > 0.0
        else:
            value_edge = None
            is_value_bet = False

        regression_scores.append(regression)
        quanta_scores.append(quanta)
        elastico_scores.append(elastico)
        sigma_scores.append(sigma)
        densita_sigma.append(densita)
        field_tilt.append(tilt)
        anomalie.append(label_anomalia)
        indice_confidenza.append(confidenza)
        spread_elastico.append(spread_reg_quanta)
        alert_anomalia.append(alert_elastico)
        fair_odds_scores.append(fair_odds)
        value_bet_scores.append(is_value_bet)
        value_edge_scores.append(value_edge)
        global_star_rating.append(
            _calcola_global_star_rating(
                spread_reg_quanta,
                regression,
                quanta,
                quote,
            )
        )

    lavoro["Regression"] = regression_scores
    lavoro["Quanta"] = quanta_scores
    lavoro["Elastico"] = elastico_scores
    lavoro["Sigma Value Score"] = sigma_scores
    lavoro["Densità Sigma"] = densita_sigma
    lavoro["Field Tilt"] = field_tilt
    lavoro["Anomalia"] = anomalie
    lavoro["Indice_Confidenza_Sigma"] = indice_confidenza
    lavoro["Spread_Elastico"] = spread_elastico
    lavoro["Alert_Anomalia"] = alert_anomalia
    lavoro["Global_Star_Rating"] = global_star_rating
    lavoro["Fair_Odds"] = fair_odds_scores
    lavoro["Value_Bet"] = value_bet_scores
    lavoro["Value_Edge"] = value_edge_scores
    if overround_lavagna is not None:
        lavoro.attrs["overround_lavagna"] = overround_lavagna

    valutabili = lavoro[lavoro["Sigma Value Score"].notna()].copy()
    if valutabili.empty:
        return lavoro.sort_values(by=["N°"], ascending=True).reset_index(drop=True)
    altri = lavoro[lavoro["Sigma Value Score"].isna()].copy()
    valutabili = valutabili.sort_values(
        by=["Sigma Value Score", "Elastico", "Regression"],
        ascending=[False, False, False],
    )
    risultato = pd.concat([valutabili, altri], ignore_index=True)
    return _applica_target_operativi_top4(risultato)


def _render_selettore_gara_salvata() -> dict | None:
    # Modalità usa e getta - niente storico selezionabile, ritorniamo solo l'ultima gara calcolata
    archivio = list(st.session_state.get("database_corse", []))
    if not archivio:
        return None
    
    gara = archivio[-1]
    st.session_state.dashboard_live_vuota = False
    st.session_state.dati_gara_dataframe = gara["partenti"]
    st.session_state.intestazione_gara_corrente = dict(gara["intestazione"])
    st.session_state.sigma_value_bet = gara["classifica"]
    return gara
    classifica_salvata = gara.get("classifica")
    if isinstance(classifica_salvata, pd.DataFrame) and not classifica_salvata.empty:
        st.session_state.sigma_value_bet = classifica_salvata.copy()
    return gara


def _indice_spread_dominanza(
    classifica: pd.DataFrame | None,
) -> tuple[str, float | None]:
    """
    Spread di Dominanza (Distribuzione Sigma): delta Score 1° vs 2°.
    Solo punteggi reali; nessun dato simulato.
    """
    nd = "N/D (Dati insufficienti per l'Indice di Dominanza)"
    if classifica is None or not isinstance(classifica, pd.DataFrame) or classifica.empty:
        return nd, None
    if "Sigma Value Score" not in classifica.columns:
        return nd, None
    valutabili = classifica[classifica["Sigma Value Score"].notna()].copy()
    if len(valutabili) < 2:
        return nd, None
    sort_cols = ["Sigma Value Score"]
    ascending = [False]
    if "Elastico" in valutabili.columns:
        sort_cols.append("Elastico")
        ascending.append(False)
    if "Regression" in valutabili.columns:
        sort_cols.append("Regression")
        ascending.append(False)
    valutabili = valutabili.sort_values(by=sort_cols, ascending=ascending)
    try:
        score_1 = float(valutabili.iloc[0]["Sigma Value Score"])
        score_2 = float(valutabili.iloc[1]["Sigma Value Score"])
    except (TypeError, ValueError):
        return nd, None
    if math.isnan(score_1) or math.isnan(score_2):
        return nd, None
    delta_dominanza = score_1 - score_2
    if delta_dominanza >= 15.0:
        status_corsa = (
            "🟢 CORSA AD ALTA FIDUCIA (Dominanza Netta - Spread > 15)"
        )
    elif delta_dominanza >= 7.0:
        status_corsa = "🟡 CORSA GIOCABILE (Equilibrio Moderato)"
    else:
        status_corsa = (
            "🔴 NO BET - CORSA TROPPO BILANCIATA (Lotteria - Spread < 7)"
        )
    return status_corsa, delta_dominanza


def _render_analisi_mercato_globale(gara: dict) -> None:
    mercato = dict(gara.get("mercato") or {})
    if not mercato.get("quota_media") and gara.get("partenti") is not None:
        mercato = {
            **mercato,
            **_statistiche_mercato_da_dataframe(gara["partenti"]),
        }
    quota_media = mercato.get("quota_media")
    scartate = mercato.get("quote_scartate")
    quota_txt = (
        f"{float(quota_media):.2f}"
        if quota_media is not None
        and not (isinstance(quota_media, float) and math.isnan(quota_media))
        else "N/D"
    )
    if scartate is None:
        scartate_txt = "N/D"
    else:
        scartate_txt = str(int(scartate))

    overround_lavagna: float | None = None
    classifica = gara.get("classifica")
    if isinstance(classifica, pd.DataFrame) and not classifica.empty:
        overround_lavagna = classifica.attrs.get("overround_lavagna")
        if overround_lavagna is None:
            overround_lavagna = _overround_lavagna_corsa(classifica)
    if overround_lavagna is None:
        partenti = gara.get("partenti")
        if isinstance(partenti, pd.DataFrame) and not partenti.empty:
            overround_lavagna = _overround_lavagna_corsa(partenti)

    lavagna_badge = ""
    if overround_lavagna is not None:
        lavagna_pct = (overround_lavagna * 100.0) - 100.0
        lavagna_badge = (
            f'<div><span style="color:#7AD;">Tassa Bookmaker (Lavagna):</span> '
            f'<strong style="color:#FF4444;"> {html.escape(f"{lavagna_pct:.1f}")}%</strong></div>'
        )

    status_corsa, delta_dominanza = _indice_spread_dominanza(
        classifica if isinstance(classifica, pd.DataFrame) else None
    )
    if (
        status_corsa.startswith("N/D")
        and isinstance(gara.get("partenti"), pd.DataFrame)
        and not gara["partenti"].empty
    ):
        classifica_live = calcola_value_bet(gara["partenti"])
        status_corsa, delta_dominanza = _indice_spread_dominanza(classifica_live)

    if delta_dominanza is not None:
        delta_txt = f"{delta_dominanza:.1f}"
        colore_status = (
            "#00FF66"
            if delta_dominanza >= 15.0
            else "#FFD700"
            if delta_dominanza >= 7.0
            else "#FF4444"
        )
    else:
        delta_txt = "N/D"
        colore_status = "#8899AA"

    _st_html(
        f"""
        <div style="
            background: rgba(8,10,14,0.92);
            border: 1px solid rgba(0,255,204,0.45);
            box-shadow: 0 0 12px rgba(0,255,204,0.35);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            margin: 0.5rem 0 0.75rem 0;">
            <div style="color:#00FFCC;font-size:0.95rem;font-weight:700;letter-spacing:0.06em;">
                ANALISI DI MERCATO GLOBALE
            </div>
            <div style="margin-top:0.55rem;padding:0.55rem 0.65rem;border-radius:8px;
                border:1px solid {colore_status};background:rgba(0,0,0,0.35);">
                <div style="color:#7AD;font-size:0.72rem;letter-spacing:0.08em;
                    text-transform:uppercase;margin-bottom:0.2rem;">
                    Indice Spread di Dominanza · Distribuzione Sigma
                </div>
                <div style="color:{colore_status};font-weight:800;font-size:0.92rem;">
                    {html.escape(status_corsa)}
                </div>
                <div style="color:#E8FFF8;font-size:0.82rem;margin-top:0.25rem;">
                    Delta 1°−2° Score:
                    <strong style="color:{colore_status};"> {html.escape(delta_txt)}</strong>
                </div>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:1.5rem;margin-top:0.55rem;color:#E8FFF8;font-size:0.9rem;">
                <div><span style="color:#7AD;">Quota Media Gara:</span>
                    <strong style="color:#00FFAA;"> {html.escape(quota_txt)}</strong></div>
                <div><span style="color:#7AD;">Quote scartate (&lt; 1.60):</span>
                    <strong style="color:#FFD700;"> {html.escape(scartate_txt)}</strong></div>
                {lavagna_badge}
            </div>
        </div>
        """
    )


def _render_metriche_gara(intestazione: dict[str, str]) -> None:
    premio = str(intestazione.get("Premio", "")).strip()
    distanza = str(intestazione.get("Distanza", "")).strip()
    orario = str(intestazione.get("Orario", "")).strip()
    col1, col2, col3 = st.columns(3)
    col1.metric("Premio", premio if premio else "N/D")
    col2.metric("Distanza", f"{distanza} m" if distanza else "N/D")
    col3.metric("Orario", orario if orario else "N/D")


def _html_barre_densita_target(riga: pd.Series, titolo: str) -> str:
    nome = html.escape(titolo)
    densita = float(riga.get("Densità Sigma") or 0.0) * 100.0
    tilt = float(riga.get("Field Tilt") or 0.0) * 100.0
    return _html_pronto_streamlit(
        f"""
        <div style="margin-bottom:0.85rem;padding:0.55rem 0.65rem;
            background:rgba(8,12,18,0.75);border-radius:10px;
            border:1px solid rgba(0,255,204,0.25);">
            <div style="color:#00FFCC;font-size:0.85rem;font-weight:700;margin-bottom:0.35rem;">
                {nome}
            </div>
            {_html_barra_progresso("Densità Sigma", densita, "#00FFCC")}
            {_html_barra_progresso("Field Tilt", tilt, "#66E0FF")}
        </div>
        """
    )


def _calcola_stelle_assolute_unificate(riga: pd.Series) -> float:
    """Sistema di stelline assoluto: 5 stelle solo ai fuoriclasse (Rating altissimo)."""
    rating_raw = pd.to_numeric(riga.get("Rating"), errors="coerce")
    quanta_raw = pd.to_numeric(riga.get("Quanta"), errors="coerce")

    quanta = float(quanta_raw) if not pd.isna(quanta_raw) else 50.0

    if pd.isna(rating_raw):
        # Se manca il rating ufficiale, il cavallo viene valutato solo sulla forma
        # e non potrà mai raggiungere lo status di Campione (5 stelle) per sicurezza.
        indice_assoluto = quanta * 0.80
    else:
        rating = float(rating_raw)
        # Media ponderata assoluta: premia il Rating elevato (es. > 90) e la forma
        indice_assoluto = (rating * 0.65) + (quanta * 0.35)

    if indice_assoluto >= 92.0:
        return 5.0
    if indice_assoluto >= 82.0:
        return 4.5
    if indice_assoluto >= 70.0:
        return 4.0
    if indice_assoluto >= 58.0:
        return 3.5
    if indice_assoluto >= 45.0:
        return 3.0
    if indice_assoluto >= 30.0:
        return 2.5
    return 2.0


def _card_cavallo_html(
    riga: pd.Series,
    posizione_rank: int,
    target_principale: bool = False,
    include_barre_densita: bool = True,
    nascondi_etichetta_target: bool = False,
    mostra_gattino: bool = False,
) -> str:
    nome = html.escape(_testo_cella_riga_nd(riga, "Nome"))
    eta = html.escape(_testo_cella_riga_nd(riga, "Età"))
    numero_raw = riga.get("N°")
    if _valore_cella_presente(numero_raw):
        numero = html.escape(str(numero_raw).strip())
    else:
        numero = html.escape("N/D")
    rating = html.escape(_fmt_nd(riga.get("Rating")))
    ultimi = html.escape(_testo_cella_riga_nd(riga, "Ultimi Arrivi"))
    quote_cella = html.escape(_testo_cella_riga_nd(riga, "Quote Valide"))
    fair_raw = riga.get("Fair_Odds")
    fair_odds_txt = "N/D"
    if _valore_cella_presente(fair_raw):
        try:
            if not pd.isna(fair_raw):
                fair_odds_txt = html.escape(f"{float(fair_raw):.2f}")
        except (TypeError, ValueError):
            fair_odds_txt = "N/D"
    regression = html.escape(_fmt_nd(riga.get("Regression")))
    quanta = html.escape(_fmt_nd(riga.get("Quanta")))
    elastico = html.escape(_fmt_nd(riga.get("Elastico")))
    sigma = html.escape(_fmt_nd(riga.get("Sigma Value Score")))
    anomalia = html.escape(_testo_cella_riga_nd(riga, "Anomalia"))
    value_bet = _bool_cella_riga(riga, "Value_Bet")
    edge_raw = riga.get("Value_Edge")
    edge_txt = "N/D"
    if _valore_cella_presente(edge_raw):
        try:
            if not pd.isna(edge_raw):
                edge_txt = f"{float(edge_raw) * 100:+.1f}%"
        except (TypeError, ValueError):
            edge_txt = "N/D"
    value_bet_txt = "SÌ" if value_bet else "NO"

    conf_raw = riga.get("Indice_Confidenza_Sigma")
    conf_pct: float | None
    if conf_raw is None or (isinstance(conf_raw, float) and math.isnan(conf_raw)):
        conf_pct = None
        conf_label = "N/D"
    else:
        try:
            if pd.isna(conf_raw):
                conf_pct = None
                conf_label = "N/D"
            else:
                conf_pct = float(conf_raw)
                conf_label = f"{conf_pct:.1f}%"
        except (TypeError, ValueError):
            conf_pct = None
            conf_label = "N/D"

    spread_raw = riga.get("Spread_Elastico")
    if spread_raw is None or (isinstance(spread_raw, float) and math.isnan(spread_raw)):
        spread_val = None
        spread_label = "N/D"
    else:
        try:
            if pd.isna(spread_raw):
                spread_val = None
                spread_label = "N/D"
            else:
                spread_val = float(spread_raw)
                spread_label = f"{spread_val:+.1f}"
        except (TypeError, ValueError):
            spread_val = None
            spread_label = "N/D"

    spread_bar = (
        min(100.0, abs(spread_val)) if spread_val is not None else None
    )

    alert = _bool_cella_riga(riga, "Alert_Anomalia")
    badge = ""
    if alert:
        badge = _html_pronto_streamlit(
            """
            <div style="
                animation: sigma-lock-pulse 1.1s ease-in-out infinite;
                background: linear-gradient(90deg,#8B0000,#FFD700);
                color:#0E1117;font-weight:800;font-size:0.78rem;
                padding:0.25rem 0.55rem;border-radius:999px;
                display:inline-block;margin:0.35rem 0 0.15rem 0;">
                ⚠️ TARGET LOCK ELASTICO
            </div>
            """
        )

    barre = ""
    micro = (
        _html_micro_barra("Confidenza Sigma", conf_pct, "#00FFCC", conf_label)
        + _html_micro_barra(
            "Spread Elastico (Reg−Quanta)",
            spread_bar,
            "#FFAA00",
            spread_label,
        )
    )

    if target_principale and posizione_rank == 1:
        glow = "#FFD700"
        border = "#FFD700"
        extra_css = "font-size:1.25rem;font-weight:800;"
        padding = "1rem 1.05rem"
        colore_stelle = "#FFD700"
    elif target_principale and posizione_rank == 2:
        glow = "#C0C0C0"
        border = "#C0C0C0"
        extra_css = "font-size:1.15rem;font-weight:700;"
        padding = "0.95rem 1rem"
        colore_stelle = "#E8E8E8"
    elif target_principale and posizione_rank == 3:
        glow = "#00E5FF"
        border = "#0099FF"
        extra_css = "font-size:1.1rem;font-weight:700;"
        padding = "0.95rem 1rem"
        colore_stelle = "#00E5FF"
    elif target_principale and posizione_rank == 4:
        glow = "#FF00FF"
        border = "#E040FB"
        extra_css = "font-size:1.08rem;font-weight:800;"
        padding = "0.95rem 1rem"
        colore_stelle = "#FF66FF"
    else:
        glow = "transparent"
        border = "rgba(120,120,120,0.35)"
        extra_css = "font-size:0.95rem;font-weight:600;"
        padding = "0.65rem 0.75rem"
        colore_stelle = "#FFD700"

    gattino = " 🐈" if mostra_gattino else ""

    rating_5 = _calcola_stelle_assolute_unificate(riga)
    stelle_html = _html_stelle_sigma_rating(rating_5, colore_stelle=colore_stelle)
    nome_display = (
        f"{stelle_html}"
        f"<div style='{extra_css}margin:0;line-height:1.35;color:#FAFAFA;'>"
        f"{gattino} {nome}</div>"
    )

    val_consiglio = riga.get("Consiglio_Operativo")
    consiglio_testo = (
        str(val_consiglio).strip()
        if _valore_cella_presente(val_consiglio)
        else ""
    )
    if not consiglio_testo and target_principale:
        consiglio_testo = _testo_target_operativo(posizione_rank)
    etichetta_cima = ""
    if target_principale and not nascondi_etichetta_target:
        etichetta_cima = _html_etichetta_target_cima(consiglio_testo)
    consiglio_html = (
        "" if target_principale else _html_blocco_consiglio_operativo(consiglio_testo)
    )

    quota_sorpresa_html = ""
    if (
        target_principale
        and posizione_rank == 4
        and not nascondi_etichetta_target
    ):
        quota_alert = riga.get("Quota_Sorpresa_Elastica")
        if quota_alert is None or (
            isinstance(quota_alert, float) and math.isnan(quota_alert)
        ):
            quota_alert = _quota_massima_valida_riga(riga)
        if quota_alert is not None:
            try:
                if not pd.isna(quota_alert):
                    quota_sorpresa_html = (
                        f'<div style="margin-top:0.4rem;padding:0.4rem 0.5rem;'
                        f"border-radius:8px;border:1px solid #FF00FF;"
                        f'background:rgba(255,0,255,0.12);color:#FF99FF;'
                        f'font-size:0.82rem;font-weight:800;text-shadow:0 0 10px #FF00FF;">'
                        f"Quota allerta sorpresa: "
                        f"<span style=\"color:#FFFFFF;\">{float(quota_alert):.2f}</span>"
                        f"</div>"
                    )
            except (TypeError, ValueError):
                quota_sorpresa_html = ""

    barre = ""
    if include_barre_densita and target_principale:
        pass
    elif include_barre_densita and not target_principale:
        densita = _float_cella_riga(riga, "Densità Sigma", 0.0) * 100.0
        tilt = _float_cella_riga(riga, "Field Tilt", 0.0) * 100.0
        barre = (
            _html_barra_progresso("Densità Sigma", densita, "#00FFCC")
            + _html_barra_progresso("Field Tilt", tilt, "#66E0FF")
        )

    shadow = (
        f"box-shadow: 0 0 16px {glow}, 0 0 28px rgba(0,255,204,0.25);"
        if target_principale
        else "box-shadow: none;"
    )
    extra_glow = (
        f"box-shadow: 0 0 10px {glow};" if target_principale else ""
    )
    return _html_pronto_streamlit(
        f"""
        <div style="
            background: rgba(10,12,18,0.92);
            border: 1px solid {border};
            border-radius: 14px;
            padding: {padding};
            margin-bottom: 0.75rem;
            {shadow}{extra_glow}">
            {etichetta_cima}
            <div style="color:#00FFCC;font-size:0.72rem;letter-spacing:0.04em;">
                SIGMA RATING · DISTRIBUZIONE SIGMA
            </div>
            {badge}
            <div style="display:grid;grid-template-columns:1.05fr 0.95fr;gap:0.65rem;margin-top:0.35rem;">
                <div>
                    <div style="margin:0.15rem 0;">
                        {nome_display}
                    </div>
                    <div style="color:#B8FFF0;font-size:0.84rem;">N° {numero} · Età {eta}</div>
                    <div style="color:#00FFAA;font-size:0.95rem;margin-top:0.35rem;">
                        Sigma Value Score: <strong>{sigma}</strong>
                    </div>
                    <div style="color:#9AA;font-size:0.76rem;margin-top:0.2rem;">{anomalia}</div>
                    {quota_sorpresa_html}
                    {consiglio_html}
                </div>
                <div style="font-size:0.8rem;color:#DDE;">
                    <div>Rating: <span style="color:#0FC;">{rating}</span></div>
                    <div>Ultimi Arrivi: <span style="color:#0FC;">{ultimi}</span></div>
                    <div style="word-break:break-word;">Quote Valide: {quote_cella}</div>
                    <div style="margin-top:0.25rem; color:#FFD700; font-weight:700;">Fair Odds Sigma: {fair_odds_txt}</div>
                    <div>Value Bet: <strong style="color:{'#00FF66' if value_bet else '#FF7777'};">{value_bet_txt}</strong> · Edge {edge_txt}</div>
                    <div style="margin-top:0.25rem;">Regression {regression}</div>
                    <div>Quanta {quanta} · Elastico {elastico}</div>
                </div>
            </div>
            <div style="margin-top:0.45rem;">{micro}</div>
            {barre}
        </div>
        """
    )


def _etichetta_nome_cavallo_riga(riga: pd.Series) -> str:
    """Nome visualizzato (senza prefisso N° -)."""
    testo = str(riga.get("Nome") or "").strip()
    if " - " in testo:
        parte = testo.split(" - ", 1)[1].strip()
        return parte if parte else testo
    return testo if testo else "N/D"


def _numero_partente_testo_riga(riga: pd.Series) -> str | None:
    """N° partente reale dal parser; None se assente (nessun dato inventato)."""
    raw = riga.get("N°")
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    try:
        numero = int(float(raw))
        if 1 <= numero <= 30:
            return str(numero)
    except (TypeError, ValueError):
        pass
    testo = str(raw).strip()
    return testo if testo else None


def _html_titolo_numero_nome_analisi(riga: pd.Series) -> str:
    """N° X - Nome (HTML escaped) oppure solo nome se N° mancante."""
    nome = html.escape(_etichetta_nome_cavallo_riga(riga))
    numero = _numero_partente_testo_riga(riga)
    if numero is not None:
        return f"N° {html.escape(numero)} - {nome}"
    return nome


def _html_pill_numero_nome_combinazione(riga: pd.Series) -> str:
    nome = html.escape(_etichetta_nome_cavallo_riga(riga))
    numero = _numero_partente_testo_riga(riga)
    if numero is not None:
        contenuto = (
            f'<span style="color:#fff;font-weight:900;margin-right:5px;">'
            f"{html.escape(numero)}</span> {nome}"
        )
    else:
        contenuto = nome
    return (
        f'<span style="display:inline-block;padding:0.32rem 0.72rem;border-radius:999px;'
        f"background:linear-gradient(145deg,rgba(12,16,22,0.95),rgba(6,10,16,0.92));"
        f'border:1px solid rgba(0,229,255,0.42);color:#F4FAFF;font-weight:800;'
        f'font-size:0.82rem;letter-spacing:0.02em;'
        f'box-shadow:0 0 10px rgba(0,180,255,0.15);">{contenuto}</span>'
    )


def _numeri_top4_sigma(valutabili: pd.DataFrame) -> set[object]:
    if valutabili is None or valutabili.empty:
        return set()
    return set(valutabili.head(4)["N°"].tolist())


def _rileva_falso_favorito(valutabili: pd.DataFrame) -> dict[str, object] | None:
    """
    Quota reale più bassa (≥ 1.60): alert se non è al 1° posto Sigma Value Score.
    """
    if valutabili is None or valutabili.empty:
        return None

    ordine_sigma = valutabili.sort_values(
        by=["Sigma Value Score", "Elastico", "Regression"],
        ascending=[False, False, False],
    )
    capo_sigma = ordine_sigma.iloc[0]
    numero_capo = capo_sigma.get("N°")

    favorito_riga: pd.Series | None = None
    quota_min_assoluta: float | None = None
    for _idx, riga in valutabili.iterrows():
        qmin = _quota_minima_valida_riga(riga)
        if qmin is None:
            continue
        if quota_min_assoluta is None or qmin < quota_min_assoluta:
            quota_min_assoluta = qmin
            favorito_riga = riga
    if favorito_riga is None or quota_min_assoluta is None:
        return None

    if favorito_riga.get("N°") == numero_capo:
        return None

    return {
        "riga": favorito_riga,
        "nome": _etichetta_nome_cavallo_riga(favorito_riga),
        "quota": quota_min_assoluta,
        "motivo": (
            "Quota più bassa in gara ma Sigma Value Score non in testa — "
            "Distribuzione Sigma"
        ),
    }


def _html_riga_combinazione_tactical(
    titolo: str,
    colore_titolo: str,
    righe_cavallo: list[pd.Series],
) -> str:
    separatore = (
        '<span style="color:rgba(180,200,220,0.85);font-weight:900;font-size:0.95rem;'
        'margin:0 0.2rem;">➕</span>'
    )
    pillole = separatore.join(
        _html_pill_numero_nome_combinazione(riga) for riga in righe_cavallo
    )
    titolo_safe = html.escape(titolo)
    return (
        f'<div style="margin:0.7rem 0;padding:0.65rem 0.75rem;border-radius:12px;'
        f'background:rgba(0,0,0,0.32);border:1px solid rgba(255,255,255,0.06);">'
        f'<div style="color:{colore_titolo};font-weight:900;font-size:0.8rem;'
        f'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.5rem;'
        f'text-shadow:0 0 12px {colore_titolo};">{titolo_safe}</div>'
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.35rem;">'
        f"{pillole}</div></div>"
    )


def _html_modulo_falso_favorito(alert: dict[str, object] | None) -> str:
    if not alert:
        return _html_pronto_streamlit(
            """
            <div style="padding:0.85rem 1.05rem;border-radius:12px;
                border:1px solid rgba(120,120,120,0.35);
                background:rgba(12,14,20,0.88);color:#9AA;font-size:0.88rem;
                margin-bottom:0.85rem;">
                Nessun falso favorito rilevato
            </div>
            """
        )
    riga_alert = alert.get("riga")
    if isinstance(riga_alert, pd.Series):
        titolo_cavallo = _html_titolo_numero_nome_analisi(riga_alert)
    else:
        titolo_cavallo = html.escape(str(alert.get("nome") or "N/D"))
    quota = alert.get("quota")
    try:
        quota_txt = html.escape(f"{float(quota):.2f}") if quota is not None else "N/D"
    except (TypeError, ValueError):
        quota_txt = "N/D"
    motivo = html.escape(str(alert.get("motivo") or ""))
    return _html_pronto_streamlit(
        f"""
        <style>
        @keyframes sigma-red-code-neon {{
            0%, 100% {{
                box-shadow: 0 0 18px rgba(255,30,30,0.55), 0 0 36px rgba(255,0,0,0.25),
                    inset 0 0 24px rgba(255,0,0,0.08);
                border-color: #ff2244;
            }}
            50% {{
                box-shadow: 0 0 28px rgba(255,80,80,0.85), 0 0 48px rgba(255,40,40,0.45),
                    inset 0 0 32px rgba(255,0,0,0.12);
                border-color: #ff6677;
            }}
        }}
        @keyframes sigma-red-code-blink {{
            0%, 49% {{ opacity: 1; transform: scale(1); }}
            50%, 100% {{ opacity: 0.35; transform: scale(0.92); }}
        }}
        </style>
        <div style="padding:1.15rem 1.25rem;border-radius:14px;margin-bottom:0.85rem;
            border:2px solid #ff2244;
            background:linear-gradient(135deg,#050505 0%,#1a0303 45%,#2d0808 100%);
            animation:sigma-red-code-neon 1.6s ease-in-out infinite;">
            <div style="display:flex;align-items:center;gap:0.55rem;margin-bottom:0.55rem;">
                <span style="font-size:1.65rem;line-height:1;
                    animation:sigma-red-code-blink 0.9s step-end infinite;">🚨</span>
                <span style="color:#ff5566;font-weight:900;font-size:0.92rem;letter-spacing:0.08em;
                    text-transform:uppercase;text-shadow:0 0 14px rgba(255,50,50,0.75);">
                    ALERT FALSO FAVORITO · RED CODE · Lay Bet
                </span>
            </div>
            <div style="font-size:24px;font-weight:900;color:#ff4d4d;letter-spacing:1px;
                text-shadow:0 0 16px rgba(255,77,77,0.65);margin:0.25rem 0 0.45rem 0;">
                {titolo_cavallo}
            </div>
            <div style="color:#ffccaa;font-size:0.92rem;margin-top:0.2rem;">
                Quota favorito (valida): <strong style="color:#fff;font-size:1.05rem;">{quota_txt}</strong>
            </div>
            <div style="color:#ff9999;font-size:0.84rem;margin-top:0.45rem;font-weight:700;
                padding:0.45rem 0.55rem;border-radius:8px;background:rgba(255,0,0,0.08);
                border-left:3px solid #ff4444;">
                {motivo}
            </div>
        </div>
        """
    )


def _html_modulo_combinazioni(
    valutabili: pd.DataFrame,
    sel: dict[str, pd.DataFrame],
) -> str | None:
    if valutabili is None or valutabili.empty or len(valutabili) < 2:
        return None
    r1 = valutabili.iloc[0]
    r2 = valutabili.iloc[1]
    righe_html = [
        _html_riga_combinazione_tactical(
            "Accoppiata Base",
            "#00E5FF",
            [r1, r2],
        )
    ]
    if len(valutabili) >= 3:
        righe_html.append(
            _html_riga_combinazione_tactical(
                "Trio Sigma",
                "#FF66FF",
                [r1, r2, valutabili.iloc[2]],
            )
        )
    sorpresa = sel.get("sorpresa")
    if isinstance(sorpresa, pd.DataFrame) and not sorpresa.empty:
        righe_html.append(
            _html_riga_combinazione_tactical(
                "Trio Sbancamento",
                "#FFD700",
                [r1, r2, sorpresa.iloc[0]],
            )
        )
    return _html_pronto_streamlit(
        f"""
        <div style="padding:1.15rem 1.2rem;border-radius:16px;margin-bottom:0.85rem;
            border:1px solid rgba(0,255,204,0.28);
            background:linear-gradient(160deg,#0c0e12 0%,#141820 40%,#0a1218 100%);
            box-shadow:0 0 28px rgba(0,255,204,0.14), inset 0 1px 0 rgba(0,255,255,0.08);">
            <div style="color:#00FFCC;font-weight:900;font-size:1rem;margin-bottom:0.15rem;
                letter-spacing:0.06em;text-shadow:0 0 14px rgba(0,255,204,0.45);">
                🎯 GENERATORE COMBINAZIONI
            </div>
            <div style="color:rgba(160,200,210,0.75);font-size:0.68rem;letter-spacing:0.12em;
                text-transform:uppercase;margin-bottom:0.55rem;">
                Tactical Board · Distribuzione Sigma
            </div>
            <div style="font-size:0.86rem;line-height:1.5;">
                {''.join(righe_html)}
            </div>
            <div style="color:#556;font-size:0.68rem;margin-top:0.55rem;">
                Chiusura matematica sui 4 target · solo nomi reali · nessuna quota simulata
            </div>
        </div>
        """
    )


def _trova_coppia_testa_a_testa(
    valutabili: pd.DataFrame,
    numeri_esclusi: set[object],
) -> tuple[pd.Series, pd.Series, float, float] | None:
    if valutabili is None or valutabili.empty:
        return None
    pool = valutabili[~valutabili["N°"].isin(numeri_esclusi)]
    if len(pool) < 2:
        pool = valutabili
    if len(pool) < 2:
        return None

    righe = [riga for _idx, riga in pool.iterrows()]
    migliore: tuple[pd.Series, pd.Series, float, float] | None = None
    gap_min: float | None = None
    for i in range(len(righe)):
        for j in range(i + 1, len(righe)):
            a, b = righe[i], righe[j]
            qa = _quota_minima_valida_riga(a)
            qb = _quota_minima_valida_riga(b)
            if qa is None or qb is None:
                continue
            reg_a = a.get("Regression")
            reg_b = b.get("Regression")
            if reg_a is None or reg_b is None:
                continue
            try:
                if pd.isna(reg_a) or pd.isna(reg_b):
                    continue
                fa = float(reg_a)
                fb = float(reg_b)
            except (TypeError, ValueError):
                continue
            gap = abs(float(qa) - float(qb))
            if gap_min is None or gap < gap_min:
                gap_min = gap
                migliore = (a, b, fa, fb)
    return migliore


def _modulo_numerico_riga_classifica(riga: pd.Series, colonna: str) -> float | None:
    valore = riga.get(colonna)
    if valore is None:
        return None
    try:
        if pd.isna(valore):
            return None
        return float(valore)
    except (TypeError, ValueError):
        return None


def _telecronaca_testa_a_testa_sigma(
    a: pd.Series,
    b: pd.Series,
    a_vince: bool,
    b_vince: bool,
    pareggio_regression: bool,
) -> str:
    """Frase broadcast sul vantaggio matematico del vincitore analitico (solo dati reali)."""
    if pareggio_regression or (not a_vince and not b_vince):
        return "Analisi: Equilibrio statistico assoluto tra i due target."

    if a_vince:
        vincitore, perdente = a, b
        verbo = "difende la posizione"
    else:
        vincitore, perdente = b, a
        verbo = "prevale nel confronto diretto"

    moduli = (
        ("Modulo Regression", "Regression"),
        ("Modulo Quanta", "Quanta"),
        ("Modulo Elastico", "Elastico"),
    )
    miglior_gap = -1.0
    etichetta_modulo = ""
    val_v: float | None = None
    val_p: float | None = None

    for etichetta, colonna in moduli:
        vv = _modulo_numerico_riga_classifica(vincitore, colonna)
        vp = _modulo_numerico_riga_classifica(perdente, colonna)
        if vv is None or vp is None:
            continue
        if vv <= vp:
            continue
        gap = vv - vp
        if gap > miglior_gap:
            miglior_gap = gap
            etichetta_modulo = etichetta
            val_v, val_p = vv, vp

    if miglior_gap < 0 or val_v is None or val_p is None:
        return "Analisi: Equilibrio statistico assoluto tra i due target."

    numero = _numero_partente_testo_riga(vincitore)
    if numero is not None:
        soggetto = f"Il N° {numero}"
    else:
        soggetto = "Il target Sigma"

    if "Quanta" in etichetta_modulo:
        complemento = "più solido"
    elif "Elastico" in etichetta_modulo:
        complemento = "più incisivo"
    else:
        complemento = "superiore"

    return (
        f"Analisi: {soggetto} {verbo} grazie a un {etichetta_modulo} {complemento} "
        f"({val_v:.1f} vs {val_p:.1f}) · Distribuzione Sigma."
    )


def _html_modulo_testa_a_testa_top2_sigma(valutabili: pd.DataFrame) -> str | None:
    """1° vs 2° Sigma Value Score — ring VS (solo dati reali)."""
    if valutabili is None or len(valutabili) < 2:
        return None
    a = valutabili.iloc[0]
    b = valutabili.iloc[1]
    nome_a = _html_titolo_numero_nome_analisi(a)
    nome_b = _html_titolo_numero_nome_analisi(b)
    reg_a = a.get("Regression")
    reg_b = b.get("Regression")
    try:
        fa = float(reg_a) if reg_a is not None and not pd.isna(reg_a) else None
        fb = float(reg_b) if reg_b is not None and not pd.isna(reg_b) else None
    except (TypeError, ValueError):
        fa = fb = None
    pareggio = fa is not None and fb is not None and fa == fb
    a_vince = fa is not None and fb is not None and fa > fb
    b_vince = fa is not None and fb is not None and fb > fa
    if a_vince:
        vincitore = nome_a
    elif b_vince:
        vincitore = nome_b
    else:
        vincitore = f"{nome_a} = {nome_b}"
    reg_a_txt = html.escape(f"{fa:.1f}") if fa is not None else "n/d"
    reg_b_txt = html.escape(f"{fb:.1f}") if fb is not None else "n/d"
    esito = (
        f"Pareggio Modulo Regression · Distribuzione Sigma"
        if pareggio
        else f"Vincitore analitico: <strong style='color:#39FF14;'>{vincitore}</strong>"
    )
    testo_analisi = html.escape(
        _telecronaca_testa_a_testa_sigma(a, b, a_vince, b_vince, pareggio)
    )
    box_a = (
        "opacity:1;border:2px solid #39FF14;"
        "box-shadow:0 0 22px rgba(57,255,20,0.65), inset 0 0 16px rgba(57,255,20,0.12);"
    )
    box_b = (
        "opacity:0.58;border:1px solid rgba(100,100,110,0.45);"
        "box-shadow:none;"
    )
    return _html_pronto_streamlit(
        f"""
        <div style="padding:1.15rem 1.2rem;border-radius:16px;margin-bottom:0.85rem;
            border:1px solid rgba(255,140,0,0.35);
            background:linear-gradient(145deg,rgba(14,10,6,0.96),rgba(8,8,14,0.94));
            box-shadow:0 0 24px rgba(255,120,0,0.12);">
            <div style="color:#FFAA00;font-weight:900;font-size:1rem;margin-bottom:0.75rem;
                letter-spacing:0.05em;text-shadow:0 0 12px rgba(255,170,0,0.45);">
                ⚔️ TESTA A TESTA · Fight VS
            </div>
            <div style="display:flex;align-items:stretch;justify-content:center;gap:0.65rem;">
                <div style="flex:1;text-align:center;padding:0.65rem 0.5rem;border-radius:12px;
                    background:rgba(0,0,0,0.35);{box_a}">
                    <div style="font-size:1.02rem;font-weight:900;color:#FAFAFA;">{nome_a}</div>
                    <div style="color:#00FFCC;font-size:0.82rem;margin-top:0.3rem;">
                        Regression {reg_a_txt}
                    </div>
                </div>
                <div style="flex:0 0 auto;display:flex;align-items:center;justify-content:center;">
                    <div style="width:3.1rem;height:3.1rem;border-radius:50%;
                        display:flex;align-items:center;justify-content:center;
                        border:2px solid #00E5FF;background:rgba(0,0,0,0.55);
                        color:#00FFFF;font-weight:900;font-size:0.95rem;letter-spacing:0.06em;
                        box-shadow:0 0 20px rgba(0,229,255,0.55), inset 0 0 12px rgba(0,255,255,0.15);">
                        VS
                    </div>
                </div>
                <div style="flex:1;text-align:center;padding:0.65rem 0.5rem;border-radius:12px;
                    background:rgba(0,0,0,0.35);{box_b}">
                    <div style="font-size:0.88rem;font-weight:700;color:#CCC;">{nome_b}</div>
                    <div style="color:#00FFCC;font-size:0.82rem;margin-top:0.3rem;">
                        Regression {reg_b_txt}
                    </div>
                </div>
            </div>
            <div style="text-align:center;color:#CDE;font-size:0.86rem;margin-top:0.75rem;">
                {esito}
            </div>
            <div style="font-size:0.75rem; color:#A8B8B8; margin-top:0.35rem; text-align:center; font-style:italic;">{testo_analisi}</div>
            <div style="text-align:center;color:#666;font-size:0.68rem;margin-top:0.35rem;">
                Top 1 vs Top 2 Sigma Value Score · Distribuzione Sigma
            </div>
        </div>
        """
    )


def _html_modulo_testa_a_testa(
    coppia: tuple[pd.Series, pd.Series, float, float] | None,
) -> str | None:
    if coppia is None:
        return None
    a, b, reg_a, reg_b = coppia
    nome_a = _html_titolo_numero_nome_analisi(a)
    nome_b = _html_titolo_numero_nome_analisi(b)
    pareggio = reg_a == reg_b
    a_vince = not pareggio and reg_a > reg_b
    b_vince = not pareggio and reg_b > reg_a

    if a_vince:
        vincitore = nome_a
    elif b_vince:
        vincitore = nome_b
    else:
        vincitore = f"{nome_a} = {nome_b}"
    score_v = max(reg_a, reg_b) if not pareggio else reg_a

    stile_vinc = (
        "opacity:1;border:2px solid #39FF14;"
        "box-shadow:0 0 22px rgba(57,255,20,0.65), inset 0 0 16px rgba(57,255,20,0.12);"
        "transform:scale(1.03);"
    )
    stile_sconf = (
        "opacity:0.6;border:1px solid rgba(100,100,110,0.45);"
        "box-shadow:none;transform:scale(0.98);"
    )
    stile_neutro = (
        "opacity:1;border:1px solid rgba(255,170,0,0.45);"
        "box-shadow:0 0 12px rgba(255,170,0,0.2);"
    )
    box_a = stile_vinc if a_vince else (stile_sconf if b_vince else stile_neutro)
    box_b = stile_vinc if b_vince else (stile_sconf if a_vince else stile_neutro)
    nome_a_style = (
        "font-size:1.02rem;font-weight:900;color:#FAFAFA;"
        if a_vince
        else "font-size:0.88rem;font-weight:700;color:#CCC;"
    )
    nome_b_style = (
        "font-size:1.02rem;font-weight:900;color:#FAFAFA;"
        if b_vince
        else "font-size:0.88rem;font-weight:700;color:#CCC;"
    )
    trofeo_a = " 🏆" if a_vince else ""
    trofeo_b = " 🏆" if b_vince else ""

    esito = (
        f"Pareggio tecnico Modulo Regression ({html.escape(f'{score_v:.1f}')})"
        if pareggio
        else f"Vincitore analitico: <strong style='color:#39FF14;'>{vincitore}</strong>"
    )
    return _html_pronto_streamlit(
        f"""
        <div style="padding:1.15rem 1.2rem;border-radius:16px;margin-bottom:0.85rem;
            border:1px solid rgba(255,140,0,0.35);
            background:linear-gradient(145deg,rgba(14,10,6,0.96),rgba(8,8,14,0.94));
            box-shadow:0 0 24px rgba(255,120,0,0.12);">
            <div style="color:#FFAA00;font-weight:900;font-size:1rem;margin-bottom:0.75rem;
                letter-spacing:0.05em;text-shadow:0 0 12px rgba(255,170,0,0.45);">
                ⚔️ TESTA A TESTA · Fight VS
            </div>
            <div style="display:flex;align-items:stretch;justify-content:center;gap:0.65rem;">
                <div style="flex:1;text-align:center;padding:0.65rem 0.5rem;border-radius:12px;
                    background:rgba(0,0,0,0.35);{box_a}">
                    <div style="{nome_a_style}">{nome_a}{trofeo_a}</div>
                    <div style="color:#00FFCC;font-size:0.82rem;margin-top:0.3rem;">
                        Regression {html.escape(f'{reg_a:.1f}')}
                    </div>
                </div>
                <div style="flex:0 0 auto;display:flex;align-items:center;justify-content:center;">
                    <div style="width:3.1rem;height:3.1rem;border-radius:50%;
                        display:flex;align-items:center;justify-content:center;
                        border:2px solid #00E5FF;background:rgba(0,0,0,0.55);
                        color:#00FFFF;font-weight:900;font-size:0.95rem;letter-spacing:0.06em;
                        box-shadow:0 0 20px rgba(0,229,255,0.55), inset 0 0 12px rgba(0,255,255,0.15);">
                        VS
                    </div>
                </div>
                <div style="flex:1;text-align:center;padding:0.65rem 0.5rem;border-radius:12px;
                    background:rgba(0,0,0,0.35);{box_b}">
                    <div style="{nome_b_style}">{nome_b}{trofeo_b}</div>
                    <div style="color:#00FFCC;font-size:0.82rem;margin-top:0.3rem;">
                        Regression {html.escape(f'{reg_b:.1f}')}
                    </div>
                </div>
            </div>
            <div style="text-align:center;color:#CDE;font-size:0.86rem;margin-top:0.75rem;">
                {esito}
            </div>
            <div style="text-align:center;color:#666;font-size:0.68rem;margin-top:0.35rem;">
                Coppia con quote valide più vicine · Distribuzione Sigma
            </div>
        </div>
        """
    )


def _render_analisi_avanzate_sigma_40(
    valutabili: pd.DataFrame,
    sel: dict[str, pd.DataFrame],
) -> None:
    st.markdown("---")
    st.markdown("## 📺 ANALISI AVANZATE SIGMA 4.0")

    alert = _rileva_falso_favorito(valutabili)
    _st_html(_html_modulo_falso_favorito(alert))

    combo = _html_modulo_combinazioni(valutabili, sel)
    if combo:
        _st_html(combo)

    ttt = _html_modulo_testa_a_testa_top2_sigma(valutabili)
    if ttt:
        _st_html(ttt)


def _render_area_partenti_premium(classifica: pd.DataFrame) -> None:
    _st_html(
        """
        <style>
        @keyframes sigma-lock-pulse {
            0%, 100% { opacity: 1; filter: brightness(1); }
            50% { opacity: 0.72; filter: brightness(1.35); }
        }
        </style>
        """
    )
    st.markdown("## Distribuzione Sigma — Area Partenti Premium")
    classifica = _classifica_ordinata(classifica)
    if classifica.empty:
        st.warning("Assenza di dati - Inserire partenti")
        return

    valutabili = classifica[classifica["Sigma Value Score"].notna()].reset_index(
        drop=True
    )
    if valutabili.empty:
        blocchi_quote: list[str] = []
        for posizione, (_idx, riga) in enumerate(classifica.iterrows(), start=1):
            blocchi_quote.append(
                _card_cavallo_html(
                    riga,
                    posizione,
                    target_principale=False,
                    include_barre_densita=False,
                )
            )
        if blocchi_quote:
            _st_html("".join(blocchi_quote))
        return

    targets = valutabili.head(4)
    n_target = len(targets)
    if n_target == 0:
        st.warning("Assenza di dati - Inserire partenti")
        return
    if n_target >= 4:
        st.markdown(
            "### Motore Pronostico — 2 Vincenti · 1 Piazzato · "
            "1 Sorpresa elastica (Top 4 Sigma)"
        )
    elif n_target == 3:
        st.markdown("### Motore Pronostico — 2 Vincenti · 1 Piazzato (Top 3 Sigma)")
    elif n_target == 2:
        st.markdown("### Motore Pronostico — 2 Vincenti (Top 2 Sigma)")
    else:
        st.markdown("### Motore Pronostico — 1 Vincente (Top 1 Sigma)")

    vincenti_df, piazzato_df, sorpresa_df = _split_top4_target(valutabili)
    sel = _seleziona_quattro_target_sigma(valutabili)
    targets = sel["top4"]
    _render_griglia_pronostico_target(
        vincenti_df,
        piazzato_df,
        sorpresa_df,
        targets,
        mostra_barre_densita=True,
    )

    numeri_target = set(_numeri_target_operativi(sel).keys())
    resto = valutabili[~valutabili["N°"].isin(numeri_target)]
    if not resto.empty:
        st.markdown("### Altri partenti")
        blocchi: list[str] = []
        for posizione, (_idx, riga) in enumerate(resto.iterrows(), start=5):
            blocchi.append(
                _card_cavallo_html(
                    riga,
                    posizione,
                    target_principale=False,
                    include_barre_densita=False,
                )
            )
        _st_html("".join(blocchi))

    _render_analisi_avanzate_sigma_40(valutabili, sel)
    _render_pulsante_reset_archivio_corse()


def _render_dashboard_sigma_value_bet(
    df_calcolato: pd.DataFrame,
    intestazione: dict[str, str] | None = None,
) -> None:
    _ = intestazione
    _render_area_partenti_premium(df_calcolato)


def _render_aggiorna_esito_gara(gara: dict) -> None:
    with st.expander("Aggiorna Esito Gara (opzionale)", expanded=False):
        st.caption(
            "Disponibile solo per corse già salvate. "
            "Registra l'ordine di arrivo reale a fine gara."
        )
        with st.form("form_ordine_arrivo_fine_gara", clear_on_submit=False):
            ordine_arrivo = st.text_input(
                "Inserisci Ordine di Arrivo (es. 1-4-7):",
                key="ordine_arrivo_dati_gara",
            )
            salva = st.form_submit_button(
                "Salva esito corsa",
                type="primary",
                use_container_width=True,
            )
        if salva:
            try:
                _salva_ordine_arrivo_gara(str(ordine_arrivo or ""), gara)
            except (ValueError, sqlite3.Error) as exc:
                st.error(f"Salvataggio non eseguito: {exc}")
            else:
                st.session_state.ordine_arrivo = str(ordine_arrivo or "").strip()
                st.success(
                    "Esito reale salvato sull'archivio della corsa selezionata."
                )


def _render_ordine_arrivo_fine_gara(gara: dict) -> None:
    _render_aggiorna_esito_gara(gara)


def _render_inserimento_dati_gara() -> None:
    with st.expander("🗄️ INSERIMENTO DATI GARA", expanded=False):
        st.caption(
            "Parse + calcolo Sigma istantaneo. La corsa viene salvata "
            "automaticamente in memoria e SQLite."
        )
        st.markdown("### Inserimento Dati Gara")
        st.info("💡 Incolla qui il testo puro dei partenti. Nessuna formattazione complessa.")
        
        st.markdown("""
            <style>
            div[data-baseweb="textarea"] textarea, .stTextArea textarea {
                background-color: #f0f2f6 !important;
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
                font-weight: bold !important;
            }
            </style>
        """, unsafe_allow_html=True)
        
        testo_incollato = st.text_area("Incolla qui i partenti (anche senza quote):", height=250, key="input_testo")
        
        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn1:
            invia_btn = st.button("Elabora Dati Gara 🚀", type="primary", use_container_width=True)
        with col_btn2:
            reset = st.button(
                "🔄 Reset",
                use_container_width=True,
                key="reset_nuova_corsa_dashboard",
            )
        
        if reset:
            _reset_dashboard_nuova_corsa()
            st.rerun()
            
        if invia_btn:
            if not testo_incollato.strip():
                st.error("⚠️ Nessun testo rilevato. Incolla i dati.")
            else:
                st.info(f"✅ Letto un blocco di {len(testo_incollato.splitlines())} righe. Inizio analisi...")
                intestazione, tabella = parse_gara_completa(testo_incollato)
                if tabella.empty:
                    st.warning(
                        "Assenza di dati - Nessun cavallo riconosciuto "
                        "nel testo incollato"
                    )
                else:
                    for avviso in _avvisi_dati_statistici_partenti_mancanti(tabella):
                        st.warning(f"Assenza di dati - {avviso}")
                    mercato = _statistiche_mercato_da_testo(testo_incollato)
                    classifica = calcola_value_bet(tabella)
                    classifica = _ensure_colonne_distribuzione_sigma(classifica)
                    if (
                        "Sigma Value Score" in classifica.columns
                        and classifica["Sigma Value Score"].isna().all()
                    ):
                        st.warning(
                            "Assenza di dati - Regression, Quanta o Rating "
                            "insufficienti per calcolare la Distribuzione Sigma."
                        )
                    _archivia_gara_in_memoria(
                        intestazione, tabella, classifica, mercato=mercato
                    )
                    st.session_state.dashboard_live_vuota = False
                    st.session_state.messaggio_flash = (
                        "Gara salvata istantaneamente con Distribuzione Sigma "
                        f"calcolata ({len(tabella)} partenti)."
                    )
                    st.rerun()


def _render_storico_gare_testo() -> None:
    if st.button(
        "💾 Salva gara",
        type="primary",
        use_container_width=True,
        key="salva_gara_storico_testo",
    ):
        try:
            _salva_gara_corrente_storico_testo()
        except (ValueError, OSError) as exc:
            st.error(f"Salvataggio non eseguito: {exc}")
        else:
            st.success("Gara accodata correttamente in storico_gare.txt.")

    with st.expander("📄 Visualizza gare", expanded=True):
        if not os.path.exists(STORICO_GARE_PATH):
            st.info("Nessuna gara ancora salvata nello storico locale.")
            return
        try:
            with open(STORICO_GARE_PATH, "r", encoding="utf-8") as storico:
                contenuto = storico.read().strip()
        except OSError as exc:
            st.error(f"Impossibile leggere lo storico locale: {exc}")
            return
        if not contenuto:
            st.info("Lo storico locale è vuoto.")
            return

        gare_salvate: list[dict[str, object]] = []
        righe_non_valide = 0
        for riga_json in contenuto.splitlines():
            if not riga_json.strip():
                continue
            try:
                gara_salvata = json.loads(riga_json)
            except json.JSONDecodeError:
                righe_non_valide += 1
                continue
            if isinstance(gara_salvata, dict):
                gare_salvate.append(gara_salvata)

        if not gare_salvate:
            st.warning("Nessuna gara valida leggibile nello storico locale.")
            return
        if righe_non_valide:
            st.warning(
                f"{righe_non_valide} righe non valide sono state escluse "
                "dalla visualizzazione."
            )

        st.caption(f"{len(gare_salvate)} gare salvate · dalla più recente")
        for gara_salvata in reversed(gare_salvate):
            intestazione = gara_salvata.get("intestazione")
            if not isinstance(intestazione, dict):
                intestazione = {}
            titolo = str(intestazione.get("Ippodromo/Corsa") or "Gara salvata")
            salvato_il = str(gara_salvata.get("salvato_il") or "")

            with st.container(border=True):
                st.markdown(f"#### 🏇 {titolo}")
                if salvato_il:
                    st.caption(f"Salvata il {salvato_il}")
                col_premio, col_distanza, col_data = st.columns(3)
                col_premio.markdown(
                    f"**Premio:** {intestazione.get('Premio') or 'Non disponibile'}"
                )
                col_distanza.markdown(
                    f"**Distanza:** "
                    f"{intestazione.get('Distanza') or 'Non disponibile'}"
                )
                riferimento_data = " · ".join(
                    valore
                    for valore in (
                        str(intestazione.get("Data") or "").strip(),
                        str(intestazione.get("Orario") or "").strip(),
                    )
                    if valore
                )
                col_data.markdown(
                    f"**Data/ora:** {riferimento_data or 'Non disponibile'}"
                )

                classifica = gara_salvata.get("classifica_sigma")
                if not isinstance(classifica, list) or not classifica:
                    classifica = gara_salvata.get("partenti")
                if not isinstance(classifica, list) or not classifica:
                    st.info("Nessun cavallo salvato per questa gara.")
                    continue

                righe_cavalli: list[dict[str, object]] = []
                for cavallo in classifica:
                    if not isinstance(cavallo, dict):
                        continue
                    righe_cavalli.append(
                        {
                            "N°": cavallo.get("N°"),
                            "Cavallo": cavallo.get("Nome"),
                            "Quote": cavallo.get("Quote Valide"),
                            "Rating": cavallo.get("Rating"),
                            "Regression": cavallo.get("Regression"),
                            "Quanta": cavallo.get("Quanta"),
                            "Elastico": cavallo.get("Elastico"),
                            "Sigma": cavallo.get("Sigma Value Score"),
                            "Fair Odds": cavallo.get("Fair_Odds"),
                            "Value Bet": cavallo.get("Value_Bet"),
                            "Consiglio operativo": cavallo.get(
                                "Consiglio_Operativo"
                            ),
                        }
                    )
                if righe_cavalli:
                    st.dataframe(
                        pd.DataFrame(righe_cavalli),
                        hide_index=True,
                        use_container_width=True,
                    )
                else:
                    st.info("Nessun cavallo valido salvato per questa gara.")


def _nomi_cavalli_da_dataframe(df: pd.DataFrame) -> list[str]:
    if not isinstance(df, pd.DataFrame) or df.empty or "Nome" not in df.columns:
        return []
    nomi: list[str] = []
    for valore in df["Nome"]:
        testo = str(valore or "").strip()
        if testo:
            nomi.append(testo)
    return nomi


def _estratto_pronostico_gara(
    gara: dict,
) -> tuple[list[str], str, str]:
    pronostico = gara.get("pronostico_generato")
    if not isinstance(pronostico, dict):
        classifica = gara.get("classifica")
        if isinstance(classifica, pd.DataFrame) and not classifica.empty:
            pronostico = _costruisci_pronostico_generato(classifica)
        else:
            return [], "N/D", "N/D"
    vincenti_df = pronostico.get("vincenti")
    piazzato_df = pronostico.get("piazzato")
    sorpresa_df = pronostico.get("sorpresa")
    if not isinstance(piazzato_df, pd.DataFrame) or piazzato_df.empty:
        legacy = pronostico.get("piazzati")
        if isinstance(legacy, pd.DataFrame) and not legacy.empty:
            piazzato_df = legacy.iloc[0:1]
            if (not isinstance(sorpresa_df, pd.DataFrame) or sorpresa_df.empty) and len(
                legacy
            ) >= 2:
                sorpresa_df = legacy.iloc[1:2]
    if not isinstance(vincenti_df, pd.DataFrame):
        vincenti_df = pd.DataFrame()
    if not isinstance(piazzato_df, pd.DataFrame):
        piazzato_df = pd.DataFrame()
    if not isinstance(sorpresa_df, pd.DataFrame):
        sorpresa_df = pd.DataFrame()
    nomi_piazzato = _nomi_cavalli_da_dataframe(piazzato_df)
    nomi_sorpresa = _nomi_cavalli_da_dataframe(sorpresa_df)
    return (
        _nomi_cavalli_da_dataframe(vincenti_df),
        nomi_piazzato[0] if nomi_piazzato else "N/D",
        nomi_sorpresa[0] if nomi_sorpresa else "N/D",
    )


def _mappa_numero_nome_partenti_gara(gara: dict) -> dict[int, str]:
    """Solo partenti già parsati e archiviati nella gara (nessun dato inventato)."""
    partenti_df = gara.get("partenti")
    if not isinstance(partenti_df, pd.DataFrame) or partenti_df.empty:
        return {}
    mappa: dict[int, str] = {}
    for _, riga in partenti_df.iterrows():
        numero = pd.to_numeric(riga.get("N°"), errors="coerce")
        if pd.isna(numero):
            continue
        n = int(numero)
        nome = str(riga.get("Nome") or "").strip()
        mappa[n] = nome if nome else "N/D"
    return mappa


def _numeri_ordine_arrivo_salvato(ordine: str) -> list[int]:
    testo = str(ordine or "").strip()
    if not testo or re.fullmatch(r"\d+(?:-\d+)*", testo) is None:
        return []
    return [int(valore) for valore in testo.split("-")]


def _layout_podio_fotofinish(
    coppie_pos_numero: list[tuple[int, int]],
) -> list[tuple[int, int, str]]:
    """
    Ordine visivo podio: 2° — 1° — 3° (classico).
    coppie_pos_numero: [(posizione_arrivo, n° partente), ...] max 3.
    """
    if not coppie_pos_numero:
        return []
    altezze = {1: "100%", 2: "78%", 3: "66%"}
    if len(coppie_pos_numero) == 1:
        pos, num = coppie_pos_numero[0]
        return [(pos, num, altezze.get(pos, "72%"))]
    if len(coppie_pos_numero) == 2:
        primo, secondo = coppie_pos_numero[0], coppie_pos_numero[1]
        return [
            (secondo[0], secondo[1], altezze[2]),
            (primo[0], primo[1], altezze[1]),
        ]
    primo, secondo, terzo = coppie_pos_numero[:3]
    return [
        (secondo[0], secondo[1], altezze[2]),
        (primo[0], primo[1], altezze[1]),
        (terzo[0], terzo[1], altezze[3]),
    ]


def _stile_medaglia_fotofinish(posizione: int) -> tuple[str, str, str]:
    """Colore, glow, etichetta medaglia."""
    if posizione == 1:
        return ("#FFD700", "0 0 22px rgba(255,215,0,0.85)", "ORO")
    if posizione == 2:
        return ("#E8E8E8", "0 0 18px rgba(192,192,192,0.75)", "ARGENTO")
    return ("#CD7F32", "0 0 16px rgba(205,127,50,0.8)", "BRONZO")


def _html_esito_fotofinish_ufficiale(gara: dict, ordine_salvato: str) -> str | None:
    """
    Fotofinish premium solo se ordine reale salvato dall'utente.
    Nessun rendering se ordine vuoto o non valido.
    """
    ordine = str(ordine_salvato or "").strip()
    if not ordine:
        return None
    numeri = _numeri_ordine_arrivo_salvato(ordine)
    if not numeri:
        return None

    mappa = _mappa_numero_nome_partenti_gara(gara)
    coppie = [(idx + 1, num) for idx, num in enumerate(numeri[:3])]
    podio = _layout_podio_fotofinish(coppie)

    blocchi: list[str] = []
    for posizione, numero, altezza in podio:
        colore, glow, medaglia = _stile_medaglia_fotofinish(posizione)
        nome = mappa.get(numero, "N/D")
        nome_safe = html.escape(nome)
        numero_safe = html.escape(str(numero))
        blocchi.append(
            f"""
            <div style="flex:1;min-width:0;max-width:11rem;display:flex;flex-direction:column;
                align-items:center;justify-content:flex-end;">
                <div style="width:100%;min-height:{altezza};padding:0.55rem 0.45rem 0.5rem;
                    border-radius:12px 12px 6px 6px;
                    border:2px solid {colore};
                    background:linear-gradient(180deg,rgba(12,18,28,0.95) 0%,rgba(8,12,18,0.98) 100%);
                    box-shadow:{glow};text-align:center;">
                    <div style="font-size:0.62rem;font-weight:800;letter-spacing:0.08em;
                        color:{colore};opacity:0.95;">{medaglia}</div>
                    <div style="font-size:1.35rem;font-weight:900;color:{colore};
                        line-height:1.1;margin-top:0.15rem;">{posizione}°</div>
                    <div style="font-size:0.72rem;color:#9ECFC4;margin-top:0.2rem;">N° {numero_safe}</div>
                    <div style="font-size:0.78rem;font-weight:700;color:#F5FFFE;margin-top:0.35rem;
                        line-height:1.25;word-break:break-word;">{nome_safe}</div>
                </div>
            </div>
            """
        )

    resto = numeri[3:]
    extra_html = ""
    if resto:
        extra_numeri = html.escape("-".join(str(n) for n in resto))
        extra_html = (
            f'<div style="margin-top:0.45rem;font-size:0.72rem;color:#A8B8B8;">'
            f"Arrivi oltre il podio (solo numeri reali salvati): "
            f'<span style="color:#00FFCC;font-weight:700;">{extra_numeri}</span></div>'
        )

    ordine_safe = html.escape(ordine)
    return _html_pronto_streamlit(
        f"""
        <div style="margin-top:0.45rem;padding:0.75rem 0.85rem;border-radius:14px;
            border:1px solid rgba(0,255,204,0.35);
            background:linear-gradient(135deg,rgba(6,12,18,0.92),rgba(10,20,28,0.88));">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;
                flex-wrap:wrap;margin-bottom:0.55rem;">
                <div style="color:#00FFCC;font-weight:800;font-size:0.88rem;letter-spacing:0.04em;">
                    📸 ESITO FOTOFINISH UFFICIALE
                </div>
                <div style="font-size:0.72rem;color:#8FA8A0;">Ordine: <b style="color:#FFD700;">
                    {ordine_safe}</b></div>
            </div>
            <div style="display:flex;align-items:flex-end;justify-content:center;gap:0.5rem;
                padding:0.25rem 0 0.1rem;">{"".join(blocchi)}</div>
            {extra_html}
            <div style="margin-top:0.5rem;font-size:0.65rem;color:#6A7A78;text-align:center;">
                Dati da ordine di arrivo inserito manualmente · Distribuzione Sigma
            </div>
        </div>
        """
    )


def _ordine_arrivo_gara(gara: dict, ordini_map: dict[str, str]) -> str:
    ordine = str(gara.get("ordine_arrivo") or "").strip()
    if ordine:
        return ordine
    return str(ordini_map.get(str(gara.get("id")), "") or "").strip()


def _ordinamento_logbook_archivio(archivio: list[dict]) -> list[dict]:
    """Più recente → più vecchia (salvataggio, poi orario gara)."""

    def chiave(gara: dict) -> tuple[str, str, str]:
        intestazione = gara.get("intestazione") or {}
        return (
            str(gara.get("salvata_il") or ""),
            str(intestazione.get("Data") or ""),
            str(intestazione.get("Orario") or ""),
        )

    return sorted(archivio, key=chiave, reverse=True)


def _data_logbook_testo(intestazione: dict[str, str]) -> str:
    raw = str(intestazione.get("Data") or "").strip()
    if not raw:
        return "N/D"
    normalizzata = _normalizza_data_palinsesto(raw)
    if normalizzata is not None:
        return normalizzata.strftime("%d/%m/%Y")
    return raw


def _html_estratto_pronostico_logbook(gara: dict) -> str:
    intestazione = dict(gara.get("intestazione") or {})
    data_ev = html.escape(_data_logbook_testo(intestazione))
    orario = html.escape(str(intestazione.get("Orario") or "N/D").strip() or "N/D")
    ippodromo = html.escape(
        str(intestazione.get("Ippodromo/Corsa") or "N/D").strip() or "N/D"
    )
    premio = html.escape(str(intestazione.get("Premio") or "N/D").strip() or "N/D")
    vincenti, piazzato, sorpresa = _estratto_pronostico_gara(gara)
    vincenti_txt = (
        " | ".join(html.escape(nome) for nome in vincenti) if vincenti else "N/D"
    )
    piazzato_txt = html.escape(piazzato)
    sorpresa_txt = html.escape(sorpresa)
    return _html_pronto_streamlit(
        f"""
        <div style="color:#E8FFF8;font-size:0.84rem;font-weight:700;line-height:1.4;margin-bottom:0.2rem;">
            📅 {data_ev} | 🕒 {orario} | 🏇 {ippodromo} | 🏆 {premio}
        </div>
        <div style="font-size:0.76rem;line-height:1.35;">
            <span style="color:#FFD700;font-weight:700;">🔥 VINCENTI:</span>
            <span style="color:#FFE066;"> {vincenti_txt}</span>
        </div>
        <div style="font-size:0.76rem;margin-top:0.08rem;line-height:1.35;">
            <span style="color:#00E5FF;font-weight:700;">🎯 PIAZZATO:</span>
            <span style="color:#66E0FF;"> {piazzato_txt}</span>
        </div>
        <div style="font-size:0.76rem;margin-top:0.08rem;line-height:1.35;">
            <span style="color:#E040FB;font-weight:700;">⚡ SORPRESA:</span>
            <span style="color:#FF66FF;"> {sorpresa_txt}</span>
        </div>
        """
    )


def _render_esito_logbook_gara(gara: dict, ordini_map: dict[str, str]) -> None:
    gara_id = str(gara.get("id") or "")
    if not gara_id:
        return
    if "logbook_modifica_esito" not in st.session_state:
        st.session_state.logbook_modifica_esito = {}

    ordine_salvato = _ordine_arrivo_gara(gara, ordini_map)
    in_modifica = bool(st.session_state.logbook_modifica_esito.get(gara_id, False))
    ha_esito = bool(ordine_salvato)

    if ha_esito and not in_modifica:
        col_esito, col_mod = st.columns([4, 1])
        with col_esito:
            fotofinish_html = _html_esito_fotofinish_ufficiale(gara, ordine_salvato)
            if fotofinish_html:
                _st_html(fotofinish_html)
        with col_mod:
            if st.button(
                "Modifica",
                key=f"modifica_esito_{gara_id}",
                type="secondary",
                use_container_width=True,
            ):
                st.session_state.logbook_modifica_esito[gara_id] = True
                st.session_state[f"esito_{gara_id}"] = ordine_salvato
                st.rerun()
        return

    col_input, col_salva = st.columns([3, 1])
    with col_input:
        esito_input = st.text_input(
            "Ordine di arrivo",
            placeholder="es. 1-4-7",
            key=f"esito_{gara_id}",
            label_visibility="collapsed",
        )
    with col_salva:
        salva = st.button(
            "Salva Esito",
            key=f"salva_esito_{gara_id}",
            type="primary",
            use_container_width=True,
        )
    if salva:
        try:
            _salva_ordine_arrivo_gara(str(esito_input or ""), gara)
        except (ValueError, sqlite3.Error) as exc:
            st.error(str(exc))
        else:
            st.session_state.logbook_modifica_esito[gara_id] = False
            st.rerun()


def _elimina_gara_da_archivio(gara_id: str) -> None:
    gara_id = str(gara_id or "").strip()
    if not gara_id:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM ordini_arrivo_gare WHERE gara_id = ?",
            (gara_id,),
        )
        conn.execute(
            "DELETE FROM gare_sigma_archivio WHERE id = ?",
            (gara_id,),
        )
        conn.commit()
    archivio = [
        g
        for g in list(st.session_state.get("database_corse", []))
        if str(g.get("id")) != gara_id
    ]
    st.session_state.database_corse = archivio
    if st.session_state.get("gara_selezionata_id") == gara_id:
        st.session_state.dashboard_live_vuota = True
        if archivio:
            st.session_state.gara_selezionata_id = str(archivio[-1].get("id"))
        else:
            st.session_state.gara_selezionata_id = None
    st.session_state.messaggio_flash = "Corsa eliminata dall'archivio."


def _render_riga_logbook_gara(gara: dict, ordini_map: dict[str, str]) -> None:
    gara_id = str(gara.get("id") or "")
    with st.container(border=True):
        col_estratto, col_elimina = st.columns([5, 1])
        with col_estratto:
            _st_html(_html_estratto_pronostico_logbook(gara))
        with col_elimina:
            if st.button(
                "🗑️ Elimina",
                type="secondary",
                key=f"elimina_gara_logbook_{gara_id}",
            ):
                _elimina_gara_da_archivio(gara_id)
                st.rerun()
        _render_esito_logbook_gara(gara, ordini_map)


def _html_riga_registro_logbook(
    gara: dict,
    ordini_map: dict[str, str],
) -> str:
    """Legacy compat: estratto HTML senza widget esito."""
    return _html_estratto_pronostico_logbook(gara)


def _svuota_archivio_corse() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM ordini_arrivo_gare")
        conn.execute("DELETE FROM gare_sigma_archivio")
        conn.commit()
    st.session_state.database_corse = []
    # st.session_state.gara_selezionata_id = None


def _reset_archivio_corse_manuale() -> None:
    """Svuota archivio corse SQLite + session_state e prepara UI per nuova diretta."""
    _svuota_archivio_corse()
    st.session_state.dashboard_live_vuota = True
    st.session_state.dati_gara_dataframe = _dataframe_dati_gara_vuoto()
    st.session_state.sigma_value_bet = _dataframe_dati_gara_vuoto()
    st.session_state.intestazione_gara_corrente = _intestazione_gara_vuota()
    st.session_state.dati_gara_grezzi_version = (
        int(st.session_state.get("dati_gara_grezzi_version", 0)) + 1
    )
    st.session_state.logbook_modifica_esito = {}
    st.session_state.ordine_arrivo = ""
    st.session_state.mostra_analisi_corsa = False
    st.session_state.ultimo_report_singolo = ""
    st.session_state.ultimo_report_corsa = ""


def _render_pulsante_reset_archivio_corse() -> None:
    st.markdown("---")
    _st_html(
        """
        <style>
        div[data-testid="stElementContainer"].st-key-reset_archivio_corse_manuale button {
            background: linear-gradient(180deg, #7a0a0a 0%, #4a0000 100%) !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            letter-spacing: 0.04em !important;
            border: 2px solid #ff3333 !important;
            box-shadow: 0 0 16px rgba(255, 40, 40, 0.35) !important;
        }
        div[data-testid="stElementContainer"].st-key-reset_archivio_corse_manuale button:hover {
            border-color: #ff6666 !important;
            box-shadow: 0 0 22px rgba(255, 80, 80, 0.5) !important;
        }
        </style>
        """
    )
    col_sx, col_btn, col_dx = st.columns([1, 2, 1])
    with col_btn:
        if st.button(
            "🗑️ RESET ARCHIVIO CORSE",
            type="primary",
            use_container_width=True,
            key="reset_archivio_corse_manuale",
        ):
            _reset_archivio_corse_manuale()
            st.session_state.messaggio_flash = (
                "Archivio corse resettato manualmente. Interfaccia pronta per la diretta."
            )
            st.rerun()
    st.caption(
        "Azione distruttiva: elimina tutte le corse salvate in SQLite e in sessione. "
        "Nessun wipe automatico a mezzanotte."
    )


def _render_database_archivio_corse() -> None:
    with st.expander("🗄️ DATABASE ARCHIVIO CORSE", expanded=False):
        archivio = list(st.session_state.get("database_corse", []))
        col_titolo, col_svuota = st.columns([4, 1])
        with col_titolo:
            st.caption(
                "Registro Storico Compatto (Logbook Sigma) — "
                f"{len(archivio)} corse in sessione"
            )
        with col_svuota:
            if st.button(
                "Svuota Archivio",
                type="secondary",
                use_container_width=True,
                key="svuota_archivio_corse",
            ):
                _reset_archivio_corse_manuale()
                st.session_state.messaggio_flash = (
                    "Archivio corse resettato manualmente. Interfaccia pronta per la diretta."
                )
                st.rerun()

        if not archivio:
            st.warning("Assenza di dati - Nessuna corsa in archivio")
            return

        ordini_map = _carica_ordini_arrivo_gare()
        righe_ord = _ordinamento_logbook_archivio(archivio)
        with st.container(height=420):
            for gara in righe_ord:
                _render_riga_logbook_gara(gara, ordini_map)


def _render_gestione_palinsesto() -> None:
    with st.expander("🗄️ GESTIONE DATABASE PALINSESTO", expanded=False):
        st.caption(
            "Una riga rappresenta una prestazione storica. Ripeti i dati "
            "dell'evento e del cavallo per aggiungere più prestazioni."
        )
        modificata = st.data_editor(
            st.session_state.palinsesto_editor,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key=(
                f"palinsesto_editor_"
                f"{st.session_state.palinsesto_editor_version}"
            ),
            column_config={
                "Numero Partente": st.column_config.NumberColumn(
                    min_value=1,
                    step=1,
                    format="%d",
                ),
                "Posizione": st.column_config.NumberColumn(
                    min_value=1,
                    step=1,
                    format="%d",
                ),
                "Quota": st.column_config.NumberColumn(
                    min_value=1.60,
                    step=0.01,
                    format="%.2f",
                ),
            },
        )
        st.session_state.palinsesto_editor = modificata
        salva_blocco = st.button(
            "Salva palinsesto e aggiorna i moduli Sigma",
            type="primary",
            use_container_width=True,
            key="salva_palinsesto_blocco",
        )
        if salva_blocco:
            try:
                pulito, schede, esclusioni = _prepara_palinsesto(modificata)
                if not schede:
                    dettaglio = "; ".join(esclusioni)
                    st.warning(
                        "Assenza di dati - Nessuna riga valida"
                        + (f": {dettaglio}" if dettaglio else "")
                    )
                    return
                sessione = st.session_state.sessione_corsa_id
                _riscrivi_corsa_da_memoria(sessione, schede)
                _salva_righe_palinsesto(sessione, pulito)
            except (ValueError, sqlite3.Error) as exc:
                st.error(f"Salvataggio non eseguito: {exc}")
                return

            evento = pulito.iloc[0]
            st.session_state.cavalli_corrente = schede
            st.session_state.cavalli_corrente_sessione = sessione
            st.session_state.palinsesto_editor = pulito
            st.session_state.intestazione_corsa = pd.DataFrame(
                [
                    {
                        "Numero Corsa": evento["Numero Corsa"],
                        "Orario Partenza": evento["Orario"],
                        "Ippodromo": evento["Ippodromo Evento"],
                    }
                ]
            )
            st.session_state.intestazione_editor_version += 1
            st.session_state.palinsesto_editor_version += 1
            messaggio = (
                f"Palinsesto salvato: {len(schede)} cavalli e "
                f"{len(pulito)} prestazioni reali."
            )
            if esclusioni:
                messaggio += (
                    f" Righe escluse: {len(esclusioni)}. "
                    + " | ".join(esclusioni)
                )
            st.session_state.messaggio_flash = messaggio
            st.rerun()


def _init_risultati_storici() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risultati_storici (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessione_corsa TEXT NOT NULL,
                numero_corsa TEXT NOT NULL,
                orario_partenza TEXT NOT NULL,
                ippodromo TEXT,
                posizione INTEGER NOT NULL CHECK (posizione BETWEEN 1 AND 3),
                numero_partente INTEGER NOT NULL CHECK (numero_partente > 0),
                quota_reale_chiusura REAL NOT NULL
                    CHECK (quota_reale_chiusura > 0),
                salvato_il TEXT NOT NULL,
                UNIQUE (
                    sessione_corsa,
                    numero_corsa,
                    orario_partenza,
                    posizione
                )
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordini_arrivo_storici (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessione_corsa TEXT NOT NULL,
                numero_corsa TEXT NOT NULL,
                orario_partenza TEXT NOT NULL,
                ippodromo TEXT,
                ordine_arrivo TEXT NOT NULL,
                salvato_il TEXT NOT NULL,
                UNIQUE (
                    sessione_corsa,
                    numero_corsa,
                    orario_partenza
                )
            )
            """
        )
        legacy = conn.execute(
            """
            SELECT
                sessione_corsa, numero_corsa, orario_partenza,
                ippodromo, posizione, numero_partente, salvato_il
            FROM risultati_storici
            ORDER BY sessione_corsa, numero_corsa, orario_partenza, posizione
            """
        ).fetchall()
        raggruppati: dict[tuple[str, str, str, str, str], list[str]] = {}
        for (
            sessione,
            numero_corsa,
            orario,
            ippodromo,
            _posizione,
            partente,
            salvato_il,
        ) in legacy:
            chiave = (
                str(sessione),
                str(numero_corsa),
                str(orario),
                str(ippodromo or ""),
                str(salvato_il),
            )
            raggruppati.setdefault(chiave, []).append(str(partente))
        conn.executemany(
            """
            INSERT OR IGNORE INTO ordini_arrivo_storici (
                sessione_corsa, numero_corsa, orario_partenza,
                ippodromo, ordine_arrivo, salvato_il
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    sessione,
                    numero_corsa,
                    orario,
                    ippodromo,
                    "-".join(partenti),
                    salvato_il,
                )
                for (
                    sessione,
                    numero_corsa,
                    orario,
                    ippodromo,
                    salvato_il,
                ), partenti in raggruppati.items()
            ],
        )
        conn.commit()


def _salva_ordine_arrivo_gara(ordine_arrivo: str, gara: dict) -> None:
    """Salva solo l'esito a fine gara sulla corsa già archiviata."""
    ordine = ordine_arrivo.strip()
    if not ordine:
        raise ValueError("Assenza di dati - Ordine di arrivo non inserito.")
    if re.fullmatch(r"\d+(?:-\d+)*", ordine) is None:
        raise ValueError(
            "Usare esclusivamente numeri di partente separati da trattini."
        )
    partenti = [int(valore) for valore in ordine.split("-")]
    if any(partente <= 0 for partente in partenti):
        raise ValueError("I numeri dei partenti devono essere maggiori di zero.")
    if len(set(partenti)) != len(partenti):
        raise ValueError("Un partente non può comparire più volte.")

    partenti_df = gara.get("partenti")
    if not isinstance(partenti_df, pd.DataFrame) or partenti_df.empty:
        raise ValueError("Assenza di dati - Nessun partente archiviato.")
    partenti_validi = {
        int(valore)
        for valore in pd.to_numeric(partenti_df["N°"], errors="coerce").dropna()
    }
    if not set(partenti).issubset(partenti_validi):
        raise ValueError(
            "Uno o più partenti non appartengono alla corsa selezionata."
        )

    gara_id = str(gara["id"])
    timestamp = ora_italiana().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ordini_arrivo_gare (
                gara_id, ordine_arrivo, salvato_il
            ) VALUES (?, ?, ?)
            """,
            (
                gara_id,
                "-".join(str(partente) for partente in partenti),
                timestamp,
            ),
        )
        conn.commit()
    ordine_salvato = "-".join(str(partente) for partente in partenti)
    archivio = list(st.session_state.get("database_corse", []))
    for record in archivio:
        if str(record.get("id")) == gara_id:
            record["ordine_arrivo"] = ordine_salvato
            break
    st.session_state.database_corse = archivio


def _salva_risultati_storici(
    ordine_arrivo: str,
    intestazione: dict[str, str],
    sessione_corsa: str,
) -> None:
    gara = _gara_selezionata()
    if gara is None:
        raise ValueError("Assenza di dati - Nessuna gara archiviata.")
    _salva_ordine_arrivo_gara(ordine_arrivo, gara)

def _carica_risultati_storici() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            """
            SELECT
                numero_corsa AS "Numero Corsa",
                orario_partenza AS "Orario",
                ippodromo AS "Ippodromo",
                ordine_arrivo AS "Ordine di Arrivo",
                salvato_il AS "Salvato il"
            FROM ordini_arrivo_storici
            ORDER BY id DESC
            """,
            conn,
        )


def _init_session_state() -> None:
    if "sessione_corsa_id" not in st.session_state:
        st.session_state.sessione_corsa_id = str(uuid.uuid4())
    if "ultimo_report_singolo" not in st.session_state:
        st.session_state.ultimo_report_singolo = ""
    if "ultimo_report_corsa" not in st.session_state:
        st.session_state.ultimo_report_corsa = ""
    if "mostra_analisi_corsa" not in st.session_state:
        st.session_state.mostra_analisi_corsa = False
    if "messaggio_flash" not in st.session_state:
        st.session_state.messaggio_flash = ""
    if "intestazione_corsa" not in st.session_state:
        st.session_state.intestazione_corsa = pd.DataFrame(
            [
                {
                    "Numero Corsa": "",
                    "Orario Partenza": "",
                    "Ippodromo": "",
                }
            ]
        )
    if "intestazione_editor_version" not in st.session_state:
        st.session_state.intestazione_editor_version = 0
    if "ordine_arrivo" not in st.session_state:
        st.session_state.ordine_arrivo = ""
    if "dati_gara_dataframe" not in st.session_state:
        st.session_state.dati_gara_dataframe = _dataframe_dati_gara_vuoto()
    if "database_corse" not in st.session_state:
        # Caricamento disattivato per modalità usa e getta
        st.session_state.database_corse = []
    if "intestazione_gara_corrente" not in st.session_state:
        st.session_state.intestazione_gara_corrente = _intestazione_gara_vuota()
    if "gara_selezionata_id" not in st.session_state:
        archivio = st.session_state.database_corse
        st.session_state.gara_selezionata_id = (
            archivio[-1]["id"] if archivio else None
        )
    if (
        "cavalli_corrente" not in st.session_state
        or st.session_state.get("cavalli_corrente_sessione")
        != st.session_state.sessione_corsa_id
    ):
        st.session_state.cavalli_corrente = [
            scheda for _cid, scheda in _concorrenti_sessione()
        ]
        st.session_state.cavalli_corrente_sessione = (
            st.session_state.sessione_corsa_id
        )
    if (
        "palinsesto_editor" not in st.session_state
        or st.session_state.get("palinsesto_editor_sessione")
        != st.session_state.sessione_corsa_id
    ):
        st.session_state.palinsesto_editor = _carica_palinsesto_sessione(
            st.session_state.sessione_corsa_id
        )
        st.session_state.palinsesto_editor_sessione = (
            st.session_state.sessione_corsa_id
        )
    if "palinsesto_editor_version" not in st.session_state:
        st.session_state.palinsesto_editor_version = 0
    if "dati_gara_grezzi_version" not in st.session_state:
        st.session_state.dati_gara_grezzi_version = 0
    if "dashboard_live_vuota" not in st.session_state:
        st.session_state.dashboard_live_vuota = False


def _reset_dashboard_nuova_corsa() -> None:
    """Pulisce la dashboard live senza cancellare database_corse / archivio SQLite."""
    st.session_state.dashboard_live_vuota = True
    st.session_state.gara_selezionata_id = None
    st.session_state.dati_gara_dataframe = _dataframe_dati_gara_vuoto()
    st.session_state.intestazione_gara_corrente = _intestazione_gara_vuota()
    st.session_state.sigma_value_bet = _dataframe_dati_gara_vuoto()
    st.session_state.dati_gara_grezzi_version = (
        int(st.session_state.get("dati_gara_grezzi_version", 0)) + 1
    )
    st.session_state.messaggio_flash = (
        "Dashboard pronta per una nuova corsa. L'archivio storico è intatto."
    )


def _render_attesa_nuova_corsa() -> None:
    _st_html(
        """
        <div style="
            margin:1rem 0;padding:1.1rem 1rem;border-radius:12px;
            border:1px dashed rgba(0,255,204,0.45);
            background:rgba(10,14,20,0.55);text-align:center;">
            <div style="color:#00FFCC;font-size:1.05rem;font-weight:700;">
                In attesa di nuovi dati gara…
            </div>
            <div style="color:#A8B8B8;font-size:0.85rem;margin-top:0.35rem;">
                Incolla i dati grezzi e premi «Elabora Dati Gara», oppure seleziona
                una corsa dall'archivio per rivederla.
            </div>
        </div>
        """
    )


def _concorrenti_sessione() -> list:
    return carica_cavalli_sessione_da_db(st.session_state.sessione_corsa_id)


def _pulisci_form() -> None:
    st.session_state.scheda_input = ""
    st.session_state.ultimo_report_singolo = ""


def _nuova_corsa() -> None:
    st.session_state.sessione_corsa_id = str(uuid.uuid4())
    st.session_state.scheda_input = ""
    st.session_state.ultimo_report_singolo = ""
    st.session_state.ultimo_report_corsa = ""
    st.session_state.mostra_analisi_corsa = False
    st.session_state.cavalli_corrente = []
    st.session_state.cavalli_corrente_sessione = (
        st.session_state.sessione_corsa_id
    )
    st.session_state.intestazione_corsa = pd.DataFrame(
        [{"Numero Corsa": "", "Orario Partenza": "", "Ippodromo": ""}]
    )
    st.session_state.intestazione_editor_version += 1
    st.session_state.palinsesto_editor = _palinsesto_vuoto()
    st.session_state.palinsesto_editor_sessione = (
        st.session_state.sessione_corsa_id
    )
    st.session_state.palinsesto_editor_version += 1
    st.session_state.ordine_arrivo = ""
    st.session_state.ordine_arrivo_dati_gara = ""
    st.session_state.dati_gara_dataframe = _dataframe_dati_gara_vuoto()
    st.session_state.messaggio_flash = (
        "Nuova corsa avviata: il prossimo inserimento sarà Cavallo n. 1."
    )


def _cancella_corsa_corrente() -> None:
    if not st.session_state.get("conferma_cancellazione", False):
        st.session_state.messaggio_flash = (
            "Seleziona la conferma prima di cancellare la corsa."
        )
        return
    eliminati = _elimina_sessione_corsa(st.session_state.sessione_corsa_id)
    st.session_state.sessione_corsa_id = str(uuid.uuid4())
    st.session_state.scheda_input = ""
    st.session_state.ultimo_report_singolo = ""
    st.session_state.ultimo_report_corsa = ""
    st.session_state.mostra_analisi_corsa = False
    st.session_state.cavalli_corrente = []
    st.session_state.cavalli_corrente_sessione = (
        st.session_state.sessione_corsa_id
    )
    st.session_state.intestazione_corsa = pd.DataFrame(
        [{"Numero Corsa": "", "Orario Partenza": "", "Ippodromo": ""}]
    )
    st.session_state.intestazione_editor_version += 1
    st.session_state.palinsesto_editor = _palinsesto_vuoto()
    st.session_state.palinsesto_editor_sessione = (
        st.session_state.sessione_corsa_id
    )
    st.session_state.palinsesto_editor_version += 1
    st.session_state.ordine_arrivo = ""
    st.session_state.ordine_arrivo_dati_gara = ""
    st.session_state.dati_gara_dataframe = _dataframe_dati_gara_vuoto()
    st.session_state.conferma_cancellazione = False
    st.session_state.messaggio_flash = (
        f"Corsa cancellata dal database: eliminati {eliminati} cavalli."
    )


def _elimina_e_ricompatta(indice: int) -> None:
    corrente = list(st.session_state.cavalli_corrente)
    if indice < 0 or indice >= len(corrente):
        return
    eliminato = corrente.pop(indice)
    mappa_numeri: dict[int, int] = {}
    for nuovo_numero, scheda in enumerate(corrente, start=1):
        mappa_numeri[scheda.numero_partente] = nuovo_numero
        scheda.numero_partente = nuovo_numero

    palinsesto = st.session_state.palinsesto_editor.copy()
    if not palinsesto.empty:
        numeri = pd.to_numeric(
            palinsesto["Numero Partente"],
            errors="coerce",
        )
        palinsesto = palinsesto[numeri != eliminato.numero_partente].copy()
        palinsesto["Numero Partente"] = pd.to_numeric(
            palinsesto["Numero Partente"],
            errors="coerce",
        ).map(mappa_numeri)
    try:
        _riscrivi_corsa_da_memoria(
            st.session_state.sessione_corsa_id,
            corrente,
        )
        _salva_righe_palinsesto(
            st.session_state.sessione_corsa_id,
            palinsesto,
        )
    except sqlite3.Error as exc:
        st.session_state.cavalli_corrente = [
            scheda for _cid, scheda in _concorrenti_sessione()
        ]
        st.session_state.messaggio_flash = (
            f"Eliminazione annullata per errore SQLite: {exc}"
        )
    else:
        st.session_state.cavalli_corrente = corrente
        st.session_state.palinsesto_editor = palinsesto
        st.session_state.palinsesto_editor_version += 1
        st.session_state.ultimo_report_singolo = ""
        st.session_state.ultimo_report_corsa = ""
        st.session_state.mostra_analisi_corsa = False
        st.session_state.messaggio_flash = (
            f"{eliminato.nome} eliminato. Numerazione ricompattata; "
            f"prossimo partente N.{len(corrente) + 1}."
        )
    st.rerun()


def _genera_backup_json() -> str:
    """Serializza esclusivamente i dati reali della corsa corrente."""
    intestazione = st.session_state.intestazione_corsa.iloc[0].to_dict()
    payload = {
        "versione": 2,
        "intestazione_corsa": {
            chiave: "" if valore is None else str(valore)
            for chiave, valore in intestazione.items()
        },
        "cavalli": [
            asdict(scheda)
            for scheda in st.session_state.cavalli_corrente
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _testo_obbligatorio(record: dict, campo: str) -> str:
    if campo not in record:
        raise ValueError(f"Campo obbligatorio mancante: {campo}")
    valore = record[campo]
    if valore is None:
        raise ValueError(f"Valore nullo non ammesso: {campo}")
    return str(valore)


def _testo_opzionale(record: dict, campo: str) -> str:
    valore = record.get(campo)
    return "" if valore is None else str(valore)


def _carica_backup_json(
    contenuto: bytes,
) -> tuple[list[SchedaCavallo], pd.DataFrame]:
    if len(contenuto) > 5_000_000:
        raise ValueError("Il backup supera il limite di 5 MB.")
    try:
        payload = json.loads(contenuto.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Il file non contiene JSON valido.") from exc
    if isinstance(payload, list):
        # Compatibilità con i backup precedenti alla versione 2.
        cavalli_payload = payload
        intestazione_payload: dict = {}
    elif isinstance(payload, dict):
        cavalli_payload = payload.get("cavalli")
        intestazione_payload = payload.get("intestazione_corsa", {})
        if not isinstance(cavalli_payload, list):
            raise ValueError("Elenco cavalli mancante nel backup.")
        if not isinstance(intestazione_payload, dict):
            raise ValueError("Intestazione corsa non valida.")
    else:
        raise ValueError("Struttura del backup non valida.")

    cavalli: list[SchedaCavallo] = []
    for indice, record in enumerate(cavalli_payload, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Record cavallo {indice} non valido.")
        corse_raw = record.get("corse")
        if not isinstance(corse_raw, list) or not corse_raw:
            raise ValueError(
                f"Il cavallo {indice} non contiene corse valide."
            )

        corse: list[Corsa] = []
        for numero_corsa, corsa_raw in enumerate(corse_raw, start=1):
            if not isinstance(corsa_raw, dict):
                raise ValueError(
                    f"Corsa {numero_corsa} del cavallo {indice} non valida."
                )
            corse.append(
                Corsa(
                    posizione=_testo_obbligatorio(corsa_raw, "posizione"),
                    data_gara=_testo_obbligatorio(corsa_raw, "data_gara"),
                    ippodromo=_testo_obbligatorio(corsa_raw, "ippodromo"),
                    distanza_m=_testo_obbligatorio(corsa_raw, "distanza_m"),
                    unita_misura=_testo_obbligatorio(
                        corsa_raw, "unita_misura"
                    ),
                    parte=_testo_obbligatorio(corsa_raw, "parte"),
                    fantino=_testo_obbligatorio(corsa_raw, "fantino"),
                    quota=_testo_obbligatorio(corsa_raw, "quota"),
                    raw_riga=str(corsa_raw.get("raw_riga", "")),
                )
            )

        numero_partente = len(cavalli) + 1
        cavalli.append(
            SchedaCavallo(
                numero_partente=numero_partente,
                nome=etichetta_cavallo(numero_partente),
                note=_testo_opzionale(record, "note"),
                eta=_testo_opzionale(record, "eta"),
                sesso=_testo_opzionale(record, "sesso"),
                allenatore=_testo_opzionale(record, "allenatore"),
                flatsix=",".join(corsa.posizione for corsa in corse),
                genealogia=_testo_opzionale(record, "genealogia"),
                proprietario=_testo_opzionale(record, "proprietario"),
                corse=corse,
            )
        )
    intestazione = pd.DataFrame(
        [
            {
                "Numero Corsa": _testo_opzionale(
                    intestazione_payload, "Numero Corsa"
                ),
                "Orario Partenza": _testo_opzionale(
                    intestazione_payload, "Orario Partenza"
                ),
                "Ippodromo": _testo_opzionale(
                    intestazione_payload, "Ippodromo"
                ),
            }
        ]
    )
    return cavalli, intestazione


def _ripristina_backup(file_caricato) -> None:
    if file_caricato is None:
        st.session_state.messaggio_flash = (
            "Seleziona un file JSON prima del ripristino."
        )
        return
    try:
        cavalli, intestazione = _carica_backup_json(
            file_caricato.getvalue()
        )
        _riscrivi_corsa_da_memoria(
            st.session_state.sessione_corsa_id,
            cavalli,
        )
    except (ValueError, sqlite3.Error) as exc:
        st.session_state.messaggio_flash = f"Ripristino non eseguito: {exc}"
    else:
        st.session_state.cavalli_corrente = cavalli
        st.session_state.intestazione_corsa = intestazione
        st.session_state.intestazione_editor_version += 1
        st.session_state.ordine_arrivo = ""
        st.session_state.ultimo_report_singolo = ""
        st.session_state.ultimo_report_corsa = ""
        st.session_state.mostra_analisi_corsa = False
        st.session_state.messaggio_flash = (
            f"Ripristino completato: {len(cavalli)} cavalli caricati. "
            f"Prossimo partente N.{len(cavalli) + 1}."
        )
    st.rerun()


def _valori_intestazione_corsa() -> dict[str, str]:
    record = st.session_state.intestazione_corsa.iloc[0].to_dict()
    return {
        colonna: "" if valore is None else str(valore).strip()
        for colonna, valore in record.items()
    }


def _render_intestazione_corsa_editor() -> None:
    st.subheader("Intestazione corsa")
    modificata = st.data_editor(
        st.session_state.intestazione_corsa,
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
        key=(
            f"intestazione_corsa_editor_"
            f"{st.session_state.sessione_corsa_id}_"
            f"{st.session_state.intestazione_editor_version}"
        ),
        column_config={
            "Numero Corsa": st.column_config.TextColumn(
                "Numero Corsa",
                width="small",
            ),
            "Orario Partenza": st.column_config.TextColumn(
                "Orario Partenza",
                width="small",
            ),
            "Ippodromo": st.column_config.TextColumn(
                "Ippodromo (opzionale)",
                width="medium",
            ),
        },
    )
    st.session_state.intestazione_corsa = modificata[
        ["Numero Corsa", "Orario Partenza", "Ippodromo"]
    ].fillna("")


def _render_v1025_header(numero_partenti: int) -> None:
    _ = numero_partenti
    from datetime import datetime, timedelta
    ora_diretta = (datetime.utcnow() + timedelta(hours=2)).strftime("%d/%m/%Y | %H:%M")
    orario_attuale = html.escape(ora_diretta)

    _st_html(
        """
        <style>
        .sigma-studio-header-row {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.35rem;
        }
        .sigma-studio-header-main {
            flex: 1 1 16rem;
            min-width: 0;
        }
        .sigma-studio-top-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.55rem;
            margin-bottom: 0.65rem;
        }
        .sigma-badge-v1025 {
            display: inline-block;
            padding: 0.28rem 0.75rem;
            border-radius: 6px;
            font-family: "Segoe UI", system-ui, sans-serif;
            font-weight: 800;
            font-size: 0.72rem;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #1a1200;
            background: linear-gradient(135deg, #ffe566 0%, #ffb800 45%, #ffd700 100%);
            border: 1px solid rgba(255, 220, 120, 0.9);
            box-shadow: 0 0 14px rgba(255, 215, 0, 0.45),
                inset 0 1px 0 rgba(255, 255, 255, 0.55);
        }
        .sigma-badge-license {
            display: inline-block;
            padding: 0.32rem 0.85rem;
            border-radius: 999px;
            font-family: "Segoe UI", system-ui, sans-serif;
            font-weight: 700;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
            color: #7dffea;
            background: linear-gradient(
                145deg,
                rgba(8, 18, 22, 0.92),
                rgba(12, 28, 32, 0.88)
            );
            border: 1px solid rgba(0, 255, 204, 0.65);
            box-shadow: 0 0 16px rgba(0, 255, 204, 0.22),
                inset 0 0 20px rgba(0, 255, 204, 0.06);
            text-shadow: 0 0 10px rgba(0, 255, 204, 0.55);
        }
        .sigma-studio-title {
            margin: 0.15rem 0 0.35rem 0;
            font-family: "Segoe UI", system-ui, sans-serif;
            font-weight: 900;
            font-size: clamp(1.65rem, 3.2vw, 2.35rem);
            line-height: 1.15;
            letter-spacing: 0.02em;
            background: linear-gradient(
                92deg,
                #00ffaa 0%,
                #e0fff5 38%,
                #00e5ff 72%,
                #4da6ff 100%
            );
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            -webkit-text-fill-color: transparent;
            text-shadow: none;
            filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.65))
                drop-shadow(0 0 18px rgba(255, 215, 0, 0.25));
        }
        .sigma-studio-subtitle {
            margin: 0 0 0.25rem 0;
            font-family: "Segoe UI", system-ui, sans-serif;
            font-weight: 500;
            font-size: 0.98rem;
            line-height: 1.45;
            color: #b8c0cc;
            letter-spacing: 0.03em;
        }
        .sigma-broadcast-clock {
            flex: 0 0 auto;
            align-self: flex-start;
            text-align: right;
            padding: 0.55rem 0.85rem;
            border-radius: 10px;
            border: 1px solid rgba(0, 229, 255, 0.45);
            background: rgba(8, 14, 22, 0.72);
            box-shadow: 0 0 18px rgba(0, 229, 255, 0.22),
                inset 0 0 12px rgba(0, 229, 255, 0.06);
            margin-right: 50px;
        }
        .sigma-broadcast-clock-label {
            display: block;
            font-family: "Segoe UI", system-ui, sans-serif;
            font-size: 0.62rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: rgba(180, 220, 230, 0.75);
            margin-bottom: 0.25rem;
        }
        .sigma-broadcast-clock-time {
            font-family: "Roboto Mono", "Courier New", Consolas, monospace;
            font-size: clamp(1rem, 2vw, 1.35rem);
            font-weight: 700;
            letter-spacing: 0.06em;
            color: #eaffff;
            text-shadow: 0 0 12px rgba(0, 229, 255, 0.65),
                0 0 24px rgba(0, 180, 255, 0.35);
        }
        </style>
        """
    )

    col_header, col_orologio = st.columns([4, 1])
    with col_header:
        _st_html(
            """
            <div class="sigma-studio-top-row">
                <span class="sigma-badge-v1025">V10.25 FULL-PRO-TV</span>
                <span class="sigma-badge-license">Sigma 4.0 - Professional License</span>
            </div>
            <h1 class="sigma-studio-title">🐱 IPPICA STAR!</h1>
            <a href="https://www.snai.it/ippica" class="btn-star" target="_blank" style="background-color: #00ffaa; color: #000; padding: 8px 15px; border-radius: 5px; text-decoration: none; font-weight: bold; margin-top: 10px; display: inline-block;">Scommesse Ippica | Scommetti sui cavalli</a>
            <p class="sigma-studio-subtitle">
                Console Premium: Regression · Quanta · Elastico su dati reali del parser
            </p>
            """
        )
    with col_orologio:
        _st_html(
            f"""
            <div class="sigma-broadcast-clock">
                <span class="sigma-broadcast-clock-label">Ora diretta</span>
                <span class="sigma-broadcast-clock-time">{orario_attuale}</span>
            </div>
            """
        )


def _render_archivio_risultati_finali_contenuto() -> None:
    st.caption(
        "Archivio manuale degli esiti reali. Questi dati non modificano "
        "automaticamente il rating della corsa corrente."
    )
    intestazione = _valori_intestazione_corsa()
    with st.container(border=True):
        with st.form(
            "form_risultati_storici",
            clear_on_submit=False,
        ):
            ordine_arrivo = st.text_input(
                "Ordine di Arrivo (es. 1-4-7-2):",
                value=st.session_state.ordine_arrivo,
                key=(
                    f"ordine_arrivo_"
                    f"{st.session_state.sessione_corsa_id}"
                ),
            )
            salva_storico = st.form_submit_button(
                "Salva Risultati a Storico",
                type="primary",
                use_container_width=True,
            )

        st.session_state.ordine_arrivo = ordine_arrivo
        if ordine_arrivo.strip():
            st.markdown(
                f"**Ordine di Arrivo:** `{html.escape(ordine_arrivo.strip())}`"
            )
        else:
            st.write("Ordine di Arrivo: Assenza di dati")
        if salva_storico:
            try:
                _salva_risultati_storici(
                    ordine_arrivo,
                    intestazione,
                    st.session_state.sessione_corsa_id,
                )
            except (ValueError, sqlite3.Error) as exc:
                st.error(f"Salvataggio non eseguito: {exc}")
            else:
                st.success(
                    "Risultato reale salvato nello storico SQLite."
                )

    storico = _carica_risultati_storici()
    if not storico.empty:
        with st.container(border=True):
            st.markdown("#### Consulta archivio risultati")
            for _indice, record in storico.iterrows():
                riferimento = " · ".join(
                    parte
                    for parte in (
                        f"Corsa {record['Numero Corsa']}",
                        str(record["Orario"]),
                        str(record["Ippodromo"]),
                    )
                    if parte and parte != "nan"
                )
                st.write(
                    f"{riferimento} — Ordine di Arrivo: "
                    f"{record['Ordine di Arrivo']}"
                )
    else:
        st.write("Ordine di Arrivo: Assenza di dati")


def _render_archivio_risultati_finali() -> None:
    st.divider()
    with st.expander("🏁 Database Risultati Finali", expanded=False):
        _render_archivio_risultati_finali_contenuto()


def _controlla_scadenza_palinsesto() -> None:
    """Disattivato: nessun wipe automatico del palinsesto o dell'archivio."""
    pass


def main() -> None:
    init_database()
    _init_risultati_storici()
    _init_archivio_gare_sigma()
    _init_palinsesto_database()
    _init_session_state()

    gara_corrente = _gara_selezionata()
    if gara_corrente is not None and not st.session_state.get("dashboard_live_vuota"):
        tabella = gara_corrente["partenti"]
        st.session_state.dati_gara_dataframe = tabella
    else:
        tabella = st.session_state.get("dati_gara_dataframe")
        if not isinstance(tabella, pd.DataFrame):
            tabella = _dataframe_dati_gara_vuoto()
            st.session_state.dati_gara_dataframe = tabella

    partenti_header = (
        0
        if st.session_state.get("dashboard_live_vuota")
        else len(tabella) if isinstance(tabella, pd.DataFrame) else 0
    )
    _render_v1025_header(partenti_header)

    if st.session_state.messaggio_flash:
        st.info(st.session_state.messaggio_flash)
        st.session_state.messaggio_flash = ""

    st.divider()
    _render_inserimento_dati_gara()
    _render_storico_gare_testo()
    # _render_database_archivio_corse disattivato per modalità usa e getta
    st.divider()

    gara = _render_selettore_gara_salvata()
    if gara is None:
        if st.session_state.get("dashboard_live_vuota"):
            _render_attesa_nuova_corsa()
        return

    intestazione = dict(gara.get("intestazione") or {})
    _render_metriche_gara(intestazione)
    _render_analisi_mercato_globale(gara)
    st.divider()

    tabella = gara["partenti"]
    if not isinstance(tabella, pd.DataFrame) or tabella.empty:
        st.warning("Assenza di dati - Inserire partenti")
        return

    classifica = gara.get("classifica")
    if not isinstance(classifica, pd.DataFrame) or classifica.empty:
        classifica = calcola_value_bet(tabella)
        gara["classifica"] = classifica.copy()
    elif (
        "Indice_Confidenza_Sigma" not in classifica.columns
        or "Consiglio_Operativo" not in classifica.columns
    ):
        classifica = calcola_value_bet(tabella)
        gara["classifica"] = classifica.copy()
    classifica = _ensure_colonne_distribuzione_sigma(classifica)
    st.session_state.sigma_value_bet = classifica
    _render_dashboard_sigma_value_bet(classifica, intestazione)
    st.divider()
    _render_aggiorna_esito_gara(gara)



if __name__ == "__main__":
    main()