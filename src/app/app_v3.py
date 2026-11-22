"""
RIB Extractor v3 — Gemini Vision (primaire) + pdfplumber (vérification)

Stratégie :
  Primaire  — Gemini 2.0 Flash Vision sur tous les fichiers (PDF et images).
              Résultats fiables quelle que soit la mise en page du RIB.
  Vérif.    — Pour les PDF natifs uniquement, pdfplumber extrait le texte
              et les regex tentent de retrouver l'IBAN. Si les deux
              méthodes trouvent un IBAN, on les compare et on signale
              une concordance ou un écart dans la colonne "Vérification".
"""

import io
import json
import re

import pdfplumber
import streamlit as st
import pandas as pd
from pydantic import ValidationError
from google import genai
from google.genai import types

from config import Settings
from models import RibData
from utils import (
    nettoyer,
    extraire_par_libelles,
    extraire_iban_valide,
    construire_iban_fr,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_settings = Settings()
# Surcharge depuis st.secrets si la clé n'est pas dans .env (Streamlit Cloud)
if not _settings.gemini_api_key.get_secret_value():
    _settings = _settings.model_copy(
        update={"gemini_api_key": st.secrets.get("GEMINI_API_KEY", "")}
    )

_gemini_client: genai.Client | None = None
if _settings.gemini_api_key.get_secret_value():
    try:
        _gemini_client = genai.Client(api_key=_settings.gemini_api_key.get_secret_value())
    except Exception:
        _gemini_client = None


# ---------------------------------------------------------------------------
# Prompt Gemini
# ---------------------------------------------------------------------------

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
- Tu dois renvoyer UNIQUEMENT le JSON, sans texte autour.
"""


# ---------------------------------------------------------------------------
# Extraction Gemini (primaire, tous fichiers)
# ---------------------------------------------------------------------------

def _nettoyer_json(texte: str) -> str:
    """Isole le JSON dans la réponse brute du modèle."""
    for pat in [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r"(\{.*\})",
    ]:
        m = re.search(pat, texte, re.DOTALL)
        if m:
            return m.group(1)
    return texte


def extraire_via_gemini(raw_bytes: bytes, mime_type: str) -> RibData | str:
    """Envoie le document à Gemini et parse la réponse dans RibData.

    Les validators du modèle (normalise_iban, normalise_bic) s'appliquent
    automatiquement lors du model_validate_json.
    """
    if not _gemini_client:
        return "__ERROR__ Clé GEMINI_API_KEY manquante ou invalide"
    try:
        response = _gemini_client.models.generate_content(
            model=_settings.gemini_model,
            contents=[
                types.Part.from_text(text=PROMPT),
                types.Part.from_bytes(data=raw_bytes, mime_type=mime_type),
            ],
        )
        json_str = _nettoyer_json(response.text)
        return RibData.model_validate_json(json_str)
    except ValidationError as e:
        return f"__ERROR__ Données invalides ({e.error_count()} champ(s)) : {e.errors()[0]['msg']}"
    except json.JSONDecodeError:
        raw = getattr(response, "text", "")
        return f"__ERROR__ Réponse non-JSON : {raw[:200]}"
    except Exception as e:
        return f"__ERROR__ {e}"


# ---------------------------------------------------------------------------
# Vérification pdfplumber (PDF natifs uniquement)
# ---------------------------------------------------------------------------

def _extraire_texte_pdfplumber(raw_bytes: bytes) -> str:
    """Extrait le texte brut d'un PDF natif."""
    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def _extraire_iban_via_regex(texte: str) -> str:
    """Extrait uniquement l'IBAN depuis un texte pdfplumber pour comparaison."""
    tclean = nettoyer(texte)
    iban = extraire_iban_valide(tclean)
    if not iban:
        lb_cb, lb_cg, lb_nc, lb_cle, _, _ = extraire_par_libelles(tclean)
        if all([lb_cb, lb_cg, lb_nc, lb_cle]):
            iban = construire_iban_fr(lb_cb, lb_cg, lb_nc, lb_cle)
    return iban


def verifier_iban(iban_gemini: str, raw_bytes: bytes) -> str:
    """Compare l'IBAN Gemini avec celui extrait par pdfplumber.

    Retourne une chaîne de statut pour la colonne Vérification.
    """
    texte = _extraire_texte_pdfplumber(raw_bytes)
    if len(texte) < _settings.texte_min_chars:
        return "— scan ou image"

    iban_pdf = _extraire_iban_via_regex(texte)
    if not iban_pdf:
        return "— pdfplumber : aucun IBAN trouvé"

    if iban_gemini.replace(" ", "").upper() == iban_pdf.replace(" ", "").upper():
        return "✅ IBAN concordant"
    return f"⚠️ IBAN discordant — pdfplumber : {iban_pdf}"


# ---------------------------------------------------------------------------
# Interface Streamlit
# ---------------------------------------------------------------------------

st.set_page_config(page_title="RIB Extractor v3", page_icon="💳", layout="centered")

st.title("💳 RIB Extractor v3")
st.markdown("""
**Stratégie d'extraction :**
- **Gemini 2.0 Flash** — extraction principale sur tous les fichiers (PDF natif, scanné, image)
- **pdfplumber** — vérification croisée de l'IBAN sur les PDF natifs (colonne *Vérification*)

Téléversez vos RIB (PDF ou images) pour démarrer.
""")

if not _settings.gemini_api_key.get_secret_value():
    st.error(
        "❌ Aucune clé `GEMINI_API_KEY` détectée. "
        "Ajoutez-la dans `.env` ou `.streamlit/secrets.toml`."
    )
    st.stop()

uploaded_files = st.file_uploader(
    "📁 Sélectionnez vos RIB :",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("En attente de fichiers…")
    st.stop()

rows: list[dict] = []
progress = st.progress(0)
total = len(uploaded_files)

for idx, f in enumerate(uploaded_files):
    st.write(f"🔍 Analyse de **{f.name}**…")
    raw_bytes = f.read()
    erreur = ""
    verification = ""
    rib_data = RibData()

    # Extraction primaire : Gemini Vision (tous fichiers)
    result = extraire_via_gemini(raw_bytes, f.type)
    if isinstance(result, str):
        erreur = result
    else:
        rib_data = result
        # Vérification croisée : pdfplumber sur les PDF uniquement
        if f.type == "application/pdf":
            verification = verifier_iban(rib_data.iban, raw_bytes)

    rows.append(rib_data.to_export_row(f.name, "Gemini Vision", erreur, verification))
    progress.progress((idx + 1) / total)

df = pd.DataFrame(rows)

st.success("✅ Extraction terminée")
st.dataframe(df, use_container_width=True)

# --- Export CSV ---
csv_bytes = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Télécharger CSV",
    data=csv_bytes,
    file_name="rib_extraction_v3.csv",
    mime="text/csv",
)

# --- Export Excel ---
excel_buf = io.BytesIO()
with pd.ExcelWriter(excel_buf, engine="xlsxwriter") as writer:
    df.to_excel(writer, index=False)
st.download_button(
    "📎 Télécharger Excel",
    data=excel_buf.getvalue(),
    file_name="rib_extraction_v3.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# --- Export Parquet ---
parquet_buf = io.BytesIO()
df.to_parquet(parquet_buf, index=False)
st.download_button(
    "🗂️ Télécharger Parquet",
    data=parquet_buf.getvalue(),
    file_name="rib_extraction_v3.parquet",
    mime="application/octet-stream",
)
