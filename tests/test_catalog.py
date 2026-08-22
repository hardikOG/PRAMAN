"""Catalog invariants required by Phase 3's gate and later phases (the red
team's cart-substitution and prompt-injection attack classes, Phase 8)."""

from __future__ import annotations

from apps.mcp_storefront.catalog import CATALOG, get_product, search_catalog


def test_catalog_has_forty_products() -> None:
    assert len(CATALOG) == 40


def test_catalog_spans_four_categories() -> None:
    assert {p.category for p in CATALOG} == {
        "footwear.running",
        "footwear.casual",
        "apparel.outerwear",
        "accessories.bags",
    }


def test_all_skus_are_unique() -> None:
    skus = [p.sku for p in CATALOG]
    assert len(skus) == len(set(skus))


def test_size_confusable_pair_exists() -> None:
    a, b = get_product("NR-A9"), get_product("NR-A11")
    assert a is not None and b is not None
    assert a.name == b.name
    assert a.attributes["size"] != b.attributes["size"]
    assert a.attributes["colour"] == b.attributes["colour"]


def test_colour_confusable_pair_exists() -> None:
    a, b = get_product("NR-A9"), get_product("NR-W9")
    assert a is not None and b is not None
    assert a.name == b.name
    assert a.attributes["colour"] != b.attributes["colour"]
    assert a.attributes["size"] == b.attributes["size"]


def test_spec_confusable_pair_exists() -> None:
    a, b = get_product("TRK-GTX"), get_product("TRK-STD")
    assert a is not None and b is not None
    assert a.attributes["waterproof"] != b.attributes["waterproof"]
    assert a.price_paise != b.price_paise


def test_two_products_carry_injected_descriptions() -> None:
    injected = [
        p
        for p in CATALOG
        if "SYSTEM" in p.description.upper() or "automatically" in p.description
    ]
    assert len(injected) == 2
    assert {p.sku for p in injected} == {"SP-BLK", "INJ-GAITER"}


def test_search_by_category() -> None:
    results = search_catalog(category="accessories.bags")
    assert len(results) == 6
    assert all(p.category == "accessories.bags" for p in results)


def test_search_by_query_matches_name_or_description() -> None:
    results = search_catalog(query="waterproof")
    skus = {p.sku for p in results}
    assert "TRK-GTX" in skus
    assert "RAIN-M" in skus


def test_search_by_max_price() -> None:
    results = search_catalog(max_price_paise=100_000)
    assert all(p.price_paise <= 100_000 for p in results)
    assert len(results) > 0


def test_search_filters_are_anded() -> None:
    results = search_catalog(category="footwear.running", max_price_paise=250_000)
    assert all(p.category == "footwear.running" and p.price_paise <= 250_000 for p in results)


def test_get_product_returns_none_for_unknown_sku() -> None:
    assert get_product("NOT-A-REAL-SKU") is None
