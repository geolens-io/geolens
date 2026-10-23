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
maps can be shared with one or more groups. A private item shared with groups
becomes `restricted`, visible to its owner, admins and the members of those
groups; an internal or public item keeps its wider audience. Sharing grants
name groups, and roles stay permission tiers. Maps gain `restricted`.

- Owners share with groups they belong to; admins share with any group.
- Only the owner and admins see which groups an item is shared with. Group
  names never appear in Records, STAC or DCAT output.
- An owner who leaves a group keeps their items shared with it. Deleting a
  group removes its grants, so its members lose any access that came only
  through it. A dataset shared only with that group stays restricted and is
  visible to its owner and admins. A restricted map left with no group
  becomes private, since a restricted map needs a group.
- Sharing a map lists the layers the group can't see and offers to share the
  owner's datasets too. Nothing is shared without that confirmation.
- An ArcGIS migration run by an admin creates a GeoLens group for each mapped
  portal group and adds the members who resolve to GeoLens users. Its report
  lists members who don't resolve yet, and a rerun adds them once they do. A
  rerun also removes the members it added who have since left the portal
  group, and leaves members added in GeoLens alone.

In Community, groups are managed inside GeoLens. Filling groups from an
identity provider's groups claim belongs with the existing paid identity
provider role mapping.

Out of scope: groups whose members edit each other's items, group managers,
invitations and join requests, and content owned by a group.

## Consequences

Dataset reads already go through the sanctioned guards, which honour
grants. Maps check visibility by hand in several places and need their own
guard and grant storage.

Access changes the moment a grant or a membership does, in either direction.
Each change keeps derived datasets and shared maps consistent with their
audiences, as a visibility change does today. Sharing with groups is a
visibility change, with everything that implies for share and embed tokens.

Adding `restricted` to map visibility changes the REST contract. Older
generated clients reject unknown values. So for one minor release, clients
that haven't opted in see restricted maps as private and can't strip a map's
groups by accident.

Existing role grants keep working, and nothing creates new ones.

Group grants change what the permission extension contract means. The groups
release therefore bumps `EXTENSION_API_VERSION` and ships alongside the paid
permission extension, and an extension that doesn't declare the new version
doesn't load.

The implementation rules are in #3262.
