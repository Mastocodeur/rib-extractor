# 🧾 RIB Extractor

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Gemini API](https://img.shields.io/badge/Google_AI-Gemini_2.0_Flash-yellow?logo=google&logoColor=white)](https://ai.google.dev)
[![UV Managed](https://img.shields.io/badge/Package_Manager-uv-7F52FF?logo=python&logoColor=white)](https://docs.astral.sh/uv/)

Outil d'extraction automatique des informations de RIB français, disponible en interface Streamlit.  
Stratégie d'extraction en deux passes : **pdfplumber** (PDF natif, sans API) puis **Gemini 2.0 Flash** (fallback scan/image).

![Demo de l'application](assets/demo.gif)

---

## 🚀 Fonctionnalités

L'outil extrait les champs suivants :

| Champ | Description |
|---|---|
| Titulaire | Nom du titulaire du compte |
| Code Banque | 5 chiffres |
| Code Guichet | 5 chiffres |
| N° de compte | 11 caractères alphanumériques |
| Clé RIB | 2 chiffres (calculée si absente) |
| IBAN | Formaté 4/4 + version compacte |
| BIC / SWIFT | Normalisé, validé |
| Domiciliation | Adresse complète de l'agence |

Exports disponibles : `.csv`, `.xlsx`, `.parquet`

---

## 🏗️ Architecture

```
src/
├── rib_extractor.py      # Script CLI batch (dossier rib/ → rib_infos.csv)
└── app/
    ├── utils.py          # Fonctions partagées (regex, IBAN, BIC, OCR)
    ├── app_v3.py         # Interface principale ✅ (pdfplumber + Gemini Vision)
    ├── app.py            # Archive — Gemini pure via API REST
    └── app_with_ocr.py   # Archive — Tesseract OCR local
```

### Stratégie d'extraction (`app_v3.py`)

```
Tous les fichiers (PDF natif, PDF scanné, image)
  └─→ Gemini 2.0 Flash Vision              extraction principale

PDF natif uniquement (texte sélectionnable)
  └─→ pdfplumber → regex (utils.py)        vérification croisée de l'IBAN
```

**Colonne "Vérification" dans les exports :**
- `✅ IBAN concordant` — pdfplumber et Gemini trouvent le même IBAN
- `⚠️ IBAN discordant` — les deux méthodes divergent (à investiguer)
- `— scan ou image` — pas de texte extractible, vérification impossible

---

## ⚙️ Installation

### 1. Cloner le projet

```bash
git clone https://github.com/Mastocodeur/rib-extractor.git
cd rib-extractor
```

### 2. Installer les dépendances

```bash
uv sync
```

### 3. Configurer la clé API Gemini

Créez un fichier `.env` à la racine :

```env
GEMINI_API_KEY=AIzaSy...votrecle...
```

> **Obtenir une clé gratuite :** [aistudio.google.com](https://aistudio.google.com) → *Get API key* → *Create API key*  
> Free tier : 1 500 requêtes/jour, sans carte bancaire.

---

## ▶️ Lancement

### Interface principale (recommandée)

```bash
uv run streamlit run src/app/app_v3.py
```

### Script CLI batch

Déposez vos PDFs dans le dossier `rib/` puis :

```bash
uv run python src/rib_extractor.py
```

Les résultats sont exportés dans `rib_infos.csv`.

---

## 📦 Versions archivées

| Fichier | Description | Statut |
|---|---|---|
| `app.py` | Gemini Vision via API REST brute | Archivé — URL modèle obsolète |
| `app_with_ocr.py` | OCR Tesseract local | Archivé — requiert Tesseract + Poppler système |

Ces fichiers sont conservés à titre de référence. Pour les utiliser, `app_with_ocr.py` nécessite :

```bash
# Linux / WSL
sudo apt install tesseract-ocr tesseract-ocr-fra poppler-utils
```

---

## Licence

Ce projet est distribué sous licence MIT. Les contributions sont les bienvenues.

## Auteur

Développé par GASMI Rémy
