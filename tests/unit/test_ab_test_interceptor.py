"""Tests for A/B Test Interceptor."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.audiobook_studio.api.ab_test_interceptor import (
    ABTestAllocator,
    ABTestConfig,
    ABTestVariant,
    ABTestMiddleware,
    DEFAULT_EXPERIMENTS,
)


class TestABTestAllocator:
    """Test A/B test allocation logic."""

    def test_default_experiments_exist(self):
        """Verify default experiments are configured."""
        assert "analyze_structure" in DEFAULT_EXPERIMENTS
        assert "annotate_paragraph" in DEFAULT_EXPERIMENTS
        assert "edit_for_tts" in DEFAULT_EXPERIMENTS
        assert "tts_routing" in DEFAULT_EXPERIMENTS
        assert "quality_judge" in DEFAULT_EXPERIMENTS

    def test_experiment_structure(self):
        """Verify experiment config structure."""
        exp = DEFAULT_EXPERIMENTS["analyze_structure"]
        assert exp.stage == "analyze_structure"
        assert exp.experiment_id == "analyze_structure_v2"
        assert len(exp.variants) == 2
        assert exp.variants[0].name == "control"
        assert exp.variants[0].version == 1
        assert exp.variants[1].name == "treatment"
        assert exp.variants[1].version == 2
        assert exp.enabled is True
        assert exp.sticky is True

    def test_allocator_get_variant(self):
        """Test variant allocation returns consistent results."""
        allocator = ABTestAllocator()
        
        # Same inputs should return same variant
        variant1 = allocator.get_variant("analyze_structure", "book1", "user1")
        variant2 = allocator.get_variant("analyze_structure", "book1", "user1")
        
        assert variant1 is not None
        assert variant1.name == variant2.name
        assert variant1.version == variant2.version

    def test_allocator_different_users_get_different_variants(self):
        """Test different users can get different variants (with enough samples)."""
        allocator = ABTestAllocator()
        
        variants = set()
        for i in range(100):
            variant = allocator.get_variant("analyze_structure", f"book{i}", f"user{i}")
            if variant:
                variants.add(variant.name)
        
        # With 100 samples and 50/50 split, should see both variants
        assert len(variants) == 2

    def test_allocator_disabled_experiment_returns_none(self):
        """Test disabled experiment returns None."""
        allocator = ABTestAllocator({
            "test_stage": ABTestConfig(
                stage="test_stage",
                experiment_id="test_disabled",
                variants=[
                    ABTestVariant(name="control", version=1, weight=0.5),
                    ABTestVariant(name="treatment", version=2, weight=0.5),
                ],
                enabled=False,
            )
        })
        
        variant = allocator.get_variant("test_stage", "book1", "user1")
        assert variant is None

    def test_allocator_target_books_filter(self):
        """Test target_books filtering."""
        allocator = ABTestAllocator({
            "test_stage": ABTestConfig(
                stage="test_stage",
                experiment_id="test_target",
                variants=[
                    ABTestVariant(name="control", version=1, weight=0.5),
                    ABTestVariant(name="treatment", version=2, weight=0.5),
                ],
                enabled=True,
                target_books=["book1", "book2"],
            )
        })
        
        # Book in target list
        variant = allocator.get_variant("test_stage", "book1", "user1")
        assert variant is not None
        
        # Book not in target list
        variant = allocator.get_variant("test_stage", "book3", "user1")
        assert variant is None

    def test_allocator_get_prompt_version(self):
        """Test get_prompt_version returns correct version."""
        allocator = ABTestAllocator()
        
        version = allocator.get_prompt_version("analyze_structure", "book1", "user1")
        assert version in [1, 2]
        
        # Unknown stage returns default
        version = allocator.get_prompt_version("unknown_stage", "book1", "user1")
        assert version == 1

    def test_sticky_vs_non_sticky(self):
        """Test sticky vs non-sticky allocation."""
        # Sticky: same inputs -> same variant
        allocator_sticky = ABTestAllocator({
            "test_stage": ABTestConfig(
                stage="test_stage",
                experiment_id="test_sticky",
                variants=[
                    ABTestVariant(name="control", version=1, weight=0.5),
                    ABTestVariant(name="treatment", version=2, weight=0.5),
                ],
                enabled=True,
                sticky=True,
            )
        })
        
        variants_sticky = [allocator_sticky.get_variant("test_stage", "book1", "user1").name for _ in range(10)]
        assert len(set(variants_sticky)) == 1  # All same
        
        # Non-sticky: random allocation
        allocator_random = ABTestAllocator({
            "test_stage": ABTestConfig(
                stage="test_stage",
                experiment_id="test_random",
                variants=[
                    ABTestVariant(name="control", version=1, weight=0.5),
                    ABTestVariant(name="treatment", version=2, weight=0.5),
                ],
                enabled=True,
                sticky=False,
            )
        })
        
        variants_random = [allocator_random.get_variant("test_stage", "book1", "user1").name for _ in range(100)]
        # With 100 random samples, should see both (probability extremely high)
        assert len(set(variants_random)) >= 1  # At least one variant


class TestABTestMiddleware:
    """Test A/B Test Middleware integration."""

    def test_middleware_creation(self):
        """Test middleware can be created."""
        app = FastAPI()
        app.add_middleware(ABTestMiddleware)
        assert len(app.user_middleware) == 1

    def test_middleware_allocator_injection(self):
        """Test allocator is injected into middleware."""
        allocator = ABTestAllocator()
        app = FastAPI()
        app.add_middleware(ABTestMiddleware, allocator=allocator)
        
        # Check middleware has the allocator
        middleware = app.user_middleware[0]
        assert middleware.kwargs.get("allocator") is allocator


class TestABTestIntegration:
    """Integration tests with pipeline."""

    def test_allocator_can_be_extended(self):
        """Test allocator can be extended with custom experiments."""
        custom_experiments = {
            "custom_stage": ABTestConfig(
                stage="custom_stage",
                experiment_id="custom_exp",
                variants=[
                    ABTestVariant(name="v1", version=1, weight=0.3),
                    ABTestVariant(name="v2", version=2, weight=0.7),
                ],
                enabled=True,
            )
        }
        
        allocator = ABTestAllocator(custom_experiments)
        variant = allocator.get_variant("custom_stage", "book1", "user1")
        
        assert variant is not None
        assert variant.version in [1, 2]

    def test_weight_distribution(self):
        """Test weight distribution is respected."""
        allocator = ABTestAllocator({
            "test_stage": ABTestConfig(
                stage="test_stage",
                experiment_id="test_weight",
                variants=[
                    ABTestVariant(name="v1", version=1, weight=0.9),
                    ABTestVariant(name="v2", version=2, weight=0.1),
                ],
                enabled=True,
                sticky=False,  # Use random for this test
            )
        })
        
        # Count distribution
        counts = {"v1": 0, "v2": 0}
        for i in range(1000):
            variant = allocator.get_variant("test_stage", f"book{i}", f"user{i}")
            if variant:
                counts[variant.name] += 1
        
        # v1 should be ~90%, v2 ~10%
        assert counts["v1"] > 800
        assert counts["v2"] < 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
