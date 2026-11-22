"""Data models for RIB extraction."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RibData(BaseModel):
    """Données extraites d'un Relevé d'Identité Bancaire (RIB) français."""

    model_config = ConfigDict(str_strip_whitespace=True)

    titulaire: str = Field(
        default="",
        description="Nom complet du titulaire du compte bancaire (personne physique ou morale).",
        examples=["DUPONT Jean", "SARL ACME CONSULTING"],
    )
    code_banque: str = Field(
        default="",
        description="Code établissement bancaire, exactement 5 chiffres.",
        pattern=r"^\d{5}$|^$",
        examples=["30006", "13106", "17589"],
    )
    code_guichet: str = Field(
        default="",
        description="Code guichet de l'agence, exactement 5 chiffres.",
        pattern=r"^\d{5}$|^$",
        examples=["00001", "12345"],
    )
    numero_compte: str = Field(
        default="",
        description="Numéro de compte bancaire, jusqu'à 11 caractères alphanumériques.",
        max_length=11,
        examples=["00012345678", "0001234567A"],
    )
    cle_rib: str = Field(
        default="",
        description="Clé de contrôle RIB (2 chiffres, valeur calculée modulo 97, entre 01 et 97).",
        pattern=r"^\d{2}$|^$",
        examples=["06", "97", "12"],
    )
    iban: str = Field(
        default="",
        description=(
            "IBAN français formaté en groupes de 4 caractères séparés par des espaces. "
            "Format : FR + 2 chiffres clé + 23 caractères alphanumériques = 27 chars compacts."
        ),
        examples=["FR76 3000 6000 0100 0012 3456 789"],
    )
    bic: str = Field(
        default="",
        description=(
            "Code BIC/SWIFT de l'établissement bancaire. "
            "Format : 4 lettres (banque) + 2 lettres pays (FR) + 2 alnum (place) + 3 optionnels (agence). "
            "Longueur : 8 ou 11 caractères."
        ),
        pattern=r"^[A-Z]{4}FR[A-Z0-9]{2}([A-Z0-9]{3})?$|^$",
        examples=["BNPAFRPP", "CMCIFRPPXXX", "CEPAFRPP"],
    )
    domiciliation: str = Field(
        default="",
        description="Adresse complète de l'agence bancaire domiciliataire (peut être multi-lignes).",
        examples=["75 RUE DE LA PAIX 75002 PARIS"],
    )

    @field_validator("iban", mode="before")
    @classmethod
    def normalise_iban(cls, v: object) -> str:
        """Normalise un IBAN : supprime le bruit, met en majuscule, regroupe par 4."""
        if not v:
            return ""
        compact = re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()
        if not compact:
            return ""
        return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))

    @field_validator("bic", mode="before")
    @classmethod
    def normalise_bic(cls, v: object) -> str:
        """Normalise un BIC : supprime les caractères parasites, tronque à 8 ou 11 chars."""
        if not v:
            return ""
        bic = re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()
        if len(bic) >= 11:
            return bic[:11]
        if len(bic) >= 8:
            return bic[:8]
        return ""

    @property
    def iban_compact(self) -> str:
        """IBAN sans espaces, pour usage informatique (paiements, API bancaires)."""
        return self.iban.replace(" ", "")

    def _label(self, field: str) -> str:
        """Retourne la valeur du champ ou 'MANQUANT' si vide."""
        v = getattr(self, field, "")
        return v if v else "MANQUANT"

    def to_export_row(self, filename: str, methode: str, erreur: str = "", verification: str = "") -> dict:
        """Sérialise le modèle en dict plat pour l'export CSV / Excel / Parquet."""
        return {
            "Fichier": filename,
            "Méthode": methode,
            "Titulaire": self._label("titulaire"),
            "Code Banque": self._label("code_banque"),
            "Code Guichet": self._label("code_guichet"),
            "N° de compte": self._label("numero_compte"),
            "Clé RIB": self._label("cle_rib"),
            "IBAN": self._label("iban"),
            "IBAN (compact)": self.iban_compact or "MANQUANT",
            "BIC / SWIFT": self._label("bic"),
            "Domiciliation": self._label("domiciliation"),
            "Vérification": verification,
            "Erreur": erreur,
        }
