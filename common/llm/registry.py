from __future__ import annotations

from common import structlog
from common.core.config import ConfigError
from common.llm.base import LLMProvider, PluginManifest

logger = structlog.get_logger(__name__)

_PROVIDER_MODULES = {
    "anthropic": "common.llm.anthropic.register",
    "openai": "common.llm.openai.register",
    "openai-compatible": "common.llm.openai_compatible.register",
    "ollama": "common.llm.ollama.register",
    "groq": "common.llm.groq.register",
    "xai": "common.llm.xai.register",
}


def _get_llm_section(config: dict) -> tuple[dict, dict]:
    """Get LLM providers and default provider from config.

    Supports both old format (config['llm']['providers']) and new format
    (config['providers'] at top level).
    Returns (providers, default_provider).
    """
    if "providers" in config:
        return config.get("providers", {}), config.get("default_provider", "")
    llm_cfg = config.get("llm", {})
    return llm_cfg.get("providers", {}), llm_cfg.get("default_provider", "")


def discover_providers(config: dict) -> dict[str, LLMProvider]:
    """Discover and instantiate all configured LLM providers.

    Reads config["providers"] (or config["llm"]["providers"]) to know which
    providers are configured. Only instantiates providers that appear in the config.
    Returns {provider_name: provider_instance}.

    Does NOT raise if a provider fails to initialize (e.g. missing API key) —
    that is the provider's responsibility to log and set _provider = None.
    Raises ConfigError if config has no providers at all.
    """
    configured_providers, default_provider = _get_llm_section(config)
    if not configured_providers:
        raise ConfigError("No LLM config found. Run: toolsetup")

    providers: dict[str, LLMProvider] = {}

    for name in configured_providers:
        provider_config_dict = configured_providers[name]
        if isinstance(provider_config_dict, dict) and "type" in provider_config_dict:
            type_name = provider_config_dict["type"]
        else:
            type_name = name  # backward compatibility

        module_path = _PROVIDER_MODULES.get(type_name)
        if not module_path:
            logger.warning("unknown_provider", name=name, type=type_name)
            continue
        try:
            import importlib

            module = importlib.import_module(module_path)
            manifest: PluginManifest = module.register(config)
            provider_config = {
                "providers": configured_providers,
                "default_provider": default_provider,
            }
            instance = manifest.provider_class(provider_config, name)
            providers[name] = instance
            logger.debug("provider_registered", name=name, type=type_name)
        except Exception as exc:
            logger.warning("provider_registration_failed", name=name, error=str(exc))

    return providers


def get_default_provider_name(config: dict) -> str:
    """Return the configured default provider name.

    Raises ConfigError if not set.
    """
    _, default_provider = _get_llm_section(config)
    if not default_provider:
        raise ConfigError("No default LLM provider configured. Run: toolsetup")
    return default_provider
