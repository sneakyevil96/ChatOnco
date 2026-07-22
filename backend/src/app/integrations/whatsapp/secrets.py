import hmac
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr


class MetaBindingSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: SecretStr | None = None
    app_secret: SecretStr | None = None
    verify_token: SecretStr | None = None


class MetaSecretCatalog:
    """Resolves opaque project bindings to deployment-injected secrets."""

    def __init__(self, bindings: dict[str, MetaBindingSecrets]) -> None:
        self._bindings = bindings

    @classmethod
    def empty(cls) -> "MetaSecretCatalog":
        return cls({})

    @classmethod
    def load(cls, path: Path) -> "MetaSecretCatalog":
        if not path.is_file():
            raise ValueError("WhatsApp secret file does not exist or is not a file")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("WhatsApp secret file must contain a JSON object")
        return cls(
            {
                str(binding): MetaBindingSecrets.model_validate(value)
                for binding, value in raw.items()
            }
        )

    @classmethod
    def load_optional(cls, path: Path | None) -> "MetaSecretCatalog":
        return cls.empty() if path is None else cls.load(path)

    def access_token(self, binding: str) -> str:
        secret = self._bindings.get(binding)
        if secret is None or secret.access_token is None:
            raise ValueError(f"No Meta access token is configured for binding {binding!r}")
        return secret.access_token.get_secret_value()

    def app_secret(self, binding: str) -> str:
        secret = self._bindings.get(binding)
        if secret is None or secret.app_secret is None:
            raise ValueError(f"No Meta app secret is configured for binding {binding!r}")
        return secret.app_secret.get_secret_value()

    def accepts_verify_token(self, token: str) -> bool:
        return any(
            binding.verify_token is not None
            and hmac.compare_digest(binding.verify_token.get_secret_value(), token)
            for binding in self._bindings.values()
        )
