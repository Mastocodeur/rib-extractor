"""Application settings, loaded from environment variables or .env file."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'application RIB Extractor.

    Toutes les valeurs peuvent être surchargées via variables d'environnement
    ou un fichier .env à la racine du projet.

    La clé API est stockée comme SecretStr : elle n'apparaît jamais en clair
    dans les logs, les repr() ou les traces d'erreur.
    Utiliser .get_secret_value() uniquement là où la valeur brute est nécessaire.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Clé API Google Gemini (stockée comme secret, jamais loggée). "
            "Obtenir gratuitement sur https://aistudio.google.com (1 500 req/jour)."
        ),
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        description="Identifiant du modèle Gemini à utiliser pour l'extraction Vision.",
    )
    texte_min_chars: int = Field(
        default=80,
        ge=1,
        description=(
            "Seuil (en nombre de caractères) pour détecter un PDF natif. "
            "Utilisé uniquement pour la vérification croisée pdfplumber : "
            "si le texte extrait est inférieur à ce seuil, la vérification est ignorée."
        ),
    )
