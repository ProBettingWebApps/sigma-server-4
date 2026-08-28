"""
Scheda ippica completa: parsing, SQLite, analisi pronostico, GUI Tkinter.
I partenti sono numerati in ordine di inserimento (Cavallo n. 1, n. 2, …).
"""

from __future__ import annotations

import re
import sqlite3
import pytz
from dataclasses import dataclass, field
from datetime import datetime

# Gestione sicura di Tkinter per l'ambiente web (Streamlit Cloud)
try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
    TK_AVAILABLE = True
except (ImportError, RuntimeError):
    TK_AVAILABLE = False
    class MockTk:
        pass
    class tk:
        Tk = MockTk
DB_PATH = "ippica_dati.db"

ETA_RE = re.compile(r"(?i)Età:\s*(\d+)")
SESSO_RE = re.compile(r"(?i)Sesso:\s*(.+)")
FLATSIX_RE = re.compile(r"(?i)FlatSix:\s*(\d+)")
TOTALSIX_RE = re.compile(r"(?i)TotalSix:\s*(\d+)")
PROPRIETARIO_RE = re.compile(r"(?i)Proprietario/a:\s*(.+)")
NONNO_RE = re.compile(r"(?i)Nonno Materno:\s*(.+)")
PADRE_RE = re.compile(r"(?i)Padre:\s*(.+)")

DATE_PATTERN = (
    r"(?:0?[1-9]|[12]\d|3[01])/"
    r"(?:0?[1-9]|1[0-2])/"
    r"(?:\d{4}|\d{2})"
)
DATE_AT_START_RE = re.compile(rf"({DATE_PATTERN})")
QUOTA_CANDIDATE_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")
RACE_LINE_RE = re.compile(
    rf"^(?P<posizione>\d+)\s+"
    rf"(?P<data>{DATE_PATTERN})\s+"
    rf"(?P<testo_intermedio>.+?)\s+"
    rf"(?P<quota>\d+(?:[.,]\d+)?)\s*$"
)
COMPACT_RACE_RE = re.compile(
    rf"(?P<posizione>\d|\d{{2}})"
    rf"(?P<data>{DATE_PATTERN})"
    r"(?P<ippodromo>[^\W\d_]+(?:[\s'’.\-]+[^\W\d_]+)*?)\s*"
    r"(?P<distanza>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unita>yards|meters)\s*"
    r"(?P<parte>\d{1,2})\s*"
    r"(?P<fantino>[^\d]{3,40}?)\s*"
    r"(?P<quota>\d+[.,]\d{2})",
    re.IGNORECASE,
)
RACE_DETAILS_RE = re.compile(
    r"^(.+?)\s+"                 # ippodromo: testo libero
    r"(\d+(?:[.,]\d+)?)\s*"     # distanza
    r"([^\d\s]+)\s*"             # unità libera: m, yards, km, miles...
    r"(\d{1,2})\s*"              # partenza/gabbia
    r"(.+?)\s*$",                 # fantino
)

ULTIME_CORSE_HEADER_RE = re.compile(
    r"^PosData\s*Corsa.*",
    re.IGNORECASE,
)
CODICE_GABBIA_STANDALONE_RE = re.compile(r"^G\d{1,2}$", re.IGNORECASE)
FANTINO_PESO_KG_SUFFIX_RE = re.compile(
    r"(?i)\s+\d+(?:[.,]\d+)?\s*kg\s*$"
)


def _normalizza_fantino_estratto(fantino: str) -> str:
    """Accetta peso in Kg sulla stessa riga; conserva solo il nome del fantino."""
    pulito = " ".join(str(fantino or "").split())
    return FANTINO_PESO_KG_SUFFIX_RE.sub("", pulito).strip()


def _riga_codice_gabbia(riga: str) -> bool:
    return bool(CODICE_GABBIA_STANDALONE_RE.fullmatch(riga.strip()))


# --- Parser partenti gara (Trotto + Galoppo, lettura a blocchi) ---

SOGLIA_QUOTA_VINCENTE_SIGMA = 1.60

NUMERO_PARTENTE_ISOLATO_RE = re.compile(r"^\s*(?P<numero>\d{1,2})\s*$")
GABBIA_GALOPPO_RE = re.compile(r"^G\d+$", re.IGNORECASE)
ETA_YO_PARTENTE_RE = re.compile(r"(?i)\b(?P<eta>\d{1,2}YO)\b")
RATING_PARTENTE_RE = re.compile(r"(?i)Rating\s*:\s*(?P<rating>\d+(?:[.,]\d+)?)")
ULTIMI_ARRIVI_PARTENTE_RE = re.compile(
    r"(?i)Ultimi\s+arrivi\s*:?\s*(?P<ultimi>\d+)"
)
DECIMAL_QUOTE_RE = re.compile(r"^\s*(?P<q>\d+[.,]\d{1,2})\s*$")
RIGA_ORARI_PALINSESTO_RE = re.compile(r"^\s*\d{1,2}\s+\d{1,2}:\d{2}\s*$")


@dataclass
class PartenteGaraGrezzo:
    numero: int
    nome: str
    fantino: str
    quota_vincente: float
    quota_piazzato: float | None
    eta: str
    rating: float | None
    ultimi_arrivi: str
    blocco: str


def _valida_inizio_blocco_partente(linee: list[str], indice: int) -> bool:
    """Conferma che la riga con solo il N° apre un blocco cavallo reale."""
    if indice + 1 >= len(linee):
        return False
    pos = indice + 1
    if pos < len(linee) and GABBIA_GALOPPO_RE.fullmatch(linee[pos].strip()):
        pos += 1
    if pos >= len(linee):
        return False
    candidato = linee[pos].strip()
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", candidato):
        return False
    if re.match(r"(?i)^rating\b", candidato):
        return False
    limite = min(indice + 24, len(linee))
    for j in range(indice, limite):
        if ETA_YO_PARTENTE_RE.search(linee[j]):
            return True
    return False


def _split_blocchi_partenti_grezzo(testo: str) -> list[tuple[int, list[str]]]:
    """Divide il testo in blocchi da un numero partente al successivo."""
    linee = [ln.rstrip() for ln in testo.splitlines()]
    inizi: list[tuple[int, int]] = []
    for indice, riga in enumerate(linee):
        if RIGA_ORARI_PALINSESTO_RE.match(riga):
            continue
        match = NUMERO_PARTENTE_ISOLATO_RE.fullmatch(riga)
        if match is None:
            continue
        numero = int(match.group("numero"))
        if not (1 <= numero <= 30):
            continue
        if not _valida_inizio_blocco_partente(linee, indice):
            continue
        inizi.append((indice, numero))

    blocchi: list[tuple[int, list[str]]] = []
    for pos, (inizio, numero) in enumerate(inizi):
        fine = inizi[pos + 1][0] if pos + 1 < len(inizi) else len(linee)
        blocchi.append((numero, linee[inizio:fine]))
    return blocchi


def _estrai_nome_inizio_blocco(linee: list[str]) -> str | None:
    if not linee or NUMERO_PARTENTE_ISOLATO_RE.fullmatch(linee[0]) is None:
        return None
    indice = 1
    if indice < len(linee) and GABBIA_GALOPPO_RE.fullmatch(linee[indice].strip()):
        indice += 1
    if indice >= len(linee):
        return None
    nome = linee[indice].strip()
    if not nome or not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", nome):
        return None
    return nome


def _indice_riga_eta_yo(linee: list[str]) -> int | None:
    for indice, riga in enumerate(linee):
        if ETA_YO_PARTENTE_RE.search(riga):
            return indice
    return None


def _estrai_fantino_dopo_eta(linee: list[str], indice_eta: int) -> str | None:
    for j in range(indice_eta + 1, len(linee)):
        testo = linee[j].strip()
        if not testo:
            continue
        if ULTIMI_ARRIVI_PARTENTE_RE.search(testo):
            break
        if re.search(r"(?i)\bmetri\b", testo):
            continue
        if re.match(r"(?i)^rating\b", testo):
            continue
        if DECIMAL_QUOTE_RE.fullmatch(testo):
            break
        if NUMERO_PARTENTE_ISOLATO_RE.fullmatch(testo):
            break
        fantino = _normalizza_fantino_estratto(testo)
        if fantino and re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ.]", fantino):
            return fantino
    return None


def _estrai_ultimi_arrivi_da_blocco(linee: list[str]) -> str:
    for riga in linee:
        match = ULTIMI_ARRIVI_PARTENTE_RE.search(riga)
        if match is not None:
            return str(match.group("ultimi") or "").strip()
    return ""


def _estrai_rating_da_blocco(linee: list[str]) -> float | None:
    for riga in linee:
        match = RATING_PARTENTE_RE.search(riga)
        if match is None:
            continue
        try:
            return float(match.group("rating").replace(",", "."))
        except ValueError:
            return None
    return None


def _estrai_eta_da_blocco(linee: list[str]) -> str:
    for riga in linee:
        match = ETA_YO_PARTENTE_RE.search(riga)
        if match is not None:
            return str(match.group("eta") or "").upper()
    return ""


def _estrai_decimali_coda_blocco(linee: list[str]) -> list[float]:
    """Quote in colonna in coda al blocco (ignora 3ª e 4ª colonna in uso)."""
    raccolti: list[float] = []
    for riga in reversed(linee):
        testo = riga.strip()
        if not testo:
            if raccolti:
                break
            continue
        if ULTIMI_ARRIVI_PARTENTE_RE.search(testo):
            break
        if NUMERO_PARTENTE_ISOLATO_RE.fullmatch(testo):
            break
        if re.search(r"(?i)\bkg\b", testo):
            break
        if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", testo):
            if raccolti:
                break
            continue
        riga_quote: list[float] = []
        if DECIMAL_QUOTE_RE.fullmatch(testo):
            valore = DECIMAL_QUOTE_RE.fullmatch(testo)
            assert valore is not None
            riga_quote.append(float(valore.group("q").replace(",", ".")))
        else:
            for pezzo in re.findall(r"\b\d+[.,]\d{1,2}\b", testo):
                riga_quote.append(float(pezzo.replace(",", ".")))
        if not riga_quote:
            if raccolti:
                break
            continue
        for quota in reversed(riga_quote):
            raccolti.insert(0, quota)
    return raccolti


def _parse_singolo_blocco_partente(
    numero: int,
    linee_blocco: list[str],
) -> PartenteGaraGrezzo | None:
    linee = [ln for ln in linee_blocco if ln is not None]
    if not linee:
        return None

    nome = _estrai_nome_inizio_blocco(linee)
    if not nome:
        return None

    indice_eta = _indice_riga_eta_yo(linee)
    if indice_eta is None:
        return None

    fantino = _estrai_fantino_dopo_eta(linee, indice_eta)
    if not fantino:
        return None

    decimali = _estrai_decimali_coda_blocco(linee)
    if not decimali:
        return None

    quota_vincente = decimali[0]
    if quota_vincente < SOGLIA_QUOTA_VINCENTE_SIGMA:
        return None

    quota_piazzato = decimali[1] if len(decimali) > 1 else None

    blocco_testo = "\n".join(linee).strip()
    return PartenteGaraGrezzo(
        numero=numero,
        nome=nome,
        fantino=fantino,
        quota_vincente=quota_vincente,
        quota_piazzato=quota_piazzato,
        eta=_estrai_eta_da_blocco(linee),
        rating=_estrai_rating_da_blocco(linee),
        ultimi_arrivi=_estrai_ultimi_arrivi_da_blocco(linee),
        blocco=blocco_testo,
    )

def parse_dati_gara(testo: str) -> pd.DataFrame:
    """
    Parser Blindato Universale (Tritatutto).
    - Divide il testo in righe. Ignora le righe vuote.
    - Per ogni riga: cerca il primo numero intero all'inizio (Numero cavallo).
    - Cerca l'ultimo numero (intero o decimale) alla fine della riga. Se esiste, è la Quota. Se NON esiste, Quota = 0.0.
    - Tutto il testo in mezzo è il Nome del cavallo.
    - Restituisce SEMPRE un DataFrame Pandas con ['Numero', 'Nome', 'Quota'].
    - Non scarta MAI una riga se ha almeno un numero e una parola.
    """
    import pandas as pd
    import re
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    dati = []
    
    num_iniziale_re = re.compile(r'^(\d+)')
    num_finale_re = re.compile(r'(\d+(?:[.,]\d+)?)$')
    parola_re = re.compile(r'[a-zA-Z]+')
    
    for riga in righe:
        match_inizio = num_iniziale_re.search(riga)
        if not match_inizio:
            continue
            
        numero_str = match_inizio.group(1)
        riga_resto = riga[len(numero_str):].strip()
        
        match_fine = num_finale_re.search(riga_resto)
        if match_fine:
            quota_str = match_fine.group(1)
            quota_val = float(quota_str.replace(',', '.'))
            nome_cavallo = riga_resto[: -len(quota_str)].strip()
        else:
            quota_val = 0.0
            nome_cavallo = riga_resto.strip()
            
        nome_cavallo = re.sub(r'^[\W_]+', '', nome_cavallo)
        nome_cavallo = re.sub(r'[\W_]+$', '', nome_cavallo)
        
        if parola_re.search(nome_cavallo):
            dati.append({
                'Numero': int(numero_str),
                'Nome': nome_cavallo,
                'Quota': quota_val
            })
            
    return pd.DataFrame(dati, columns=['Numero', 'Nome', 'Quota'])



def parse_partenti_testo_grezzo(testo: str) -> list[PartenteGaraGrezzo]:
    """
    Estrae i partenti da testo bookmaker (Trotto + Galoppo).
    Lettura a blocchi: N° isolato → gabbia opzionale → nome → fantino → quote.
    Nessun dato simulato; salta blocchi incompleti o con quota vincente < 1.60.
    """
    grezzo = testo.strip()
    if not grezzo:
        return []

    risultato: list[PartenteGaraGrezzo] = []
    for numero, linee_blocco in _split_blocchi_partenti_grezzo(grezzo):
        partente = _parse_singolo_blocco_partente(numero, linee_blocco)
        if partente is not None:
            risultato.append(partente)
    return risultato


def partente_grezzo_a_record_dict(partente: PartenteGaraGrezzo) -> dict[str, object]:
    """Record compatibile con Distribuzione Sigma / DataFrame partenti."""
    quote_valide = [partente.quota_vincente]
    if partente.quota_piazzato is not None:
        quote_valide.append(partente.quota_piazzato)
    return {
        "numero": partente.numero,
        "nome": partente.nome,
        "fantino": partente.fantino,
        "eta": partente.eta,
        "rating": partente.rating,
        "ultimi_arrivi": partente.ultimi_arrivi,
        "quote_valide": quote_valide,
        "blocco": partente.blocco,
    }


def etichetta_cavallo(numero_partente: int) -> str:
    return f"Cavallo n. {numero_partente}"


@dataclass
class Corsa:
    posizione: str
    data_gara: str
    ippodromo: str
    distanza_m: str
    unita_misura: str
    parte: str
    fantino: str
    quota: str
    raw_riga: str = ""


@dataclass
class SchedaCavallo:
    numero_partente: int
    nome: str
    note: str
    eta: str
    sesso: str
    allenatore: str
    flatsix: str
    genealogia: str
    proprietario: str
    corse: list[Corsa] = field(default_factory=list)
    righe_corse_non_parse: list[str] = field(default_factory=list)


def _extract_flatsix(text: str) -> str:
    m = FLATSIX_RE.search(text) or TOTALSIX_RE.search(text)
    return m.group(1).strip() if m else ""


def _valid_date(day: int, month: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _split_posizione_data(line: str) -> tuple[str, str, str] | None:
    testo = line.lstrip()
    for m in DATE_AT_START_RE.finditer(testo):
        prefisso = testo[:m.start()].strip()
        if prefisso and (not prefisso.isdigit() or len(prefisso) > 2):
            continue
        data_gara = m.group(1)
        d, mo, _y = data_gara.split("/")
        if _valid_date(int(d), int(mo)):
            tail = testo[m.end():]
            return prefisso, data_gara, tail
    return None


def _find_quota_boundary(tail: str) -> tuple[int, int, str] | None:
    """Trova una quota finale, anche intera e concatenata alla corsa seguente."""
    for candidate in QUOTA_CANDIDATE_RE.finditer(tail):
        token = candidate.group(0)
        restante = tail[candidate.end():].lstrip()
        if not restante or _split_posizione_data(restante) is not None:
            return candidate.start(), candidate.end(), token

        # Caso ambiguo senza spazi: quota intera + posizione/data successiva,
        # ad esempio "... Mason 5216/4/26" = quota 5 + "2 16/4/26".
        if "." not in token and "," not in token:
            for cut in range(1, len(token)):
                restante = (token[cut:] + tail[candidate.end():]).lstrip()
                if _split_posizione_data(restante) is not None:
                    return candidate.start(), candidate.start() + cut, token[:cut]
    return None


def parse_compact_races(scheda_testo: str) -> list[Corsa]:
    """Trova tutte le corse complete nel testo schiacciato via finditer."""
    corse_trovate: list[Corsa] = []
    for match in COMPACT_RACE_RE.finditer(scheda_testo):
        corse_trovate.append(
            Corsa(
                posizione=match.group("posizione"),
                data_gara=match.group("data"),
                ippodromo=match.group("ippodromo").strip(),
                distanza_m=match.group("distanza").replace(",", "."),
                unita_misura=match.group("unita").lower(),
                parte=match.group("parte"),
                fantino=_normalizza_fantino_estratto(
                    " ".join(match.group("fantino").split())
                ),
                quota=match.group("quota").replace(",", "."),
                raw_riga=match.group(0),
            )
        )
    return corse_trovate


def parse_race_blob(blob: str) -> tuple[list[Corsa], list[str]]:
    """Estrae corse internazionali senza dizionari di ippodromi o unità.

    Una corsa è delimitata da posizione+data all'inizio e quota numerica
    alla fine. L'unità viene acquisita come testo libero e conservata.
    """
    righe = [riga.strip() for riga in blob.splitlines() if riga.strip()]

    # Percorso principale per tabelle con una corsa per riga. Sono necessari
    # soltanto posizione, data e quota finale; spazi multipli e tab sono validi.
    if righe and all(RACE_LINE_RE.fullmatch(riga) for riga in righe):
        corse_trovate: list[Corsa] = []
        for riga in righe:
            match = RACE_LINE_RE.fullmatch(riga)
            assert match is not None
            testo_intermedio = match.group("testo_intermedio").strip()
            dettagli = RACE_DETAILS_RE.fullmatch(testo_intermedio)
            if dettagli is None:
                ippodromo = testo_intermedio
                distanza = unita = parte = fantino = ""
            else:
                ippodromo, distanza, unita, parte, fantino = dettagli.groups()

            corse_trovate.append(
                Corsa(
                    posizione=match.group("posizione"),
                    data_gara=match.group("data"),
                    ippodromo=ippodromo.strip(),
                    distanza_m=distanza.replace(",", "."),
                    unita_misura=unita.strip(),
                    parte=parte,
                    fantino=_normalizza_fantino_estratto(fantino),
                    quota=match.group("quota").replace(",", "."),
                    raw_riga=riga,
                )
            )
        return corse_trovate, []

    # Fallback per il vecchio formato web con più corse concatenate.
    corse: list[Corsa] = []
    errors: list[str] = []
    pos = 0
    text = re.sub(r"[\r\n]+", " ", blob.strip())

    while pos < len(text):
        chunk = text[pos:].lstrip()
        pos += len(text[pos:]) - len(chunk)
        header = _split_posizione_data(chunk)
        if not header:
            if chunk:
                errors.append(chunk[:80] + ("…" if len(chunk) > 80 else ""))
            break
        posizione, data_gara, tail = header

        quota_boundary = _find_quota_boundary(tail)
        if quota_boundary is None:
            errors.append(chunk[:80] + ("…" if len(chunk) > 80 else ""))
            break
        quota_start, quota_end, quota_token = quota_boundary

        dettagli = tail[:quota_start].strip()
        detail_match = RACE_DETAILS_RE.match(dettagli)
        if detail_match is None:
            # La riga resta valida (data + quota): conserviamo integralmente
            # il payload invece di scartare o inventare campi.
            ippodromo = dettagli
            distanza = unita = parte = fantino = ""
        else:
            ippodromo, distanza, unita, parte, fantino = detail_match.groups()
        quota = quota_token.replace(",", ".")
        consumed = (len(chunk) - len(tail)) + quota_end
        raw_riga = chunk[:consumed].strip()
        pos += consumed
        corse.append(
            Corsa(
                posizione=posizione,
                data_gara=data_gara,
                ippodromo=ippodromo.strip(),
                distanza_m=distanza.replace(",", "."),
                unita_misura=unita.strip(),
                parte=parte,
                fantino=_normalizza_fantino_estratto(fantino),
                quota=quota,
                raw_riga=raw_riga,
            )
        )

    return corse, errors


def _section_text(lines: list[str], start_label: str, stop_labels: tuple[str, ...]) -> str:
    try:
        start = next(
            i
            for i, ln in enumerate(lines)
            if ln.strip().lower().rstrip(":") == start_label.lower()
        )
    except StopIteration:
        return ""
    start += 1
    collected: list[str] = []
    stop_set = {s.lower() for s in stop_labels}
    for ln in lines[start:]:
        stripped = ln.strip()
        if not stripped:
            continue
        head = stripped.lower().rstrip(":").split(":")[0].strip()
        if head in stop_set:
            break
        collected.append(stripped)
    return "\n".join(collected)


def parse_scheda_completa(raw: str, numero_partente: int) -> SchedaCavallo | None:
    text = raw.strip()
    if not text:
        return None

    lines = [ln.rstrip() for ln in text.splitlines()]
    nome = etichetta_cavallo(numero_partente)

    note = _section_text(
        lines,
        "Note",
        (
            "Cavallo",
            "Età",
            "Sesso",
            "Allenatore",
            "Genealogia",
            "Allevatore",
            "Stato di Forma",
            "FlatSix",
            "TotalSix",
            "Ultime Corse",
        ),
    )
    if not note:
        note = _section_text(
            lines,
            "Notes",
            (
                "Cavallo",
                "Età",
                "Allenatore",
                "Genealogia",
                "Stato di Forma",
                "FlatSix",
                "TotalSix",
                "Ultime Corse",
            ),
        )

    eta_m = ETA_RE.search(text)
    sesso_m = SESSO_RE.search(text)
    prop_m = PROPRIETARIO_RE.search(text)

    eta = eta_m.group(1).strip() if eta_m else ""
    sesso = sesso_m.group(1).strip() if sesso_m else ""
    flatsix = _extract_flatsix(text)

    allenatore = ""
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "allenatore" and i + 1 < len(lines):
            allenatore = lines[i + 1].strip()
            break
    if not allenatore:
        block = _section_text(
            lines,
            "Allenatore",
            ("Genealogia", "Allevatore", "Stato di Forma", "FlatSix", "TotalSix", "Ultime Corse"),
        )
        allenatore = block.split("\n")[0].strip() if block else ""

    gene_lines: list[str] = []
    if nonno := NONNO_RE.search(text):
        gene_lines.append(f"Nonno Materno: {nonno.group(1).strip()}")
    if padre := PADRE_RE.search(text):
        gene_lines.append(f"Padre: {padre.group(1).strip()}")
    genealogia = "\n".join(gene_lines)

    proprietario = prop_m.group(1).strip() if prop_m else ""

    # Prima scelta: ricerca globale sul testo grezzo, indispensabile quando
    # intestazione e record sono incollati senza spazi o ritorni a capo.
    corse = parse_compact_races(text)
    parse_err: list[str] = []

    if not corse:
        corse_blob = ""
        try:
            ultime_idx = next(
                i for i, ln in enumerate(lines) if ln.strip().lower() == "ultime corse"
            )
            race_lines = lines[ultime_idx + 1 :]
            cleaned: list[str] = []
            for ln in race_lines:
                if not ln.strip():
                    continue
                if ULTIME_CORSE_HEADER_RE.match(ln.strip()):
                    continue
                cleaned.append(ln.strip())
            corse_blob = "\n".join(cleaned)
        except StopIteration:
            corse_blob = ""

        corse, parse_err = parse_race_blob(corse_blob) if corse_blob else ([], [])

    return SchedaCavallo(
        numero_partente=numero_partente,
        nome=nome,
        note=note,
        eta=eta,
        sesso=sesso,
        allenatore=allenatore,
        flatsix=flatsix,
        genealogia=genealogia,
        proprietario=proprietario,
        corse=corse,
        righe_corse_non_parse=parse_err,
    )


def _parse_data_gara(data_gara: str) -> datetime | None:
    try:
        return datetime.strptime(data_gara, "%d/%m/%y")
    except ValueError:
        try:
            parts = data_gara.split("/")
            if len(parts) == 3:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                return datetime(2000 + y if y < 100 else y, m, d)
        except (ValueError, TypeError):
            return None
    return None


def analizza_cavallo(scheda: SchedaCavallo) -> str:
    lines: list[str] = [
        f"=== Analisi: {scheda.nome} (partente n. {scheda.numero_partente}) ===",
        "",
        "— Anagrafica —",
        f"Età: {scheda.eta or '(mancante)'} | Sesso: {scheda.sesso or '(mancante)'}",
        f"Allenatore: {scheda.allenatore or '(mancante)'}",
        f"FlatSix: {scheda.flatsix or '(mancante)'}",
        f"Corse lette: {len(scheda.corse)}",
    ]
    if scheda.note:
        lines.append(f"Note: {scheda.note}")
    if scheda.righe_corse_non_parse:
        lines.append(
            f"ATTENZIONE: {len(scheda.righe_corse_non_parse)} frammento/i non interpretato/i "
            "(esclusi dal calcolo, nessun dato inventato)."
        )
    lines.append("")

    lines.append("— Trend di forma (FlatSix) —")
    if scheda.flatsix:
        digits = [int(c) for c in scheda.flatsix if c.isdigit()]
        if len(digits) >= 2:
            recent = digits[-3:] if len(digits) >= 3 else digits[-2:]
            older = digits[:-3] if len(digits) >= 3 else digits[:-2]
            avg_recent = statistics.mean(recent)
            avg_older = statistics.mean(older) if older else avg_recent
            if avg_recent < avg_older:
                trend = "miglioramento (valori recenti più bassi → prestazioni migliori)."
            elif avg_recent > avg_older:
                trend = "peggioramento (valori recenti più alti)."
            else:
                trend = "stabilità nella sequenza FlatSix."
            lines.append(f"Sequenza: {' → '.join(str(d) for d in digits)}")
            lines.append(
                f"Media ultimi {len(recent)}: {avg_recent:.2f} | "
                f"media precedenti: {avg_older:.2f} → {trend}"
            )
        elif digits:
            lines.append(f"Sequenza troppo corta per un trend: {digits[0]}.")
        else:
            lines.append("FlatSix presente ma senza cifre numeriche utili.")
    else:
        lines.append("FlatSix assente: trend di forma non calcolabile.")

    lines.append("")
    lines.append("— Analisi metrica / distanza —")
    if scheda.corse:
        distanze = [
            float(c.distanza_m)
            for c in scheda.corse
            if re.fullmatch(r"\d+(?:\.\d+)?", c.distanza_m)
        ]
        if not distanze:
            lines.append("Distanze non strutturate: confronto metrico escluso.")
            distanze = []
    else:
        distanze = []

    if distanze:
        spread = max(distanze) - min(distanze)
        media = statistics.mean(distanze)
        lines.append(
            f"Distanze numeriche: min {min(distanze):g}, max {max(distanze):g}, "
            f"media {media:.0f}, escursione {spread:g}. "
            "Il confronto diretto è indicativo se le unità sono diverse."
        )
        if spread <= 200:
            lines.append("Profilo coerente: specialista su distanza simile.")
        elif spread <= 400:
            lines.append("Profilo moderato: flessibilità media sulle distanze.")
        else:
            lines.append("Profilo variabile: escursione elevata tra le ultime uscite.")
    elif not scheda.corse:
        lines.append("Nessuna corsa valida: analisi distanza non disponibile.")

    lines.append("")
    lines.append("— Trend fantino e quota —")
    if scheda.corse:
        ordered = sorted(
            scheda.corse,
            key=lambda c: _parse_data_gara(c.data_gara) or datetime.min,
        )
        quote = [float(c.quota) for c in ordered]
        fantini = list(dict.fromkeys(c.fantino for c in ordered))
        lines.append(f"Fantini impiegati: {', '.join(fantini)} ({len(fantini)} distinti).")
        if len(quote) >= 2:
            delta = quote[-1] - quote[0]
            if delta < -0.5:
                q_trend = "quote in calo (maggiore fiducia del mercato nelle uscite recenti)."
            elif delta > 0.5:
                q_trend = "quote in aumento (minore favoritismo recente)."
            else:
                q_trend = "quote sostanzialmente stabili."
            lines.append(
                f"Quota prima uscita (cronologica): {quote[0]:.2f} → "
                f"ultima: {quote[-1]:.2f}. {q_trend}"
            )
        posizioni = [int(c.posizione) for c in ordered if c.posizione.isdigit()]
        if posizioni:
            lines.append(
                f"Posizioni (ordine cronologico): {', '.join(str(p) for p in posizioni)}."
            )
    else:
        lines.append("Nessuna corsa valida: trend fantino/quota non disponibile.")

    lines.append("")
    lines.append("— Sintesi pronostico —")
    if not scheda.corse and not scheda.flatsix:
        lines.append("Dati insufficienti per una valutazione affidabile.")
    else:
        hints: list[str] = []
        if scheda.flatsix:
            digits = [int(c) for c in scheda.flatsix if c.isdigit()]
            if digits and digits[-1] <= 3:
                hints.append("FlatSix recente favorevole.")
            elif digits and digits[-1] >= 7:
                hints.append("FlatSix recente debole.")
        if scheda.corse:
            last = _ultima_corsa(scheda)
            assert last is not None
            if last.posizione.isdigit() and int(last.posizione) <= 3:
                hints.append("Ultima uscita in posizione alta.")
            try:
                if float(last.quota) <= 6.0:
                    hints.append("Ultima quota contenuta.")
            except ValueError:
                pass
        lines.append(
            " ".join(hints) if hints else "Valutazione neutra: monitorare prossima uscita con dati reali."
        )

    return "\n".join(lines)


@dataclass
class MetricheConfronto:
    nome: str
    numero_partente: int
    cavallo_id: int
    flatsix_media_recente: float | None
    ultima_quota: float | None
    media_posizioni_recenti: float | None
    punteggio_composito: float
    dati_parziali: bool


def _flatsix_media_recente(scheda: SchedaCavallo) -> float | None:
    digits = [int(c) for c in scheda.flatsix if c.isdigit()]
    if not digits:
        return None
    recent = digits[-3:] if len(digits) >= 3 else digits
    return statistics.mean(recent)


def _ultima_corsa(scheda: SchedaCavallo) -> Corsa | None:
    if not scheda.corse:
        return None
    return max(
        scheda.corse,
        key=lambda c: _parse_data_gara(c.data_gara) or datetime.min,
    )


def _media_posizioni_recenti(scheda: SchedaCavallo, n: int = 3) -> float | None:
    ordered = sorted(
        scheda.corse,
        key=lambda c: _parse_data_gara(c.data_gara) or datetime.min,
    )
    posizioni = [int(c.posizione) for c in ordered[-n:] if c.posizione.isdigit()]
    if not posizioni:
        return None
    return statistics.mean(posizioni)


def _calcola_metriche(cavallo_id: int, scheda: SchedaCavallo) -> MetricheConfronto:
    fs = _flatsix_media_recente(scheda)
    quota = None
    ultima = _ultima_corsa(scheda)
    if ultima is not None:
        try:
            quota = float(ultima.quota)
        except ValueError:
            quota = None
    media_pos = _media_posizioni_recenti(scheda)
    partial = fs is None or quota is None or media_pos is None
    score = 0.0
    weight = 0.0
    if fs is not None:
        score += max(0.0, 10.0 - fs) * 0.35
        weight += 0.35
    if quota is not None:
        score += max(0.0, 25.0 - quota) * 0.30
        weight += 0.30
    if media_pos is not None:
        score += max(0.0, 12.0 - media_pos) * 0.35
        weight += 0.35
    composito = (score / weight) if weight else 0.0
    return MetricheConfronto(
        nome=scheda.nome,
        numero_partente=scheda.numero_partente,
        cavallo_id=cavallo_id,
        flatsix_media_recente=fs,
        ultima_quota=quota,
        media_posizioni_recenti=media_pos,
        punteggio_composito=composito,
        dati_parziali=partial,
    )


def _fmt_opt_float(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "n/d"
    return f"{value:.{decimals}f}"


def _ranking_linee(
    metriche: list[MetricheConfronto],
    key_fn,
    titolo: str,
    lower_is_better: bool,
) -> list[str]:
    valid = [(m, key_fn(m)) for m in metriche if key_fn(m) is not None]
    if not valid:
        return [f"{titolo}: dati insufficienti per tutti i concorrenti."]
    valid.sort(key=lambda x: x[1], reverse=not lower_is_better)
    lines = [titolo + ":"]
    for i, (m, val) in enumerate(valid, start=1):
        lines.append(
            f"  {i}. {m.nome} [n. {m.numero_partente}] ({_fmt_opt_float(val)})"
        )
    return lines


def analizza_corsa_completa(concorrenti: list[tuple[int, SchedaCavallo]]) -> str:
    if len(concorrenti) < 2:
        return "Servono almeno 2 cavalli salvati per la stessa corsa."

    metriche = [_calcola_metriche(cid, s) for cid, s in concorrenti]
    metriche.sort(key=lambda m: m.numero_partente)
    lines: list[str] = [
        "=== Analisi corsa completa ===",
        f"Concorrenti (ordine inserimento, da database): {len(metriche)}",
        "",
        "Criteri: FlatSix recente, ultima quota, media posizioni ultime uscite.",
        "",
    ]
    lines.extend(
        _ranking_linee(
            metriche,
            lambda m: m.flatsix_media_recente,
            "— Classifica FlatSix (media ultime cifre)",
            lower_is_better=True,
        )
    )
    lines.append("")
    lines.extend(
        _ranking_linee(
            metriche,
            lambda m: m.ultima_quota,
            "— Classifica quote (ultima uscita)",
            lower_is_better=True,
        )
    )
    lines.append("")
    lines.extend(
        _ranking_linee(
            metriche,
            lambda m: m.media_posizioni_recenti,
            "— Classifica prestazioni recenti (media posizioni)",
            lower_is_better=True,
        )
    )
    lines.append("")
    lines.append("— Classifica composita (pronostico corsa) —")
    composite_sorted = sorted(
        metriche, key=lambda m: m.punteggio_composito, reverse=True
    )
    for i, m in enumerate(composite_sorted, start=1):
        note = " (dati parziali)" if m.dati_parziali else ""
        lines.append(
            f"  {i}. {m.nome} [partente n. {m.numero_partente}] — "
            f"punteggio {_fmt_opt_float(m.punteggio_composito)}{note}"
        )
    if composite_sorted:
        top = composite_sorted[0]
        lines.append("")
        lines.append(
            f"Pronostico sintetico: {top.nome} (partente n. {top.numero_partente}) "
            f"in testa — id {top.cavallo_id}. Solo dati reali salvati in database."
        )
    return "\n".join(lines)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_database(path: str = DB_PATH) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cavalli (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                eta TEXT,
                sesso TEXT,
                allenatore TEXT,
                totalsix TEXT,
                genealogia TEXT,
                proprietario TEXT,
                inserito_il TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ultime_corse (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cavallo_id INTEGER NOT NULL,
                posizione TEXT NOT NULL,
                data_gara TEXT NOT NULL,
                ippodromo TEXT NOT NULL,
                distanza_m TEXT NOT NULL,
                unita_misura TEXT,
                parte TEXT NOT NULL,
                fantino TEXT NOT NULL,
                quota TEXT NOT NULL,
                raw_riga TEXT,
                FOREIGN KEY (cavallo_id) REFERENCES cavalli(id)
            )
            """
        )
        _ensure_column(conn, "cavalli", "note", "TEXT")
        _ensure_column(conn, "cavalli", "flatsix", "TEXT")
        _ensure_column(conn, "cavalli", "sessione_corsa", "TEXT")
        _ensure_column(conn, "cavalli", "numero_partente", "INTEGER")
        _ensure_column(conn, "ultime_corse", "unita_misura", "TEXT")
        _ensure_column(conn, "ultime_corse", "raw_riga", "TEXT")
        conn.commit()


def prossimo_numero_partente(sessione_corsa: str, db_path: str = DB_PATH) -> int:
    return len(carica_cavalli_sessione_da_db(sessione_corsa, db_path)) + 1


def salva_scheda(
    scheda: SchedaCavallo,
    sessione_corsa: str,
    db_path: str = DB_PATH,
) -> int:
    if not scheda.corse and not scheda.eta and not scheda.flatsix:
        raise ValueError("Scheda priva di dati salvabili.")

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO cavalli (
                nome, note, eta, sesso, allenatore, flatsix, totalsix,
                genealogia, proprietario, sessione_corsa, numero_partente,
                inserito_il
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
                datetime.now(pytz.timezone('Europe/Rome')).isoformat(timespec="seconds"),
            ),
        )
        cavallo_id = int(cur.lastrowid)
        if scheda.corse:
            conn.executemany(
                """
                INSERT INTO ultime_corse (
                    cavallo_id, posizione, data_gara, ippodromo,
                    distanza_m, unita_misura, parte, fantino, quota, raw_riga
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        cavallo_id,
                        c.posizione,
                        c.data_gara,
                        c.ippodromo,
                        c.distanza_m,
                        c.unita_misura,
                        c.parte,
                        c.fantino,
                        c.quota,
                        c.raw_riga,
                    )
                    for c in scheda.corse
                ],
            )
        conn.commit()
    return cavallo_id


def carica_scheda_da_id(cavallo_id: int, db_path: str = DB_PATH) -> SchedaCavallo | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT nome, note, eta, sesso, allenatore,
                   COALESCE(flatsix, totalsix, '') AS flatsix,
                   genealogia, proprietario,
                   COALESCE(numero_partente, 0) AS numero_partente
            FROM cavalli WHERE id = ?
            """,
            (cavallo_id,),
        ).fetchone()
        if row is None:
            return None
        corse_rows = conn.execute(
            """
            SELECT posizione, data_gara, ippodromo, distanza_m,
                   COALESCE(unita_misura, '') AS unita_misura,
                   parte, fantino, quota, COALESCE(raw_riga, '') AS raw_riga
            FROM ultime_corse WHERE cavallo_id = ?
            ORDER BY id
            """,
            (cavallo_id,),
        ).fetchall()
    corse = [
        Corsa(
            posizione=r["posizione"],
            data_gara=r["data_gara"],
            ippodromo=r["ippodromo"],
            distanza_m=r["distanza_m"],
            unita_misura=r["unita_misura"],
            parte=r["parte"],
            fantino=r["fantino"],
            quota=r["quota"],
            raw_riga=r["raw_riga"],
        )
        for r in corse_rows
    ]
    numero = int(row["numero_partente"]) or 0
    if numero <= 0:
        numero = cavallo_id
    return SchedaCavallo(
        numero_partente=numero,
        nome=row["nome"] or etichetta_cavallo(numero),
        note=row["note"] or "",
        eta=row["eta"] or "",
        sesso=row["sesso"] or "",
        allenatore=row["allenatore"] or "",
        flatsix=row["flatsix"] or "",
        genealogia=row["genealogia"] or "",
        proprietario=row["proprietario"] or "",
        corse=corse,
    )


def carica_cavalli_sessione_da_db(
    sessione_corsa: str,
    db_path: str = DB_PATH,
) -> list[tuple[int, SchedaCavallo]]:
    with sqlite3.connect(db_path) as conn:
        ids = [
            int(r[0])
            for r in conn.execute(
                """
                SELECT id FROM cavalli
                WHERE sessione_corsa = ?
                ORDER BY COALESCE(numero_partente, id), id
                """,
                (sessione_corsa,),
            ).fetchall()
        ]
    result: list[tuple[int, SchedaCavallo]] = []
    for cid in ids:
        scheda = carica_scheda_da_id(cid, db_path)
        if scheda is not None:
            result.append((cid, scheda))
    return result


class IppicaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Scheda ippica — inserimento e analisi")
        self.minsize(780, 620)
        self.sessione_corsa_id = str(uuid.uuid4())
        init_database()
        self._build_ui()
        self._aggiorna_sessione_corsa_label()
        self._aggiorna_prossimo_numero_label()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 5}
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        ttk.Label(
            main,
            text="Incolla la scheda (note, anagrafica, FlatSix/TotalSix, ultime corse). "
            "Il numero partente è assegnato automaticamente.",
        ).grid(row=0, column=0, sticky=tk.W, **pad)

        self.prossimo_numero_var = tk.StringVar()
        ttk.Label(main, textvariable=self.prossimo_numero_var, foreground="#006").grid(
            row=1, column=0, sticky=tk.W, **pad
        )

        self.scheda_text = scrolledtext.ScrolledText(
            main, wrap=tk.WORD, height=14, font=("Consolas", 10)
        )
        self.scheda_text.grid(row=2, column=0, sticky=tk.NSEW, **pad)
        main.rowconfigure(2, weight=1)

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, sticky=tk.EW, **pad)
        ttk.Button(
            btn_frame,
            text="Elabora e salva nel database",
            command=self._on_process,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btn_frame,
            text="Nuovo Cavallo",
            command=self._on_nuovo_cavallo,
        ).pack(side=tk.LEFT)

        corsa_frame = ttk.LabelFrame(main, text="Analisi corsa completa", padding=8)
        corsa_frame.grid(row=4, column=0, sticky=tk.EW, **pad)
        ttk.Button(
            corsa_frame,
            text="Analisi Corsa Completa",
            command=self._on_analisi_corsa,
        ).grid(row=0, column=0, sticky=tk.W)
        self.corsa_session_var = tk.StringVar()
        ttk.Label(corsa_frame, textvariable=self.corsa_session_var).grid(
            row=0, column=1, sticky=tk.W, padx=(12, 0)
        )
        ttk.Button(
            corsa_frame,
            text="Nuova corsa (svuota sessione)",
            command=self._on_nuova_corsa,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        ttk.Label(main, text="Report analisi / pronostico:").grid(
            row=5, column=0, sticky=tk.NW, **pad
        )
        self.report_text = scrolledtext.ScrolledText(
            main,
            wrap=tk.WORD,
            height=16,
            font=("Segoe UI", 10),
            state=tk.DISABLED,
        )
        self.report_text.grid(row=6, column=0, sticky=tk.NSEW, **pad)
        main.rowconfigure(6, weight=1)

        self.status_var = tk.StringVar(value="Pronto.")
        ttk.Label(main, textvariable=self.status_var, foreground="#444").grid(
            row=7, column=0, sticky=tk.W, **pad
        )

    def _set_report(self, content: str) -> None:
        self.report_text.configure(state=tk.NORMAL)
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, content)
        self.report_text.configure(state=tk.DISABLED)

    def _aggiorna_prossimo_numero_label(self) -> None:
        n = prossimo_numero_partente(self.sessione_corsa_id)
        self.prossimo_numero_var.set(
            f"Prossimo salvataggio: {etichetta_cavallo(n)} (ordine cronologico di inserimento)."
        )

    def _aggiorna_sessione_corsa_label(self) -> None:
        concorrenti = carica_cavalli_sessione_da_db(self.sessione_corsa_id)
        n = len(concorrenti)
        etichette = ", ".join(
            f"n.{s.numero_partente}" for _, s in concorrenti[:8]
        )
        if n > 8:
            etichette += ", …"
        extra = f" — {etichette}" if etichette else ""
        self.corsa_session_var.set(
            f"Cavalli salvati in sessione corsa: {n}{extra} "
            f"(minimo 2 per analisi comparativa)."
        )

    def _on_nuovo_cavallo(self) -> None:
        self.scheda_text.delete("1.0", tk.END)
        self._set_report("")
        self._aggiorna_prossimo_numero_label()
        n = prossimo_numero_partente(self.sessione_corsa_id)
        self.status_var.set(f"Campi puliti: pronto per {etichetta_cavallo(n)}.")

    def _on_nuova_corsa(self) -> None:
        self.sessione_corsa_id = str(uuid.uuid4())
        self._aggiorna_sessione_corsa_label()
        self._aggiorna_prossimo_numero_label()
        self.status_var.set(
            "Nuova sessione corsa: il prossimo salvataggio sarà Cavallo n. 1."
        )

    def _on_analisi_corsa(self) -> None:
        concorrenti = carica_cavalli_sessione_da_db(self.sessione_corsa_id)
        if len(concorrenti) < 2:
            messagebox.showinfo(
                "Analisi corsa completa",
                "Salva almeno 2 cavalli nella sessione corrente, poi riprova.",
            )
            return
        report = analizza_corsa_completa(concorrenti)
        self._set_report(report)
        self.status_var.set(
            f"Analisi corsa completata su {len(concorrenti)} concorrenti (lettura da database)."
        )

    def _on_process(self) -> None:
        raw = self.scheda_text.get("1.0", tk.END)
        if not raw.strip():
            messagebox.showwarning(
                "Dati mancanti",
                "Incollare la scheda completa del cavallo prima di elaborare.",
            )
            return

        numero = prossimo_numero_partente(self.sessione_corsa_id)
        scheda = parse_scheda_completa(raw, numero)
        if scheda is None:
            messagebox.showwarning("Errore", "Testo scheda non valido o vuoto.")
            return

        missing = []
        if not scheda.eta:
            missing.append("età")
        if not scheda.flatsix:
            missing.append("FlatSix")
        if not scheda.corse:
            missing.append("ultime corse")

        report = analizza_cavallo(scheda)
        if missing:
            report += (
                "\n\n— Campi mancanti —\n"
                + ", ".join(missing)
                + " non estratti: sezioni correlate limitate o assenti."
            )

        try:
            cavallo_id = salva_scheda(scheda, self.sessione_corsa_id)
        except ValueError as exc:
            messagebox.showwarning("Salvataggio", str(exc))
            self._set_report(report)
            return
        except sqlite3.Error as exc:
            messagebox.showerror("Database", f"Errore SQLite:\n{exc}")
            self._set_report(report)
            return

        self._aggiorna_sessione_corsa_label()
        n_sessione = len(carica_cavalli_sessione_da_db(self.sessione_corsa_id))
        report += (
            f"\n\n— Database —\nSalvato {scheda.nome} (partente n. {scheda.numero_partente}), "
            f"id={cavallo_id}, {len(scheda.corse)} corse storiche, "
            f"sessione corsa: {n_sessione} concorrenti."
        )
        self._set_report(report)
        self._aggiorna_prossimo_numero_label()
        self.status_var.set(
            f"Salvato {scheda.nome} — sessione corsa: {n_sessione} cavalli."
        )


def main() -> None:
    IppicaApp().mainloop()


if __name__ == "__main__":
    main()