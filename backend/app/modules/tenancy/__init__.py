# Tenancy module — dormant substrate for multi-tenant SaaS (Phase 1207).
# All tenant_id columns and tenancy tables are inert in single_tenant mode
# (tenant_id IS NULL everywhere; mode default).  Isolation enforcement is
# Phase 1208 (RLS) and Phase 1209 (per-tenant data schemas).
