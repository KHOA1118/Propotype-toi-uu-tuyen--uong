"""Optional OSM backdrop. Never imported by routing, costs or the optimizer."""
import xml.etree.ElementTree as ET
import math


def load_context(source):
    nodes={};ways=[]
    with open(source, 'rb') as stream:
        for _,element in ET.iterparse(stream,events=('end',)):
            if element.tag=='node':
                try:
                    lat,lon=float(element.attrib['lat']),float(element.attrib['lon'])
                    if math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180:
                        nodes[element.attrib['id']]=[lon,lat]
                except (KeyError,ValueError):pass
                element.clear()
            elif element.tag=='way':
                tags={t.get('k'):t.get('v') for t in element.findall('tag')}
                water=tags.get('natural')=='water' or 'water' in tags or tags.get('waterway') in ('river','canal')
                green=tags.get('leisure')=='park' or tags.get('landuse') in ('forest','grass','recreation_ground') or tags.get('natural')=='wood'
                if water or green:ways.append((element.get('id'),[n.get('ref') for n in element.findall('nd')],'water' if water else 'green',tags))
                element.clear()
            elif element.tag=='relation':element.clear()
    features=[]
    for wid,refs,kind,tags in ways:
        if len(refs)<2 or any(n not in nodes for n in refs):continue
        closed=len(refs)>=4 and refs[0]==refs[-1]
        if not closed and tags.get('waterway') not in ('river','canal'):continue
        coords=[nodes[n] for n in refs]
        features.append({'type':'Feature','id':'way:'+wid,'properties':{'kind':kind,'name':tags.get('name','')},'geometry':{'type':'Polygon' if closed else 'LineString','coordinates':[coords] if closed else coords}})
    return {'type':'FeatureCollection','features':features,'display_only':True}
