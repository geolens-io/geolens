---
name: geolens-plugin-audit
description: Audit the GeoLens map plugin platform. Use when the user asks for /plugin-audit, plugin building, map plugins, plugin registry, PluginHost, PluginPanel, measurement plugin, legend plugin, enabled_plugins, plugin persistence, or plugin docs/test coverage.
metadata:
  short-description: GeoLens plugin platform audit
---

<codex_skill_adapter>
Codex skills-first mode:
- Invoke with `$geolens-plugin-audit` or when a user asks for `/plugin-audit`.
- Treat all text after the skill name or slash command as `{{ARGS}}`.
- Read `.claude/commands/plugin-audit.md` before acting; it is the canonical detailed playbook.
- Map `$ARGUMENTS` in that file to `{{ARGS}}`.
- Use Codex subagents only if the user explicitly asked for agents, delegation, or parallel agent work.
- When the Claude command says to use a Read tool, use targeted Codex file reads.
</codex_skill_adapter>

<objective>
Audit GeoLens map plugins end to end: registry contract, host rendering, plugin lifecycle, built-in behavior, admin enablement, saved-map persistence, docs, i18n, and tests.
</objective>

<process>
1. Resolve `{{ARGS}}` to a plugin audit scope such as `registry`, `host`, `lifecycle`, `builtins`, `admin`, `ux`, `docs`, or `tests`.
2. Run the command intake around `frontend/src/components/map-plugins/**`, builder integration, settings, map persistence, locale files, docs, and existing command references.
3. Treat `frontend/src/components/map-plugins/register-plugins.ts` as the current source of truth for built-in plugin IDs unless the registry implementation has changed.
4. Distinguish plugin-platform issues from wider builder issues; route non-plugin findings to `/builder-audit`, `/admin-audit`, `/design-audit`, or `/test-audit` as appropriate.
5. If fixing, keep changes local to the plugin platform or the narrow integration point, and rerun focused frontend tests.
</process>

<output>
Return findings with plugin area labels, severity, `file:line` evidence, affected user/admin flow, and concrete fixes. Include tested flows and skipped areas.
</output>
