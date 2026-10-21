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

Dataset reads already go through the sanctioned guards (`check_dataset_access`
for one item, `apply_visibility_filter` for lists), and both honour grants.
Maps don't: they check visibility by hand in several places and need their
own guard and grant storage.

Access has to change the moment a grant or a membership does. Every such
change, widening or narrowing:

- bumps the affected items' publication version, as an ownership transfer
  does, because signed tile URLs authorize before the visibility check;
- runs the derived-dataset audience check before it commits, so a derived
  dataset never gains a reader who can't read its sources.

Narrowing also runs the shared-map guard, as a visibility change does today.
Sharing with groups changes visibility through the same path as any other
visibility change, so a public map that becomes restricted loses its share
and embed tokens. Layer data stays behind each dataset's own guard, so a new
member of a group that a map is shared with sees only the layers they can
read.

The change adds `restricted` to the published map visibility values, and older
generated clients reject unknown values. Clients opt in with an
`X-GeoLens-Map-Visibility: restricted` request header, negotiated the way
`X-GeoLens-Auth-Mode` is. Every endpoint that returns a map honours it and
sends `Vary: X-GeoLens-Map-Visibility`, so a cache never hands one form to the
other client, and the API's CORS allow-list carries it for split-origin
deployments. The frontend, the CLI, the MCP server and the SDKs released with
groups send the header.

For one minor release, a request without the header sees restricted maps as
private, and a write without it that sends `private` for a restricted map
leaves the map restricted, since that client can't tell the two apart. After
that release every client sees `restricted`.

No GeoLens surface writes role grants, so rows exist only where someone
inserted them directly. Those rows keep authorizing as they do today, so an
upgrade changes no one's access, and nothing creates new ones. They are the
one exception to restricted meaning owner, admins and group members.

Group grants change what an extension filling the `permission` slot has to
answer, even where no method signature changes. The groups release therefore
bumps `EXTENSION_API_VERSION`, and the paid permission extension ships its
matching release with it. An extension for the `permission` slot that declares
an older version, or no version at all, refuses to load instead of ignoring
group grants.
