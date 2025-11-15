"""
Module core pour l'extraction d'informations bancaires à partir de fichiers RIB (PDF).

Ce module fournit les fonctions nécessaires à :
- L'extraction OCR du texte
- L'identification des champs RIB (IBAN, BIC, Code Banque, etc.)
- La validation et reconstruction d'informations manquantes

Aucune exécution automatique n'est effectuée à l'import.
"""

import os
import re
import tempfile
import logging
import importlib
from pdf2image import convert_from_path
import pytesseract
from stdnum import iban as iban_lib

# --- Chargement dynamique du module BIC ---
try:
    bic_lib = importlib.import_module("stdnum.swiftbic")
except ModuleNotFoundError:
    try:
        bic_lib = importlib.import_module("stdnum.bic")
    except ModuleNotFoundError:
        bic_lib = None

# --- Réduction du bruit des logs PDF ---
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# --- Expressions régulières de détection des champs ---
PAT_CODE_BANQUE  = re.compile(r'(?i)\b(code\s*banque|banque|code\s*bq)\b\D*([0-9]{5})')
PAT_CODE_GUICHET = re.compile(r'(?i)\b(code\s*guichet|guichet)\b\D*([0-9]{5})')
PAT_NUM_COMPTE   = re.compile(r'(?i)\b(num(?:[ée]ro)?\s*de\s*compte|n[°\s]*compte|compte)\b\D*([A-Z0-9]{5,34})')
PAT_CLE_RIB      = re.compile(r'(?i)\b(cl[ée]\s*rib|cl[ée])\b\D*([0-9]{2})')
PAT_IBAN_FR_COMPACT = re.compile(r'FR\d{2}[A-Z0-9]{23}')
# Label BIC / SWIFT tolérant OCR
PAT_BIC = re.compile(
    r"""
    (?i)
    \b(
        B[\.\s]*I[\.\s]*C              # BIC / B.I.C / B I C
        (?:[\s\./:-]*S[\.\s]*W[\.\s]*I[\.\s]*F[\.\s]*T(?:\s*CODE)?)?
      | S[\.\s]*W[\.\s]*I[\.\s]*F[\.\s]*T(?:\s*CODE)?     # SWIFT / SWIFT CODE
      | CODE\s*B[\.\s]*I[\.\s]*C                          # CODE BIC
      | ADRESSE\s*S[\.\s]*W[\.\s]*I[\.\s]*F[\.\s]*T       # ADRESSE SWIFT
    )\b
    """,
    re.VERBOSE
)

# Pattern du code BIC lui-même (structure officielle, 8 ou 11 chars)
PAT_BIC_CODE = re.compile(
    r'[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?'
)



PAT_TITULAIRE = re.compile(
    r'(?i)\b(titulaire(?:\s*du\s*compte)?|nom\s+du\s+titul(?:aire)?|b[ée]n[ée]ficiaire|au\s*nom\s*de)\b\s*[:\-]?\s*([A-ZÉÈÊÀÂÎÏÔÙÜÇa-z0-9\.\'\-\s]+)'
)

# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def extraire_texte_ocr(path: str) -> str:
    """Réalise une extraction OCR complète du texte d’un PDF."""
    texte = ""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            images = convert_from_path(path, dpi=300, output_folder=tmp)
            for img in images:
                try:
                    texte += pytesseract.image_to_string(img, lang="fra") + "\n"
                except pytesseract.TesseractError:
                    texte += pytesseract.image_to_string(img, lang="eng") + "\n"
        except Exception as e:
            print(f"Erreur OCR sur {path}: {e}")
    return texte.strip()

# ---------------------------------------------------------------------------
# Fonctions de traitement du texte
# ---------------------------------------------------------------------------

def nettoyer(texte: str) -> str:
    """Nettoie le texte extrait (suppression espaces multiples et caractères parasites)."""
    texte = texte.replace('\r', '')
    texte = re.sub(r'[ \t]+', ' ', texte)
    return texte

def compacter(texte: str) -> str:
    """Compacte un texte en supprimant tout caractère non alphanumérique."""
    return re.sub(r'[^A-Za-z0-9]', '', texte)

# ---------------------------------------------------------------------------
# Fonctions d’extraction des informations bancaires
# ---------------------------------------------------------------------------

def extraire_iban_valide(t: str) -> str:
    """Recherche un IBAN français valide dans le texte."""
    compact = compacter(t).upper()
    for cand in set(PAT_IBAN_FR_COMPACT.findall(compact)):
        try:
            if iban_lib.is_valid(cand):
                return iban_lib.format(cand)
        except Exception:
            pass

    # Fallback : recherche d'un IBAN par label
    for m in re.finditer(r'(?i)\bIBAN\b\s*[:\-]?\s*([A-Z0-9 ]{8,50})', t):
        extrait = compacter(m.group(1)).upper()
        if extrait.startswith("FR") and len(extrait) >= 27:
            extrait = extrait[:27]
            try:
                if iban_lib.is_valid(extrait):
                    return iban_lib.format(extrait)
            except Exception:
                continue
    return ""

def decomposer_iban_fr(iban: str):
    """Décompose un IBAN français en code banque, guichet, compte et clé."""
    if not iban:
        return ("", "", "", "")
    try:
        c = iban_lib.compact(iban).upper()
        if not (c.startswith("FR") and iban_lib.is_valid(c)):
            return ("", "", "", "")
        bban = c[4:]
        return (bban[:5], bban[5:10], bban[10:21], bban[21:23])
    except Exception:
        return ("", "", "", "")

def lettres_vers_nombres(s: str) -> str:
    """Convertit les lettres d’un compte en nombres selon la convention RIB."""
    out = []
    for ch in s.upper():
        if ch.isdigit():
            out.append(ch)
        elif 'A' <= ch <= 'Z':
            out.append(str(10 + ord(ch) - ord('A')))
    return ''.join(out)

def calculer_cle_rib(cb: str, cg: str, nc: str) -> str:
    """Calcule la clé RIB à partir des composantes."""
    if not (cb and cg and nc):
        return ""
    base = f"{cb}{cg}{lettres_vers_nombres(nc)}"
    if not base.isdigit():
        return ""
    try:
        cle = 97 - (int(base) % 97)
        return f"{cle:02d}"
    except Exception:
        return ""

def construire_iban_fr(cb: str, cg: str, nc: str, cle: str) -> str:
    """Construit un IBAN FR à partir d’un RIB complet."""
    if not all([cb, cg, nc, cle]):
        return ""
    bban = f"{cb}{cg}{nc}{cle}"
    try:
        iban = iban_lib.from_bban("FR", bban)
        if iban_lib.is_valid(iban):
            return iban_lib.format(iban)
    except Exception:
        pass
    return ""


PAT_BIC_CODE = re.compile(
    r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b'
)

def nettoyer_bic_ocr(chunk):
    """
    Nettoie un BIC sorti de l'OCR :
    - supprime les espaces
    - supprime les points
    - remet en majuscules
    - limite à 11 caractères max
    """
    if not chunk:
        return ""

    bic = re.sub(r'[^A-Za-z0-9]', '', chunk).upper()

    # Certaines OCR lisent 'BOUS FRPP XXX' → 'BOUSFRPPXXX'
    # On ne garde que 8 ou 11 chars max.
    if len(bic) >= 11:
        bic = bic[:11]
    elif len(bic) >= 8:
        bic = bic[:8]

    return bic

def valider_normaliser_bic(raw: str) -> str:
    """
    Normalise un BIC (supprime le bruit) et le valide.

    Hypothèse volontairement forte :
    - On travaille sur des RIB français -> le code pays du BIC doit être 'FR'.
      Si tu veux accepter des banques étrangères, enlève ce test.
    """
    if not raw:
        return ""

    # Nettoyage brut
    bic = re.sub(r'[^A-Za-z0-9]', '', raw.upper())

    if len(bic) not in (8, 11):
        return ""

    # Filtre très fort pour éviter 'BOULOGNE', 'PARIS', etc.
    # BIC = 4 lettres banque + 2 lettres pays + 2 alnum localisation (+ 3 optionnels)
    if not (bic[:4].isalpha() and bic[4:6].isalpha()):
        return ""

    # Pour un RIB FR : pays = FR
    if bic[4:6] != "FR":
        return ""

    # Validation via python-stdnum si dispo
    if bic_lib:
        try:
            if not bic_lib.is_valid(bic):
                return ""
        except Exception:
            return ""

    return bic


def extraire_bic_valide(texte: str) -> str:
    """
    Extraction robuste du BIC :

    1. Trouve une ligne contenant un label BIC / SWIFT / Code BIC / Adresse SWIFT
    2. Regarde dans les quelques lignes suivantes pour un code BIC au bon format
    3. Valide et normalise (FR + python-stdnum)
    4. Fallback global sur tout le texte si aucun label trouvé
    """
    lignes = texte.splitlines()
    n = len(lignes)

    # 1) On cherche d'abord les zones où on parle de BIC / SWIFT
    for i, ligne in enumerate(lignes):
        if PAT_BIC.search(ligne):
            # On prend une fenêtre autour (ligne du label + quelques lignes suivantes)
            fenetre = "\n".join(lignes[i:i+6]).upper()

            # a) Recherche sur la fenêtre compactée (pour gérer 'BOUS FRPP XXX')
            compact = re.sub(r'[^A-Z0-9]', '', fenetre)
            candidats = PAT_BIC_CODE.findall(compact)
            for cand in candidats:
                bic = valider_normaliser_bic(cand)
                if bic:
                    return bic

            # b) Recherche sur la fenêtre brute (au cas où ce soit déjà bien collé)
            candidats = PAT_BIC_CODE.findall(fenetre)
            for cand in candidats:
                bic = valider_normaliser_bic(cand)
                if bic:
                    return bic

    # 2) Si aucun label trouvé ou rien de valide dans la zone → fallback global
    texte_up = texte.upper()
    compact_global = re.sub(r'[^A-Z0-9]', '', texte_up)
    candidats = PAT_BIC_CODE.findall(compact_global)
    for cand in candidats:
        bic = valider_normaliser_bic(cand)
        if bic:
            return bic

    return ""



def extraire_titulaire(t: str) -> str:
    """Extrait le titulaire du compte depuis le texte OCR."""
    m = PAT_TITULAIRE.search(t)
    if m:
        val = m.group(2).strip().split("\n")[0].strip()
        if len(val) > 3 and not re.search(r'\b(BIC|IBAN|DOMICILIATION)\b', val, re.I):
            return val
    for l in t.split('\n'):
        if re.search(r'\b(M\.|MME|MONSIEUR|MADAME|SARL|SAS|SA|EURL|SOCIETE)\b', l, re.I):
            return l.strip()
    return ""

def extraire_domiciliation(t: str) -> str:
    """Extrait la domiciliation sur plusieurs lignes consécutives."""
    lignes = [l.strip() for l in t.split('\n') if l.strip()]
    for i, l in enumerate(lignes):
        if re.search(r'(?i)\b(domiciliation|agence|adresse)\b', l):
            contenu = []
            m = re.search(r'(?i)\b(domiciliation|agence|adresse)\b[:\-\s]*(.*)', l)
            after = m.group(2).strip() if m else ""
            if after:
                contenu.append(after)
            for j in range(i + 1, len(lignes)):
                nextline = lignes[j]
                if re.search(r'(?i)\b(BIC|IBAN|TITULAIRE|COMPTE|CODE BANQUE|CLE RIB|CLÉ RIB|RIB)\b', nextline):
                    break
                if len(nextline) < 3:
                    break
                contenu.append(nextline)
            return ' '.join(contenu).strip()
    return ""

def extraire_par_libelles(t: str):
    """Extrait tous les champs RIB à partir des libellés textuels."""
    cb = cg = nc = cle = tit = dom = ""
    m = PAT_CODE_BANQUE.search(t);  cb = m.group(2) if m else ""
    m = PAT_CODE_GUICHET.search(t); cg = m.group(2) if m else ""
    m = PAT_NUM_COMPTE.search(t);   nc = m.group(2).replace(" ", "") if m else ""
    m = PAT_CLE_RIB.search(t);      cle = m.group(2) if m else ""
    tit = extraire_titulaire(t)
    dom = extraire_domiciliation(t)
    nc = re.sub(r'[^A-Z0-9]', '', nc.upper())
    return cb, cg, nc, cle, tit, dom
