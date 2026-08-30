import unittest

from scripts.validate_product_capability_catalog import validate


class ProductCapabilityCatalogTests(unittest.TestCase):
    def test_product_capability_catalog_matches_product_and_mcp_surfaces(self) -> None:
        validate()
