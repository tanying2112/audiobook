"""FastAPI router for dynamic provider and model management."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.config_loader import ProviderConfig, ProviderType, StageName
from ..llm.router import get_llm_router, reload_llm_router
from ..models.provider import Model, Provider
from ..schemas.provider import (
    ModelCreate,
    ModelListResponse,
    ModelOut,
    ModelUpdate,
    ProviderCreate,
    ProviderListResponse,
    ProviderOut,
    ProviderUpdate,
)
from .dependencies import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["provider-management"])


# ── DB -> LLM router hot-reload bridge (S2.1) ───────────────────────────────
#
# The DB-backed provider table is the admin source of truth for dynamically
# added suppliers. After any mutation we push the enabled providers into the
# live LLMRouter singleton so routing picks them up without a restart.

# Map freeform DB provider_type strings to the typed ProviderType enum.
# Unknown gateways fall back to OPENAI (most are OpenAI-compatible HTTP APIs).
_DB_TYPE_TO_ENUM = {
    "openai": ProviderType.OPENAI,
    "anthropic": ProviderType.ANTHROPIC,
    "groq": ProviderType.GROQ,
    "deepseek": ProviderType.DEEPSEEK,
    "openrouter": ProviderType.OPENROUTER,
    "ollama": ProviderType.OLLAMA,
    "gemini": ProviderType.GEMINI,
    "cerebras": ProviderType.CEREBRAS,
    "alibaba": ProviderType.ALIBABA,
    "zhipu": ProviderType.ZHIPU,
    "siliconcloud": ProviderType.SILICONCLOUD,
    "mistral": ProviderType.MISTRAL,
    "volcengine": ProviderType.VOLCENGINE,
    "tencent": ProviderType.TENCENT,
    "cohere": ProviderType.COHERE,
    "together": ProviderType.TOGETHER,
    "huggingface": ProviderType.HUGGINGFACE,
    "baidu_qianfan": ProviderType.BAIDU_QIANFAN,
    "cloudflare": ProviderType.CLOUDFLARE,
    "github": ProviderType.GITHUB,
    "duck2api": ProviderType.DUCK2API,
    # Common gateway aliases seen in this project's data
    "nvidia_nemotron": ProviderType.OPENAI,
    "fcc_gateway": ProviderType.OPENAI,
    "fcc": ProviderType.OPENAI,
    "nemotron": ProviderType.OPENAI,
}

# A managed provider is made available to every pipeline stage by default.
_ALL_STAGES = list(StageName)


def _db_provider_to_config(provider: Provider) -> ProviderConfig:
    """Map a DB ``Provider`` row (+ its enabled models) to a ``ProviderConfig``.

    Best-effort: unknown provider_type -> OPENAI; missing default_model falls
    back to the first enabled model's model_id; API key is exported to a
    synthetic env var so the router's env-based key lookup works.
    """
    ptype = _DB_TYPE_TO_ENUM.get(provider.provider_type, ProviderType.OPENAI)
    enabled_models = [m for m in provider.models if getattr(m, "is_enabled", True)]
    model_id = provider.default_model
    if not model_id and enabled_models:
        model_id = enabled_models[0].model_id or enabled_models[0].name
    model_id = model_id or provider.name

    # Export the literal DB key into the environment so the router (which reads
    # api_key_env) can pick it up. Keyed by provider name to avoid collisions.
    env_var = f"PROVIDER_DB_{provider.name.upper().replace('-', '_')}_KEY"
    if provider.api_key:
        import os

        os.environ[env_var] = provider.api_key

    return ProviderConfig(
        name=provider.name,
        provider=ptype,
        model=model_id,
        api_key_env=env_var if provider.api_key else None,
        base_url=provider.api_base or None,
        priority=provider.sort_priority or 100,
        stages=_ALL_STAGES,
        enabled=bool(provider.is_enabled),
    )


async def build_provider_configs_from_db(db: AsyncSession) -> List[ProviderConfig]:
    """Query enabled providers (with models) and map to ProviderConfig list."""
    result = await db.execute(select(Provider).where(Provider.is_enabled.is_(True)))
    providers = result.scalars().all()
    return [_db_provider_to_config(p) for p in providers]


async def sync_router_from_db(db: AsyncSession) -> None:
    """Push current DB providers into the live LLM router (hot-reload).

    Awaited from async API endpoints; never raises, so a provider DB write
    always succeeds even if the router sync has issues.
    """
    try:
        configs = await build_provider_configs_from_db(db)
        router_instance = get_llm_router()
        router_instance.apply_provider_configs(configs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[provider_router] router sync skipped: %s", exc)


def trigger_router_reload() -> None:
    """Best-effort YAML-based hot-reload of the singleton router."""
    try:
        reload_llm_router()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[provider_router] router reload skipped: %s", exc)


# ── Provider CRUD ─────────────────────────────────────────────────────────


@router.post("/", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    db: AsyncSession = Depends(get_async_db),
) -> Provider:
    """Create a new provider."""
    from ..models.provider import Provider as ProviderModel

    # Check if provider with same name exists
    result = await db.execute(select(ProviderModel).where(ProviderModel.name == payload.name))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider '{payload.name}' already exists",
        )

    provider = ProviderModel(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        provider_type=payload.provider_type,
        api_base=payload.api_base,
        api_key=payload.api_key,
        auth_type=payload.auth_type,
        default_model=payload.default_model,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        is_enabled=payload.is_enabled,
        sort_priority=payload.sort_priority,
    )

    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.get("/", response_model=ProviderListResponse)
async def list_providers(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_db),
) -> ProviderListResponse:
    """List all providers with optional filtering."""
    from ..models.provider import Provider as ProviderModel

    result = await db.execute(
        select(ProviderModel).order_by(ProviderModel.sort_priority.asc(), ProviderModel.name.asc())
    )
    providers = result.scalars().all()

    # Count models for each provider
    provider_outs = []
    for p in providers:
        model_result = await db.execute(select(Model).where(Model.provider_id == p.id, Model.is_enabled.is_(True)))
        models = model_result.scalars().all()
        provider_out = ProviderOut(
            **{c: getattr(p, c) for c in ProviderOut.model_fields},
            model_count=len(models),
        )
        provider_outs.append(provider_out)

    return ProviderListResponse(
        providers=provider_outs,
        total=len(provider_outs),
        page=(skip // 100) + 1,
        page_size=limit,
    )


@router.get("/{provider_id}", response_model=ProviderOut)
async def get_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> Provider:
    """Get a specific provider by ID."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider with id {provider_id} not found",
        )
    return provider


@router.put("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    db: AsyncSession = Depends(get_async_db),
) -> Provider:
    """Update a provider."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider with id {provider_id} not found",
        )

    # Update fields
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.commit()
    await db.refresh(provider)
    await sync_router_from_db(db)
    return provider


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete a provider (and its models)."""
    from ..models.provider import Model as ModelModel

    # Check if provider has models - if so, soft delete by disabling
    result = await db.execute(select(ModelModel).where(ModelModel.provider_id == provider_id))
    models = result.scalars().all()

    if models:
        # Soft delete: disable the provider instead
        provider_result = await db.execute(select(Provider).where(Provider.id == provider_id))
        provider = provider_result.scalar_one()
        provider.is_enabled = False
        await db.commit()
    else:
        # Hard delete
        await db.execute(delete(Provider).where(Provider.id == provider_id))
        await db.commit()

    return None


# ── Model CRUD ────────────────────────────────────────────────────────────


@router.post("/{provider_id}/models/", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    provider_id: int,
    payload: ModelCreate,
    db: AsyncSession = Depends(get_async_db),
) -> ModelOut:
    """Create a new model under a provider."""
    from ..models.provider import Model as ModelModel
    from ..models.provider import Provider as ProviderModel

    # Check if provider exists
    prov_result = await db.execute(select(ProviderModel).where(ProviderModel.id == provider_id))
    provider = prov_result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider with id {provider_id} not found",
        )

    # Check if model with same name exists under this provider
    result = await db.execute(
        select(ModelModel).where(ModelModel.provider_id == provider_id, ModelModel.name == payload.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Model '{payload.name}' already exists under provider {provider_id}",
        )

    model = ModelModel(
        name=payload.name,
        provider_id=provider_id,
        model_id=payload.model_id,
        version=payload.version,
        context_window=payload.context_window,
        instructions=payload.instructions,
        parameters=payload.parameters,
        is_enabled=payload.is_enabled,
        sort_priority=payload.sort_priority,
    )

    db.add(model)
    await db.commit()
    await db.refresh(model)
    await sync_router_from_db(db)

    # Return with provider name nested
    model_out = ModelOut(
        **{c: getattr(model, c) for c in ModelOut.model_fields},
        provider_name=provider.name,
    )
    return model_out


@router.get("/{provider_id}/models/", response_model=ModelListResponse)
async def list_models(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> ModelListResponse:
    """List all models under a specific provider."""
    from ..models.provider import Model as ModelModel
    from ..models.provider import Provider as ProviderModel

    # Check provider exists
    prov_result = await db.execute(select(ProviderModel).where(ProviderModel.id == provider_id))
    provider = prov_result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider with id {provider_id} not found",
        )

    result = await db.execute(
        select(ModelModel).where(ModelModel.provider_id == provider_id, ModelModel.is_enabled.is_(True))
    )
    models = result.scalars().all()

    # Build response with provider name
    model_outs = []
    for m in models:
        model_out = ModelOut(
            **{c: getattr(m, c) for c in ModelOut.model_fields},
            provider_name=provider.name,
        )
        model_outs.append(model_out)

    return ModelListResponse(
        models=model_outs,
        total=len(model_outs),
        provider_name=provider.name,
    )


@router.get("/{provider_id}/models/{model_id}", response_model=ModelOut)
async def get_model(
    provider_id: int,
    model_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> ModelOut:
    """Get a specific model by ID under a provider."""
    from ..models.provider import Model as ModelModel
    from ..models.provider import Provider as ProviderModel

    result = await db.execute(
        select(ModelModel).where(ModelModel.provider_id == provider_id, ModelModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id {model_id} not found under provider {provider_id}",
        )

    prov_result = await db.execute(select(ProviderModel).where(ProviderModel.id == provider_id))
    provider = prov_result.scalar_one_or_none()

    model_out = ModelOut(
        **{c: getattr(model, c) for c in ModelOut.model_fields},
        provider_name=provider.name if provider else None,
    )
    return model_out


@router.put("/{provider_id}/models/{model_id}", response_model=ModelOut)
async def update_model(
    provider_id: int,
    model_id: int,
    payload: ModelUpdate,
    db: AsyncSession = Depends(get_async_db),
) -> ModelOut:
    """Update a model."""
    from ..models.provider import Model as ModelModel
    from ..models.provider import Provider as ProviderModel

    result = await db.execute(
        select(ModelModel).where(ModelModel.provider_id == provider_id, ModelModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id {model_id} not found under provider {provider_id}",
        )

    # Check if new name conflicts with existing model under same provider
    if payload.name and payload.name != model.name:
        conflict_result = await db.execute(
            select(ModelModel).where(
                ModelModel.provider_id == provider_id, ModelModel.name == payload.name, ModelModel.id != model_id
            )
        )
        if conflict_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Model '{payload.name}' already exists under provider {provider_id}",
            )

    # Update fields
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model, field, value)

    await db.commit()
    await db.refresh(model)
    await sync_router_from_db(db)

    # Return with provider name
    prov_result = await db.execute(select(ProviderModel).where(ProviderModel.id == provider_id))
    provider = prov_result.scalar_one_or_none()

    model_out = ModelOut(
        **{c: getattr(model, c) for c in ModelOut.model_fields},
        provider_name=provider.name if provider else None,
    )
    return model_out


@router.delete("/{provider_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    provider_id: int,
    model_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete a model (soft delete by disabling)."""
    from ..models.provider import Model as ModelModel

    result = await db.execute(
        select(ModelModel).where(ModelModel.provider_id == provider_id, ModelModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if not model:
        return None  # Already doesn't exist

    # Soft delete: disable the model
    model.is_enabled = False
    await db.commit()
    await sync_router_from_db(db)
    return None


# ── Hot-reload endpoint (S2.1) ────────────────────────────────────────────────


@router.post("/reload", status_code=status.HTTP_200_OK, tags=["provider-management"])
async def reload_providers(
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Hot-reload provider configuration into the live LLM router.

    Two sources are reconciled:
    1. DB-backed providers (the dynamic supplier table) are pushed into the
       router via ``sync_router_from_db``.
    2. The YAML config is re-read via ``reload_llm_router`` (env-based keys).

    The router merges both sets; either can change routing without a restart.
    Failures are reported but never raise, so the endpoint is safe to call.
    """
    result: dict[str, Any] = {"db_sync": "ok", "yaml_reload": "ok", "errors": []}
    try:
        await sync_router_from_db(db)
    except Exception as exc:  # pragma: no cover - defensive
        result["db_sync"] = "failed"
        result["errors"].append(f"db_sync: {exc}")
    try:
        trigger_router_reload()
    except Exception as exc:  # pragma: no cover - defensive
        result["yaml_reload"] = "failed"
        result["errors"].append(f"yaml_reload: {exc}")
    return result
