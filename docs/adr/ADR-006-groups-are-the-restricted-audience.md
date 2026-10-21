# ADR-006: Groups are the audience for restricted visibility

**Status:** accepted. **Scope:** how datasets and maps are shared with a set
of users narrower than everyone who can sign in.

## Context

Datasets have four visibility levels: private, internal, restricted and
public. Maps have three, without restricted. A dataset's `restricted` existed
with grants keyed on role, but nothing wrote those grants, and a role is a
permission tier (admin, editor or viewer). A role grant can say "every
editor". It can't say "the Planning team".

ArcGIS organizations share mostly through groups. If an ArcGIS migration maps a
group-only item to private plus a collection, the group's members lose
access at cutover. Mapping it to internal shares it with everyone instead.

## Decision

A group is a named set of users, created and filled by admins. Datasets and
maps can be shared with one or more groups. Sharing makes them `restricted`,
visible to their owner, admins and the members of those groups. Sharing
grants name groups, and roles stay permission tiers. Maps gain `restricted`.

- Owners share with groups they belong to; admins share with any group.
- Only the owner and admins see which groups an item is shared with. Group
  names never appear in Records, STAC or DCAT output.
- An owner who leaves a group keeps their items shared with it. Deleting a
  group removes its grants and changes no item's visibility. An item shared
  only with that group is then visible to its owner and admins.
- Sharing a map lists the layers the group can't see and offers to share the
  owner's datasets too. Nothing is shared without that confirmation.

In Community, groups are managed inside GeoLens. Filling groups from an
identity provider's groups claim belongs with the existing paid identity
provider role mapping.

Out of scope: groups whose members edit each other's items, group managers,
invitations and join requests, and content owned by a group.

## Consequences

Dataset reads already go through the sanctioned guards (`check_dataset_access`
for one item, `apply_visibility_filter` for lists), and both honour grants.
Maps don't: they check visibility by hand in several places and need their
own guard and grant storage.

Access has to change the moment a grant or a membership does. Signed tile URLs
authorize before the visibility check, so every grant or membership change
bumps the affected items' publication version, as an ownership transfer does.
Narrowing an audience runs the same derived-dataset audience check and
shared-map guard that a visibility change runs today.

The change adds `restricted` to the published map visibility values, and older
generated clients reject unknown values. For one minor release, clients that
don't opt in see restricted maps as private.

No GeoLens surface writes role grants, so rows exist only where someone
inserted them directly. Those rows keep authorizing as they do today, so an
upgrade changes no one's access, and nothing creates new ones. They are the
one exception to restricted meaning owner, admins and group members.

The Enterprise permission overlay mirrors the grant check, so it ships a
release alongside. `EXTENSION_API_VERSION` moves only if a Protocol member
changes, for example a required map access method.
