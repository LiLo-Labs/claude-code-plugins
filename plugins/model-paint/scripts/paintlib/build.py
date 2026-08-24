"""Build an Orca/Bambu-compatible 3MF from a plain mesh (typically an STL).

STL carries no color information at all, so painting an STL means constructing a
3MF around it first. The mesh is written exactly as loaded: no repair, no
decimation, no re-meshing, no unit rescaling. Whatever the slicer would have
made of the original STL, it makes of this.
"""

import zipfile

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""

MODEL_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">model-paint</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
"""

MODEL_FOOTER = """ </resources>
 <build>
{items}
 </build>
</model>
"""


def _format_float(value):
    # Match the slicers' own habit: enough precision to be lossless for float32
    # STL data, without dumping 17 digits into every vertex.
    text = "%.6f" % value
    text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def model_xml(meshes):
    """Serialize ``[(name, vertices, triangles), ...]`` as a 3dmodel.model."""
    parts = [MODEL_HEADER]
    items = []
    for index, (name, vertices, triangles) in enumerate(meshes, start=1):
        parts.append('  <object id="%d" type="model" name="%s">\n   <mesh>\n    <vertices>\n'
                     % (index, name))
        for x, y, z in vertices:
            parts.append('     <vertex x="%s" y="%s" z="%s"/>\n'
                         % (_format_float(x), _format_float(y), _format_float(z)))
        parts.append("    </vertices>\n    <triangles>\n")
        for v1, v2, v3 in triangles:
            parts.append('     <triangle v1="%d" v2="%d" v3="%d"/>\n' % (v1, v2, v3))
        parts.append("    </triangles>\n   </mesh>\n  </object>\n")
        items.append('  <item objectid="%d" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' % index)
    parts.append(MODEL_FOOTER.format(items="\n".join(items)))
    return "".join(parts)


def model_settings_xml(meshes):
    """Bambu/Orca per-object settings. Filament 1 is the object default."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for index, (name, _vertices, _triangles) in enumerate(meshes, start=1):
        parts.append('  <object id="%d">\n' % index)
        parts.append('    <metadata key="name" value="%s"/>\n' % name)
        parts.append('    <metadata key="extruder" value="1"/>\n')
        parts.append('  </object>\n')
    parts.append("</config>\n")
    return "".join(parts)


def write_3mf(path, meshes):
    """Write a 3MF containing ``meshes`` = ``[(name, vertices, triangles), ...]``."""
    path = str(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("3D/3dmodel.model", model_xml(meshes))
        archive.writestr("Metadata/model_settings.config", model_settings_xml(meshes))
    return path


def from_stl(stl_path, out_path, name=None):
    """Convert an STL (or any trimesh-readable mesh) into an unpainted 3MF."""
    import trimesh

    loaded = trimesh.load(str(stl_path), process=False, force="mesh")
    vertices = [tuple(float(c) for c in row) for row in loaded.vertices]
    triangles = [tuple(int(i) for i in row) for row in loaded.faces]
    label = name or str(stl_path).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return write_3mf(out_path, [(label, vertices, triangles)])
