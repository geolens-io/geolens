"""Cross-cutting HTTP mechanics shared by catalog and processing routes.

Lives here, not under a product domain, because ``modules/catalog/`` and
``processing/`` both need it and neither may import the other.
"""
