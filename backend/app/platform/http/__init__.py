"""Cross-cutting HTTP mechanics shared by catalog and processing routes.

Like ``platform/security.py``, this is infrastructure rather than a product
domain: ``modules/catalog/`` and ``processing/`` both serve byte ranges off
stored objects and must agree on what a ``Range`` header means, and neither may
import the other.
"""
