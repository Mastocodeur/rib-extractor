"""
RIB Extractor - Analyse et extraction automatique des informations de RIB à partir de fichiers PDF.

Ce script lit tous les fichiers PDF présents dans le dossier spécifié, exécute une reconnaissance
optique de caractères (OCR) sur chaque page, puis tente d'extraire les informations suivantes :
    - Titulaire du compte
    - Code Banque
    - Code Guichet
    - Numéro de compte
    - Clé RIB
    - BIC / SWIFT
    - IBAN
    - Domiciliation (agence ou adresse)

Les données extraites sont ensuite exportées dans un fichier CSV, en conservant les zéros initiaux
et en forçant toutes les colonnes à être interprétées comme du texte.

Fonctionnalités principales :
    • OCR systématique sur tous les PDF (via Tesseract)
    • Extraction robuste avec expressions régulières et heuristiques
    • Validation et reconstruction partielle de l'IBAN lorsque possible
    • Formatage propre pour usage avec Excel ou autres outils

Auteur : GASMI Rémy
Date   : 2025-11
"""

import os
import re
import csv
import tempfile
import logging
import importlib
import pandas as pd
from pdf2image import convert_from_path
import pytesseract
from stdnum import iban as iban_lib


# ---------------------------------------------------------------------------
# Chargement dynamique du module swiftbic / bic (pour compatibilité future)
# ---------------------------------------------------------------------------

try:
    bic_lib = importlib.import_module("stdnum.swiftbic")
except ModuleNotFoundError:
    try:
        bic_lib = importlib.import_module("stdnum.bic")
    except ModuleNotFoundError:
        bic_lib = None


# ---------------------------------------------------------------------------
# Configuration générale
# ---------------------------------------------------------------------------

logging.getLogger("pdfminer").setLevel(logging.ERROR)

DOSSIER_PDF = "rib"                 # Dossier contenant les fichiers PDF à analyser
SORTIE_CSV = "rib_infos.csv"        # Nom du fichier CSV de sortie


# ---------------------------------------------------------------------------
# Expressions régulières pour l’extraction des champs RIB
# ---------------------------------------------------------------------------

PAT_CODE_BANQUE  = re.compile(r'(?i)\b(code\s*banque|banque|code\s*bq)\b\D*([0-9]{5})')
PAT_CODE_GUICHET = re.compile(r'(?i)\b(code\s*guichet|guichet)\b\D*([0-9]{5})')
PAT_NUM_COMPTE   = re.compile(r'(?i)\b(num(?:[ée]ro)?\s*de\s*compte|n[°\s]*compte|compte)\b\D*([A-Z0-9]{5,34})')
PAT_CLE_RIB      = re.compile(r'(?i)\b(cl[ée]\s*rib|cl[ée])\b\D*([0-9]{2})')
PAT_IBAN_FR_COMPACT = re.compile(r'FR\d{2}[A-Z0-9]{23}')
PAT_BIC = re.compile(
    r"""(?i)
        B[\.\s]*I[\.\s]*C
        (?:[\s\./:-]*S[\.\s]*W[\.\s]*I[\.\s]*F[\.\s]*T(?:\s*CODE)?)?
      | SWIFT(?:\s*CODE)?
      | CODE\s*B[\.\s]*I[\.\s]*C
      | ADRESSE\s*S[\.\s]*W[\.\s]*I[\.\s]*F[\.\s]*T
    """, re.VERBOSE
)


PAT_TITULAIRE = re.compile(
    r'(?i)\b(titulaire(?:\s*du\s*compte)?|nom\s+du\s+titul(?:aire)?|b[ée]n[ée]ficiaire|au\s*nom\s*de)\b\s*[:\-]?\s*([A-ZÉÈÊÀÂÎÏÔÙÜÇa-z0-9\.\'\-\s]+)'
)
PAT_DOMICILIATION = re.compile(r'(?i)\b(domiciliation|agence|adresse)\b\s*[:\-]?\s*([A-Z0-9\'\-\s,\.]+)')


# ---------------------------------------------------------------------------
# OCR : conversion PDF → image → texte
# ---------------------------------------------------------------------------

def extraire_texte_ocr(path: str) -> str:
    """
    Exécute une reconnaissance optique de caractères (OCR) sur un fichier PDF.
    Chaque page est convertie en image avant d’être analysée par Tesseract.

    Args:
        path (str): Chemin vers le fichier PDF.

    Returns:
        str: Texte brut extrait du PDF.
    """
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
# Fonctions utilitaires pour le nettoyage de texte
# ---------------------------------------------------------------------------

def nettoyer(texte: str) -> str:
    """Nettoie le texte pour supprimer les caractères parasites et espaces multiples."""
    texte = texte.replace('\r', '')
    texte = re.sub(r'[ \t]+', ' ', texte)
    return texte

def compacter(texte: str) -> str:
    """Supprime tout caractère non alphanumérique du texte (utile pour les IBAN)."""
    return re.sub(r'[^A-Za-z0-9]', '', texte)


# ---------------------------------------------------------------------------
# Fonctions de gestion du RIB et IBAN
# ---------------------------------------------------------------------------

def extraire_iban_valide(t: str) -> str:
    """Recherche et valide un IBAN français dans le texte."""
    compact = compacter(t).upper()
    for cand in set(PAT_IBAN_FR_COMPACT.findall(compact)):
        try:
            if iban_lib.is_valid(cand):
                return iban_lib.format(cand)
        except Exception:
            pass

    # Fallback : recherche basée sur le label "IBAN"
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
    """Décompose un IBAN français en code banque, guichet, numéro de compte et clé RIB."""
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
    """Convertit les lettres d'un numéro de compte en équivalent numérique (A=10, B=11, etc.)."""
    out = []
    for ch in s.upper():
        if ch.isdigit():
            out.append(ch)
        elif 'A' <= ch <= 'Z':
            out.append(str(10 + ord(ch) - ord('A')))
    return ''.join(out)

def calculer_cle_rib(cb: str, cg: str, nc: str) -> str:
    """Calcule la clé RIB à partir du code banque, guichet et numéro de compte."""
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
    """Construit un IBAN français complet à partir des composantes RIB."""
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


# ---------------------------------------------------------------------------
# Fonctions d’extraction du BIC, Titulaire et Domiciliation
# ---------------------------------------------------------------------------
PAT_BIC_CODE = re.compile(
    r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b'
)

def nettoyer_bic_ocr(chunk):
    """
    Nettoie un code BIC extrait de l'OCR :
    - supprime tous les caractères non alphanumériques
    - met en majuscules
    - tronque à 11 caractères maximum (format BIC)
    """
    if not chunk:
        return ""

    bic = re.sub(r'[^A-Za-z0-9]', '', chunk).upper()

    # Tronque : 11 > format complet, 8 > format court
    if len(bic) >= 11:
        return bic[:11]
    if len(bic) >= 8:
        return bic[:8]
    return ""



def extraire_bic_valide(texte):
    """
    Extrait un BIC de manière robuste en évitant les faux positifs (ex: 'BOULOGNE').
    Fonctionnement :
    1) Trouve un LABEL (BIC, SWIFT, B.I.C, Code BIC...)
    2) Regarde dans les lignes suivantes pour un vrai BIC (8 ou 11 caractères)
    3) Valide le format strictement
    """

    lignes = texte.split("\n")
    total = len(lignes)

    # 1) Trouver la ligne où apparaît un label BIC / SWIFT
    for idx, ligne in enumerate(lignes):
        if PAT_BIC.search(ligne):
            # Chercher dans les 5 lignes suivantes un vrai code BIC
            for j in range(idx, min(idx + 6, total)):
                candidats = PAT_BIC_CODE.findall(lignes[j].upper())

                for bic in candidats:
                    # Validation structurelle stricte
                    if len(bic) in (8, 11) and bic[:4].isalpha() and bic[4:6].isalpha():
                        
                        # Ne garde pas un mot d'adresse (Boulogne, Paris...)
                        if bic in ["PARIS", "BOULOGNE", "FRANCE"]:
                            continue

                        # Vérification via stdnum (si dispo)
                        if bic_lib:
                            try:
                                if bic_lib.is_valid(bic):
                                    return bic
                            except:
                                pass

                        return bic  # fallback : structure OK

    # 2) Fallback brut si aucun label trouvé
    candidats = PAT_BIC_CODE.findall(texte.upper())
    for bic in candidats:
        if len(bic) in (8, 11):
            return bic

    return ""


def extraire_titulaire(t: str) -> str:
    """Extrait le titulaire du compte, en essayant de corriger les erreurs OCR."""
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
    """
    Extrait la domiciliation sur plusieurs lignes, jusqu’à la prochaine rubrique identifiable.
    Combine toutes les lignes de l’agence ou de l’adresse.
    """
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

            dom = ' '.join(contenu)
            dom = re.sub(r'\s{2,}', ' ', dom)
            return dom.strip()

    # Fallback heuristique si le mot-clé n'existe pas
    for l in lignes:
        if re.search(r'(?i)\b(\d{1,4}\s+(rue|avenue|bd|boulevard|place|impasse))\b', l):
            return l.strip()
    for l in lignes:
        if 'RIB' in l.upper() and re.search(r'\d{1,4}\s', l):
            return l.split('RIB', 1)[-1].strip(' :.-')
    return ""


# ---------------------------------------------------------------------------
# Extraction complète d’un texte OCR
# ---------------------------------------------------------------------------

def extraire_par_libelles(t: str):
    """Extrait tous les champs d’un texte OCR via recherche de labels."""
    cb = cg = nc = cle = tit = dom = ""
    m = PAT_CODE_BANQUE.search(t);  cb = m.group(2) if m else ""
    m = PAT_CODE_GUICHET.search(t); cg = m.group(2) if m else ""
    m = PAT_NUM_COMPTE.search(t);   nc = m.group(2).replace(" ", "") if m else ""
    m = PAT_CLE_RIB.search(t);      cle = m.group(2) if m else ""
    tit = extraire_titulaire(t)
    dom = extraire_domiciliation(t)
    nc = re.sub(r'[^A-Z0-9]', '', nc.upper())
    return cb, cg, nc, cle, tit, dom


# ---------------------------------------------------------------------------
# Boucle principale d’analyse de tous les fichiers PDF
# ---------------------------------------------------------------------------

rows = []

for fichier in os.listdir(DOSSIER_PDF):
    if not fichier.lower().endswith(".pdf"):
        continue

    chemin = os.path.join(DOSSIER_PDF, fichier)
    print(f"OCR forcé sur {fichier}...")
    texte = extraire_texte_ocr(chemin)
    tclean = nettoyer(texte)

    iban = extraire_iban_valide(tclean)
    cb = cg = nc = cle = tit = dom = ""

    # Décomposition éventuelle de l’IBAN
    if iban:
        cb, cg, nc, cle = decomposer_iban_fr(iban)

    # Extraction par labels
    lb_cb, lb_cg, lb_nc, lb_cle, lb_tit, lb_dom = extraire_par_libelles(tclean)
    cb = cb or lb_cb
    cg = cg or lb_cg
    nc = nc or lb_nc
    cle = cle or lb_cle
    tit = lb_tit or extraire_titulaire(texte)
    dom = lb_dom or extraire_domiciliation(texte)

    # Calcul ou reconstruction si nécessaire
    if not cle and all([cb, cg, nc]):
        cle = calculer_cle_rib(cb, cg, nc)
    if not iban and all([cb, cg, nc, cle]):
        iban = construire_iban_fr(cb, cg, nc, cle)
    bic = extraire_bic_valide(tclean)

    def nz(v): return v if v else "MANQUANT"

    rows.append({
        "Fichier": fichier,
        "Titulaire du compte": nz(tit),
        "Code Banque": f"'{nz(cb)}",
        "Code Guichet": f"'{nz(cg)}",
        "N° de compte": f"'{nz(nc)}",
        "Clé RIB": f"'{nz(cle)}",
        "BIC / SWIFT": nz(bic),
        "IBAN": nz(iban),
        "Domiciliation": nz(dom)
    })


# ---------------------------------------------------------------------------
# Export final en CSV (toutes les colonnes en texte)
# ---------------------------------------------------------------------------

df = pd.DataFrame(rows, dtype=str)
df.to_csv(SORTIE_CSV, index=False, encoding="utf-8", quoting=csv.QUOTE_NONNUMERIC)
print(f"Données exportées vers {SORTIE_CSV}")
