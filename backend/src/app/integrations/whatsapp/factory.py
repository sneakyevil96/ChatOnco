from app.core.project_config import ProjectCatalog
from app.core.settings import Settings
from app.integrations.whatsapp.base import WhatsAppClient
from app.integrations.whatsapp.meta import MetaWhatsAppClient
from app.integrations.whatsapp.mock import MockWhatsAppClient
from app.integrations.whatsapp.secrets import MetaSecretCatalog


def create_whatsapp_client(
    provider: str,
    *,
    settings: Settings | None = None,
    project_catalog: ProjectCatalog | None = None,
    secret_catalog: MetaSecretCatalog | None = None,
) -> WhatsAppClient:
    if provider == "mock":
        return MockWhatsAppClient()
    if provider == "meta":
        if settings is None or project_catalog is None or secret_catalog is None:
            raise ValueError("Meta provider requires settings, projects, and secrets")
        if not settings.meta_graph_api_version:
            raise ValueError("Meta provider requires an explicit Graph API version")
        return MetaWhatsAppClient(
            project_catalog,
            secret_catalog,
            graph_api_version=settings.meta_graph_api_version,
            graph_api_base_url=settings.meta_graph_api_base_url,
            timeout_seconds=settings.meta_request_timeout_seconds,
        )
    raise ValueError(f"Unsupported WhatsApp provider: {provider}")
