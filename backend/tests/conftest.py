"""Shared fixtures. Nothing here changes what a test sees except state that would otherwise
leak between tests."""
import pytest


@pytest.fixture(autouse=True)
def _clear_brain_headline_cache():
    """The Aira Brain headline is cached per tenant for a minute in-process; tests reuse the
    same tenant ids with different data, so each test starts and ends with an empty cache."""
    from app.services.brain import headline

    headline.clear_cache()
    yield
    headline.clear_cache()


@pytest.fixture(autouse=True)
def _no_live_astro_settings(monkeypatch):
    """"Is this tenant connected to AstroTamil?" is a settings read, which would reach the real
    database from any test that runs the deal flow. Default every test to "not connected"; a test
    about the connection patches astro_bridge.get_setting itself, after this runs."""
    from app.services import astro_bridge

    monkeypatch.setattr(astro_bridge, "get_setting", lambda key, fallback=None, tenant_id=None: fallback)


def fake_embedding(text: str) -> list[float]:
    """A deterministic 768-dim bag-of-words vector: texts sharing words point the same way."""
    import hashlib
    vec = [0.0] * 768
    for word in text.casefold().replace("|", " ").replace(":", " ").split():
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 768] += 1.0
    return vec


@pytest.fixture(autouse=True)
def _no_live_memory_embeddings(monkeypatch):
    """Companion memory search embeds text with the tenant's Gemini/Jina key. Tests never call out:
    embed() gives fake_embedding vectors (a test about embedding failures patches it again)."""
    from app.companion import memory_embed

    async def embed(texts, kind, tenant_id, model=None, retries=True):
        return [fake_embedding(t) for t in texts]
    monkeypatch.setattr(memory_embed, "embed", embed)


@pytest.fixture(autouse=True)
def _no_shared_rewrite(monkeypatch):
    """A reply starts one small rewrite call that both searches share (engine._shared_rewrite). Most
    tests script the LLM answers one by one and are not about that call, so it is off by default; the
    tests about it (test_companion_memory_router.py) switch the real one back on."""
    from app.companion import engine

    monkeypatch.setattr(engine, "_shared_rewrite", lambda *a, **k: None)
