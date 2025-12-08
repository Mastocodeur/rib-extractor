"""
RIB Extractor — Vision Large Model (Gemini 2.0 Flash via REST API)
=================================================================

Cette application Streamlit permet d'extraire automatiquement les informations
contenues dans un RIB (PDF ou image), en utilisant un modèle de vision Gemini.

Le flux complet :
1. Import du document PDF / image via l'interface Streamlit.
2. Conversion en base64 et envoi à l'API REST de Google GenAI (Gemini Flash).
3. Extraction intelligente :
   - Titulaire du compte
   - Code Banque / Code Guichet
   - Numéro de compte + Clé RIB
   - IBAN normalisé
   - BIC normalisé
   - Adresse complète de domiciliation
4. Nettoyage des données retournées
5. Affichage + Export CSV

Ce fichier est structuré pour être lisible, maintenable et robuste.
"""

import streamlit as st
import pandas as pd
import requests
import json
import base64
import re
import os
from dotenv import load_dotenv

#region call API
# =====================================================================
# 1 — Chargement clé API et configuration REST
# =====================================================================

load_dotenv()  # Permet d'utiliser .env en développement local

API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")

if not API_KEY:
    st.error("❌ Clé GEMINI_API_KEY manquante dans .env ou .streamlit/secrets.toml")
    st.stop()

# Endpoint officiel REST Gemini 2.0 Flash
API_URL = (
    "https://generativelanguage.googleapis.com/v1/models/"
    "gemini-2.5-flash:generateContent?key=" + API_KEY
)

#region prompt
# =====================================================================
# 2 — Prompt spécialisé pour l'extraction bancaire
# =====================================================================

PROMPT = """
Tu es un expert en documents bancaires français.

Analyse ce RIB et renvoie STRICTEMENT ce JSON :

{
  "titulaire": "",
  "code_banque": "",
  "code_guichet": "",
  "numero_compte": "",
  "cle_rib": "",
  "iban": "",
  "bic": "",
  "domiciliation": ""
}

RÈGLES :
- Si une information est absente : mets "".
- Ne JAMAIS inventer.
- Ne JAMAIS mettre autre chose que le contenu demandé.
- "titulaire" doit contenir uniquement le nom du titulaire du compte.
- "domiciliation" doit contenir toutes les lignes visibles.
- Tu dois renvoyer UNIQUEMENT le JSON, sans texte autour.
"""

#region nettoyage
# =====================================================================
# 3 — Fonctions utilitaires de nettoyage
# =====================================================================

def nettoyer_reponse_json(texte: str) -> str:
    """
    Extrait un objet JSON valide depuis la réponse du modèle.

    Le modèle Gemini renvoie parfois :
    - des blocs ```json { ... } ```
    - des blocs ``` { ... } ```
    - des réponses mixtes texte + JSON

    Cette fonction isole proprement le JSON.
    """
    if not texte:
        return texte

    # Cas 1 : ```json ... ```
    m = re.search(r"```json\s*(\{.*?\})\s*```", texte, re.DOTALL)
    if m:
        return m.group(1)

    # Cas 2 : ``` ... ```
    m = re.search(r"```\s*(\{.*?\})\s*```", texte, re.DOTALL)
    if m:
        return m.group(1)

    # Cas 3 : Premier JSON trouvé
    m = re.search(r"(\{.*\})", texte, re.DOTALL)
    if m:
        return m.group(1)

    return texte


def nettoyer_bic(bic: str) -> str:
    """
    Nettoie et valide un code BIC :
    - supprime les caractères non alphanumériques
    - met en majuscule
    - tronque à 8 ou 11 caractères
    """
    if not bic:
        return ""
    bic = re.sub(r"[^A-Za-z0-9]", "", bic).upper()
    return bic[:11] if len(bic) >= 11 else bic[:8]


def nettoyer_iban(iban: str) -> str:
    """
    Normalise un IBAN :
    - supprime les espaces
    - groupe par 4 caractères pour lisibilité
    """
    if not iban:
        return ""
    iban = iban.replace(" ", "").upper()
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))


def nettoyer_domiciliation(dom: str) -> str:
    """
    Nettoie la domiciliation :
    - supprime les lignes vides
    - conserve la structure multiline
    """
    if not dom:
        return ""
    lignes = [l.strip() for l in dom.split("\n") if l.strip()]
    return "\n".join(lignes)

#region API REST
# =====================================================================
# 4 — Fonction principale d'appel à l'API Gemini (REST)
# =====================================================================

def analyser_rib(file) -> str:
    """
    Envoie un document PDF ou image à l'API Gemini 2.0 Flash
    et renvoie la réponse brute du modèle.

    Paramètres
    ----------
    file : UploadedFile (Streamlit)
        Fichier PDF ou image fourni par l'utilisateur.

    Retour
    ------
    str : texte renvoyé par le modèle, ou message d'erreur formaté.
    """
    # Conversion du fichier en base64
    raw_bytes = file.read()
    # Encodage du fichier en Base64 pour l'envoi via l'API REST
    b64_data = base64.b64encode(raw_bytes).decode("utf-8")

    # Construction du payload REST pour Gemini :
    # - une partie texte (PROMPT)
    # - une partie image inline (document binaire encodé en base64)
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT}, # Prompt strict demandant un JSON propre
                    {
                        "inline_data": {
                            "mime_type": file.type, # type du fichier (pdf/png/jpeg)
                            "data": b64_data # encodage base64 du document
                        }
                    }
                ]
            }
        ]
    }

    try:
        # Envoi de la requête POST à l'API REST Gemini
        response = requests.post(API_URL, json=payload)
        res_json = response.json()

        # Cas : erreur API
        # Si Google renvoie un bloc "error", on le retourne proprement
        if "error" in res_json:
            return "__ERROR_API__ " + json.dumps(res_json["error"], ensure_ascii=False, indent=2)
        
        # Extraction du texte renvoyé par le modèle
        candidates = res_json.get("candidates", [])
        if not candidates:
            return "__ERROR_NO_CANDIDATE__ " + json.dumps(res_json, ensure_ascii=False, indent=2)

        # Extraction du texte complet depuis les parties
        parts = candidates[0].get("content", {}).get("parts", [])
        # Reconstruction du texte complet
        return "".join(p.get("text", "") for p in parts)

    except Exception as e:
        # En cas d'erreur technique, on renvoie un message formaté
        return f"__ERROR_EXCEPTION__ {e}"


# =====================================================================
# 5 — Interface utilisateur Streamlit
# =====================================================================

st.set_page_config(page_title="RIB Extractor (VLM REST)", page_icon="💳", layout="centered")

st.title("💳 RIB Extractor — Gemini Vision (API REST)")
st.markdown("""
Téléversez vos RIB (PDF ou images).  
L'IA extrait automatiquement :
- Titulaire du compte  
- Codes banque / guichet  
- Numéro + clé RIB  
- IBAN  
- BIC  
- Domiciliation complète  
""")

uploaded_files = st.file_uploader(
    "📁 Sélectionnez vos RIB :",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("En attente de fichiers…")
    st.stop()

rows = []
progress = st.progress(0)
total = len(uploaded_files)

#region traitement 
# =====================================================================
# 6 — Boucle de traitement pour chaque fichier
# =====================================================================

for idx, f in enumerate(uploaded_files):

    st.write(f"🔍 Analyse de **{f.name}**...")
    raw_response = analyser_rib(f)

    # Cas d'erreurs directes
    if raw_response.startswith("__ERROR__"):
        rows.append({
            "Fichier": f.name,
            "Titulaire du compte": "",
            "Code Banque": "",
            "Code Guichet": "",
            "N° de compte": "",
            "Clé RIB": "",
            "IBAN": "",
            "BIC / SWIFT": "",
            "Domiciliation": "",
            "Erreur": raw_response,
        })
        progress.progress((idx + 1) / total)
        continue

    # Nettoyage et parsing JSON
    json_clean = nettoyer_reponse_json(raw_response)

    try:
        data = json.loads(json_clean)
    except Exception:
        st.error(f"❌ Réponse non-JSON pour {f.name}")
        st.code(raw_response)
        rows.append({
            "Fichier": f.name,
            "Titulaire du compte": "",
            "Code Banque": "",
            "Code Guichet": "",
            "N° de compte": "",
            "Clé RIB": "",
            "IBAN": "",
            "BIC / SWIFT": "",
            "Domiciliation": "",
            "Erreur": "Réponse IA non JSON",
        })
        progress.progress((idx + 1) / total)
        continue

    # Normalisation

    iban_raw = data.get("iban", "")
    iban_normal = nettoyer_iban(iban_raw)
    # Ajout IBAN compact (sans espace) (demande utilisateur)
    iban_compact = iban_normal.replace(" ", "") if iban_normal else ""

    rows.append({
        "Fichier": f.name,
        "Titulaire du compte": data.get("titulaire", ""),
        "Code Banque": data.get("code_banque", ""),
        "Code Guichet": data.get("code_guichet", ""),
        "N° de compte": data.get("numero_compte", ""),
        "Clé RIB": data.get("cle_rib", ""),
        "IBAN": nettoyer_iban(data.get("iban", "")),
        "IBAN (compact)": iban_compact,
        "BIC / SWIFT": nettoyer_bic(data.get("bic", "")),
        "Domiciliation": nettoyer_domiciliation(data.get("domiciliation", "")),
        "Erreur": "",
    })

    progress.progress((idx + 1) / total)

#region résultats
# =====================================================================
# 7 — Résultats
# =====================================================================

df = pd.DataFrame(rows)

st.success("✅ Extraction terminée")
st.dataframe(df, width="stretch")

# --------- EXPORT CSV ---------
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Télécharger le CSV",
    data=csv,
    file_name="rib_extraction.csv",
    mime="text/csv",
)

import io
# ==================== EXPORT EXCEL ====================
excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
    df.to_excel(writer, index=False)
st.download_button(
    "📎 Télécharger en Excel (.xlsx)",
    data=excel_buffer.getvalue(),
    file_name="rib_extraction.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ==================== EXPORT PARQUET ====================
parquet_buffer = io.BytesIO()
df.to_parquet(parquet_buffer, index=False)
st.download_button(
    "🗂️ Télécharger en Parquet (.parquet)",
    data=parquet_buffer.getvalue(),
    file_name="rib_extraction.parquet",
    mime="application/octet-stream",
)