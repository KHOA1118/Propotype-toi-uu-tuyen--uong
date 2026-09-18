"""OSM XML 0.6 -> directed, tagged geographic network. No routing or incidents."""
from collections import Counter
import hashlib
import math
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET


class MapValidationError(ValueError):
    pass


def osm_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise MapValidationError(f"Invalid positive OSM ID for {label}: {value!r}")
    return value  # Strings preserve large OSM IDs exactly in JavaScript.


def finite(value, label, lower, upper):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise MapValidationError(f"Invalid {label}: {value!r}") from error
    if not math.isfinite(number) or not lower <= number <= upper:
        raise MapValidationError(f"Invalid {label}: {value!r}")
    return number


def tags_of(element):
    result = {}
    for tag in element.findall("tag"):
        key, value = tag.get("k"), tag.get("v")
        if not key or value is None or key in result:
            raise MapValidationError(f"Missing or duplicate tag key in {element.tag} {element.get('id')}")
        result[key] = value
    return result


def haversine_meters(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = lat2 - lat1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def direction(tags):
    value = tags.get("oneway", "").strip().lower()
    if value in {"yes", "true", "1"}:
        return ["forward"], "explicit"
    if value == "-1":
        return ["backward"], "explicit"
    if value in {"no", "false", "0"}:
        return ["forward", "backward"], "explicit"
    if value:
        return [], "unresolved"  # reversible/alternating cannot be static arcs
    if tags.get("junction") == "roundabout" or tags.get("highway") == "motorway":
        return ["forward"], "implied"
    return ["forward", "backward"], "default_bidirectional"


def speed_kph(value):
    if value is None:
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(km/h|kph|mph)?\s*", value, re.I)
    if not match:
        return None  # symbolic, conditional or multi-value limits stay unknown
    speed = float(match[1]) * (1.609344 if (match[2] or "").lower() == "mph" else 1)
    return speed if math.isfinite(speed) and speed > 0 else None


def fingerprint(path):
    digest = hashlib.sha256()
    tail = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if b"<!DOCTYPE" in (tail + block).upper() or b"<!ENTITY" in (tail + block).upper():
                raise MapValidationError("DTD/entity declarations are not accepted")
            digest.update(block)
            tail = block[-16:]
    return digest.hexdigest()


def load_osm(path):
    """Fail on bad road geometry; explicitly report incomplete relation members."""
    started = time.perf_counter()
    path = Path(path)
    sha = fingerprint(path)
    all_nodes, all_ways, relations = {}, {}, {}
    source, bounds = {}, None
    try:
        context = ET.iterparse(path, events=("start", "end"))
        _, root = next(context)
        if root.tag != "osm" or root.get("version") != "0.6":
            raise MapValidationError("Expected OSM XML <osm version='0.6'>")
        source = {key: root.get(key) for key in ("version", "generator", "copyright", "attribution", "license") if root.get(key)}
        depth = 1
        for event, element in context:
            if event == "start":
                depth += 1
                continue
            if depth != 2:
                depth -= 1
                continue
            kind = element.tag
            if kind == "bounds":
                bounds = {key: finite(element.get(key), key, -90 if "lat" in key else -180, 90 if "lat" in key else 180) for key in ("minlat", "minlon", "maxlat", "maxlon")}
                if bounds["minlat"] > bounds["maxlat"] or bounds["minlon"] > bounds["maxlon"]:
                    raise MapValidationError("Inverted source bounds")
            elif kind in {"node", "way", "relation"}:
                element_id = osm_id(element.get("id"), kind)
                target = {"node": all_nodes, "way": all_ways, "relation": relations}[kind]
                if element_id in target:
                    raise MapValidationError(f"Duplicate {kind} ID {element_id}")
                tags = tags_of(element)
                if kind == "node":
                    target[element_id] = {"id": element_id, "lat": finite(element.get("lat"), "latitude", -90, 90), "lon": finite(element.get("lon"), "longitude", -180, 180), "tags": tags}
                elif kind == "way":
                    target[element_id] = {"id": element_id, "node_ids": [osm_id(nd.get("ref"), f"way {element_id} reference") for nd in element.findall("nd")], "tags": tags}
                else:
                    members = []
                    for member in element.findall("member"):
                        member_type = member.get("type")
                        if member_type not in {"node", "way", "relation"}:
                            raise MapValidationError(f"Invalid member type in relation {element_id}")
                        members.append({"type": member_type, "ref": osm_id(member.get("ref"), "relation member"), "role": member.get("role", "")})
                    target[element_id] = {"id": element_id, "members": members, "tags": tags}
            element.clear()
            root.remove(element)
            depth -= 1
    except (ET.ParseError, StopIteration) as error:
        raise MapValidationError(f"Malformed OSM XML: {error}") from error
    for way in all_ways.values():
        for ref in way["node_ids"]:
            if ref not in all_nodes:
                raise MapValidationError(f"Way {way['id']} references missing node {ref}")
    missing = []
    for relation in relations.values():
        for member in relation["members"]:
            member["present_in_source"] = member["ref"] in {"node": all_nodes, "way": all_ways, "relation": relations}[member["type"]]
            if not member["present_in_source"]:
                missing.append({"relation_id": relation["id"], **member})

    ways = {key: way for key, way in all_ways.items() if "highway" in way["tags"]}
    nodes, edges, exclusions = {}, {}, []
    segment_count = 0
    for way_id, way in ways.items():
        refs, tags = way["node_ids"], way["tags"]
        if len(refs) < 2:
            raise MapValidationError(f"Highway way {way_id} has fewer than two nodes")
        nodes.update({ref: all_nodes[ref] for ref in refs})
        dirs, direction_source = direction(tags)
        way["directions"] = dirs
        way["direction_source"] = direction_source
        if tags.get("area") == "yes" or not dirs:
            reason = "area_not_linear_road" if tags.get("area") == "yes" else "unresolved_direction"
            way["edge_exclusion_reason"] = reason
            exclusions.append({"way_id": way_id, "reason": reason})
            continue
        for index, (a, b) in enumerate(zip(refs, refs[1:])):
            segment_count += 1
            distance = haversine_meters(nodes[a], nodes[b])
            for travel_direction in dirs:
                edge_id = f"osm:{way_id}:{index}:{'f' if travel_direction == 'forward' else 'r'}"
                if edge_id in edges:
                    raise MapValidationError(f"Duplicate edge ID {edge_id}")
                raw_speed = tags.get(f"maxspeed:{travel_direction}", tags.get("maxspeed"))
                speed = speed_kph(raw_speed)
                travel_time = distance / (speed / 3.6) if speed is not None else None
                if not math.isfinite(distance) or distance < 0 or (travel_time is not None and (not math.isfinite(travel_time) or travel_time < 0)):
                    raise MapValidationError(f"Invalid distance/travel time for edge {edge_id}")
                edges[edge_id] = {
                    "id": edge_id, "from_node": a if travel_direction == "forward" else b,
                    "to_node": b if travel_direction == "forward" else a,
                    "distance": distance, "travel_time": travel_time,
                    "base_travel_time": travel_time, "status": "unassessed",
                    "way_id": way_id, "segment_index": index, "direction": travel_direction,
                    "direction_source": direction_source, "speed_limit_kph": speed,
                    "travel_time_source": "maxspeed_estimate" if speed is not None else "unknown",
                }
    if not edges:
        raise MapValidationError("No linear highway edges found")
    for relation in relations.values():
        for member in relation["members"]:
            member["present_in_network"] = member["ref"] in {"node": nodes, "way": ways, "relation": relations}[member["type"]]
    if path.stat().st_size == 0 or fingerprint(path) != sha:
        raise MapValidationError("Source changed while loading")
    road_bounds = {"minlat": min(n["lat"] for n in nodes.values()), "maxlat": max(n["lat"] for n in nodes.values()), "minlon": min(n["lon"] for n in nodes.values()), "maxlon": max(n["lon"] for n in nodes.values())}
    stats = {
        "raw_nodes": len(all_nodes), "raw_ways": len(all_ways), "raw_relations": len(relations),
        "highway_ways": len(ways), "network_nodes": len(nodes), "physical_segments": segment_count,
        "directed_edges": len(edges), "excluded_ways": len(exclusions),
        "edges_with_time_estimate": sum(e["travel_time"] is not None for e in edges.values()),
        "edges_with_unknown_time": sum(e["travel_time"] is None for e in edges.values()),
        "zero_length_edges": sum(e["distance"] == 0 for e in edges.values()),
        "missing_way_node_references": 0, "missing_relation_members": len(missing),
        "duplicate_primitive_ids": 0, "duplicate_edge_ids": 0,
        "highway_types": dict(Counter(w["tags"]["highway"] for w in ways.values())),
        "direction_sources": dict(Counter(w["direction_source"] for w in ways.values())),
        "turn_restrictions": sum(r["tags"].get("type") == "restriction" for r in relations.values()),
        "incomplete_turn_restrictions": sum(r["tags"].get("type") == "restriction" and any(not m["present_in_source"] for m in r["members"]) for r in relations.values()),
        "edge_connected_nodes": len({ref for e in edges.values() for ref in (e["from_node"], e["to_node"])}),
    }
    return {
        "metadata": {"schema_version": "1.0", "crs": "EPSG:4326", "units": {"distance": "meters", "travel_time": "seconds", "speed": "km/h"},
                     "source": {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha, **source},
                     "source_bounds": bounds, "network_bounds": road_bounds, "stats": stats,
                     "policies": {"road_scope": "all highway-tagged ways; areas preserved but not converted to edges", "status": "unassessed; not a claim of legal vehicle access", "travel_time": "speed-limit estimate when numeric maxspeed exists, otherwise null", "routing_ready": False, "restriction_relations_enforced": False},
                     "load_seconds": time.perf_counter() - started},
        "nodes": nodes, "edges": edges, "ways": ways, "relations": relations,
        "validation": {"missing_relation_members": missing, "excluded_ways": exclusions},
    }


def to_geojson(network):
    """One feature per physical segment, not per directional edge. [lon, lat]."""
    grouped = {}
    for edge in network["edges"].values():
        grouped.setdefault((edge["way_id"], edge["segment_index"]), []).append(edge)
    features = []
    for (way_id, index), arcs in grouped.items():
        way = network["ways"][way_id]
        refs = way["node_ids"][index:index + 2]
        features.append({"type": "Feature", "id": f"osm:{way_id}:{index}",
                         "geometry": {"type": "LineString", "coordinates": [[network["nodes"][ref]["lon"], network["nodes"][ref]["lat"]] for ref in refs]},
                         "properties": {"way_id": way_id, "segment_index": index, "edge_ids": [e["id"] for e in arcs], "directions": [e["direction"] for e in arcs], "distance": arcs[0]["distance"], "highway": way["tags"]["highway"], "name": way["tags"].get("name"), "status": "unassessed"}})
    return {"type": "FeatureCollection", "features": features, "source_sha256": network["metadata"]["source"]["sha256"]}
