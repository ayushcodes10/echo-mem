"""echo-memory unmerge: take back an alias a node should never have absorbed.

A confirmed `resolved_to` does two things, and the second is easy to miss. It
points this episode's facts at the named node, and it appends the mention to
that node's aliases - so the node now answers to both names. That is what makes
a misdirected resolution a merge rather than a misfiled fact: two distinct
entities become one node, which is criterion 6's third bar word for word.

Both of this store's confirmed bad merges are still live for exactly that
reason. On 2026-09-02 the misdirected edges were found and deleted, and the
aliases were not, so 'node_embedding table' has answered to 'Eigon billing
profile' and 'AGE graphid column type' to 'Eigon GST tax rule' ever since.
_exact_match checks aliases, so every later mention of those names has been one
retired node away from resolving onto an embedding table's lesson.

Deleting the edges was the visible half of the cleanup and doing it by hand is
why the other half was missed. This is the other half, as a command, so the
next person does not have to know that aliases exist to finish the job.
"""

import json

from echo_memory.infra.db import GRAPH_NAME as GRAPH


class UnmergeError(Exception):
    pass


def foreign_aliases(conn, group_id: str) -> list[dict]:
    """Nodes carrying an alias that is another node's name.

    The signature of an absorbed entity: the same string exists in this scope
    both as a node in its own right and as somebody else's alias. That is not
    proof - a genuine duplicate pair can look the same on the way to being
    merged properly - which is why this lists and does not act.
    """
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}})
            RETURN id(n), n.name, n.aliases
        $$, %s) AS (node_id agtype, name agtype, aliases agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()

    nodes = []
    for node_id, name, aliases in rows:
        parsed = json.loads(str(aliases)) if aliases is not None else []
        nodes.append((str(node_id), str(name).strip('"'), [str(a) for a in parsed or []]))

    names = {name.lower(): node_id for node_id, name, _ in nodes}
    found = []
    for node_id, name, aliases in nodes:
        for alias in aliases:
            owner = names.get(alias.lower())
            # An alias equal to the node's own name is how a node records
            # itself; only an alias owned by a DIFFERENT node is a merge.
            if owner is not None and owner != node_id:
                found.append({
                    "node_id": node_id, "name": name,
                    "alias": alias, "alias_owner_id": owner,
                })
    return sorted(found, key=lambda f: f["name"])


def unmerge(conn, group_id: str, session_id: str, node_id: str, alias: str) -> dict:
    """Remove one alias from one node, and say so in the audit log.

    Audited as `entity_resolved` because that is the mutation being undone and
    the log's job is to let someone reconstruct how an entity's identity got to
    where it is. A repair that leaves no trace is how the first half of this
    cleanup came to look complete.
    """
    try:
        wanted = int(node_id)
    except (TypeError, ValueError) as e:
        raise UnmergeError(f"{node_id!r} is not a node id") from e

    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND n.group_id = $gid
            RETURN n.name, n.aliases
        $$, %s) AS (name agtype, aliases agtype)""",
        (json.dumps({"nid": wanted, "gid": group_id}),),
    ).fetchone()
    if row is None:
        raise UnmergeError(f"node {node_id} is not a node in this scope")

    name = str(row[0]).strip('"')
    aliases = [str(a) for a in (json.loads(str(row[1])) if row[1] is not None else [])]
    remaining = [a for a in aliases if a.lower() != alias.lower()]
    if len(remaining) == len(aliases):
        raise UnmergeError(f"node {node_id} ({name}) has no alias {alias!r}")
    if alias.lower() == name.lower():
        # Removing a node's own name from its aliases would leave it unable to
        # match itself, which is a different and worse kind of broken.
        raise UnmergeError(f"{alias!r} is node {node_id}'s own name, not an absorbed alias")

    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND n.group_id = $gid
            SET n.aliases = $aliases RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"nid": wanted, "gid": group_id, "aliases": remaining}),),
    ).fetchall()

    conn.execute(
        """INSERT INTO public.audit_entry
               (group_id, session_id, mutation_type, affected_node_id, summary,
                resolution_detail)
           VALUES (%s, %s, 'entity_resolved', %s::text::graphid, %s, %s)""",
        (
            group_id, session_id, node_id,
            f"unmerged alias {alias!r} from {name!r}",
            f"alias {alias!r} removed: it names a different entity in this scope",
        ),
    )
    return {"node_id": node_id, "name": name, "alias": alias, "aliases_left": remaining}


def render_foreign_aliases(scope: str, found: list[dict]) -> str:
    if not found:
        return f"No node in {scope} answers to another node's name.\n"

    lines = [f"Nodes in {scope} carrying another node's name as an alias:", ""]
    for f in found:
        lines.append(
            f"  {f['name']} [{f['node_id']}]  answers to  {f['alias']!r}  "
            f"which is node {f['alias_owner_id']}"
        )
    lines += [
        "",
        "Each of these is two entities sharing one node. _exact_match checks",
        "aliases, so a mention of the alias can resolve onto the wrong node.",
        "Confirm each one is wrong before undoing it - a genuine duplicate pair",
        "on its way to being merged properly looks the same from here:",
        f"  echo-memory --scope {scope} unmerge --node <id> --alias <name>",
    ]
    return "\n".join(lines) + "\n"


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)
    if not (args.node and args.alias):
        print(render_foreign_aliases(args.scope, foreign_aliases(conn, group_id)), end="")
        return 0 if args.list_aliases else 1
    try:
        result = unmerge(conn, group_id, args.session_id or "cli", args.node, args.alias)
    except UnmergeError as e:
        print(f"error: {e}")
        return 1
    print(
        f"Removed alias {result['alias']!r} from {result['name']!r} "
        f"({len(result['aliases_left'])} alias(es) left)."
    )
    return 0
