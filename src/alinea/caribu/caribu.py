# -*- python -*-
#
#       Copyright 2015 INRIA - CIRAD - INRA
#
#       Distributed under the Cecill-C License.
#       See accompanying file LICENSE.txt or copy at
#           http://www.cecill.info/licences/Licence_CeCILL-C_V1-en.html
#
#       WebSite : https://github.com/openalea-incubator/caribu
#
# ==============================================================================
"""
Core pythonic functions to call caribu shell.
"""

from alinea.caribu.label import Label
from alinea.caribu.caribu_shell import Caribu

green_leaf_PAR = (0.06, 0.07)
green_stem_PAR = (0.13,)
soil_reflectance_PAR = 0.2

default_light = (1, (0, 0, -1))


def pattern_string(pattern_tuple):
    """ format pattern as caribu file string content
    """
    x1, y1, x2, y2 = pattern_tuple
    pattern_tuple = [(min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
    pattern = '\n'.join([' '.join(map(str, pattern_tuple[0])),
                         ' '.join(map(str, pattern_tuple[1])), ' '])
    return pattern


def light_string(lights):
    """ format lights as caribu light file string content
    """

    def _as_string(light):
        e, p = light
        return ' '.join(map(str, [e] + list(p))) + '\n'

    lines = map(_as_string, lights)

    return ''.join(lines)


def opt_string(species, soil_reflectance=-1):
    """ format species as caribu opt file string content
    """

    n = len(species)
    o_string = 'n %s\n' % n
    o_string += "s d %s\n" % soil_reflectance
    species_sorted_keys = sorted(species.keys())
    for key in species_sorted_keys:
        po = species[key]
        if sum(po) <= 0:
            raise ValueError('Caribu do not accept black body material (absorptance=1)')
        if len(po) == 1:
            o_string += 'e d %s   d -1 -1  d -1 -1\n' % po
        elif len(po) == 2:
            o_string += 'e d -1   d %s %s' % po + ' d %s %s\n' % po
        else:
            o_string += 'e d -1   d %s %s  d %s %s\n' % po

    return o_string


def encode_labels(materials, species, x_mat=False):
    mapping = {v: k for k, v in species.iteritems()}

    def _label(material):
        lab = Label()
        lab.plant_id = 1
        lab.optical_id = mapping[material]
        if x_mat:
            transparent = len(material[0]) > 1
        else:
            transparent = len(material) > 1
        if transparent:
            lab.leaf_id = 1
        return str(lab)

    return [_label(m) for m in materials]


def opt_string_and_labels(materials, soil_reflectance=-1):
    """ format materials as caribu opt file string content and encode label
    """

    species = {i + 1: po for i, po in enumerate(list(set(materials)))}
    o_string = opt_string(species, soil_reflectance)
    labels = encode_labels(materials, species)

    return o_string, labels


def x_opt_strings_and_labels(x_materials, x_soil_reflectance):
    """ format multispectral materials as caribu opt file strings content
    """

    x_opts = zip(*x_materials.values())
    x_species = {i + 1: po for i, po in enumerate(list(set(x_opts)))}

    labels = encode_labels(x_opts, x_species, x_mat=True)

    opt_strings = {}
    for i, k in enumerate(x_materials.keys()):
        species = {k: v[i] for k, v in x_species.iteritems()}
        opt_strings[k] = opt_string(species, x_soil_reflectance[k])

    return opt_strings, labels


def triangles_string(triangles, labels):
    """ format triangles and associated labels as caribu canopy string content
    """
    if len(triangles) != len(labels):
        raise ValueError('The number of triangles and materials should match')

    def _can_string(triangle, label):
        s = "p 1 %s 3" % str(label)
        for pt in triangle:
            s += " %.6f %.6f %.6f" % pt
        return s + '\n'

    lines = [_can_string(t, l) for t, l in zip(triangles, labels)]

    return ''.join(lines)


def _absorptance(material):
    if len(material) <= 2:
        return 1 - sum(material)
    else:
        return 1 - sum(material) / 2.


def get_incident(eabs, materials):
    """ estimate incident light using absorbed light and materials
    
        For asymetric materials, return a mean estimate
    """
    # check for integrity of caribu output
    if len(eabs) != len(materials):
        raise ValueError("The number of caribu outputs doesn't match the number of inputs")
    alpha = (_absorptance(m) for m in materials)

    return [float(e) / a if a != 0 else e for e, a in zip(eabs, alpha)]


def raycasting(triangles, materials, lights=(default_light,), domain=None,
               screen_size=1536):
    """Compute monochrome illumination of triangles using caribu raycasting mode.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        materials: (list of tuple) a list of materials defining optical properties of triangles
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode the reflectance of an opaque material
                    A 2-tuple encode the reflectance and transmittance of a symmetric translucent material
                    A 4-tuple encode the reflectance and transmittance
                    of the upper and lower side of an asymmetric translucent material
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining ligh sources
                By default a normalised zenithal light is used.
                Energy is light flux passing through a unit area (scene unit) horizontal plane.
        domain: (tuple of floats) 2D Coordinates of the domain bounding the scene for its replication.
                 (xmin, ymin, xmax, ymax) scene is not bounded along z axis
                 if None (default), scene is not repeated
        screen_size: (int) buffer size for projection images (pixels)

    Returns:
        (dict of str:property) properties computed:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debugging)
          - area (float): the individual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle.
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
    """

    o_string, labels = opt_string_and_labels(materials)
    can_string = triangles_string(triangles, labels)
    sky_string = light_string(lights)

    if domain is None:
        infinite = False
        pattern_str = None
    else:
        infinite = True
        pattern_str = pattern_string(domain)

    algo = Caribu(canfile=can_string,
                  skyfile=sky_string,
                  optfiles=o_string,
                  patternfile=pattern_str,
                  direct=True,
                  infinitise=infinite,
                  projection_image_size=screen_size,
                  resdir=None, resfile=None)
    algo.run()
    out = algo.nrj['band0']['data']
    out['Ei'] = get_incident(out['Eabs'], materials)

    return out


def x_raycasting(triangles, x_materials, lights=(default_light,), domain=None,
                 screen_size=1536):
    """Compute monochrome illumination of triangles using caribu raycasting mode.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        x_materials: (dict of list of tuple) a {band_name: [materials]} dict defining optical properties of triangles
                    for different band/wavelength
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode an opaque material characterised by its reflectance
                    A 2-tuple encode a symmetric translucent material defined by a reflectance and a transmittance
                    A 4-tuple encode an asymmetric translucent material defined the reflectance and transmittance
                    of the upper and lower side respectively
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining ligh sources
                By default a normalised zenithal light is used.
                Energy is light flux passing through a unit area (scene unit) horizontal plane.
        domain: (tuple of floats) 2D Coordinates of the domain bounding the scene for its replication.
                 (xmin, ymin, xmax, ymax) scene is not bounded along z axis
                 if None (default), scene is not repeated
        screen_size: (int) buffer size for projection images (pixels)

    Returns:
        a ({band_name: {property_name:property_values} } dict of dict) with  properties:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debuging)
          - area (float): the individual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
    """

    x_out = {}
    band, materials = x_materials.popitem()
    out = raycasting(triangles, materials, lights=lights, domain=domain,
                     screen_size=screen_size)
    x_out[band] = out

    for band in x_materials:
        x_out[band] = {}
        absorptance = (_absorptance(m) for m in x_materials[band])
        for var in out:
            if var != 'Eabs':
                x_out[band][var] = out[var]
            else:
                x_out[band]['Eabs'] = [a * e for a, e in zip(absorptance, out['Ei'])]

    return x_out


def radiosity(triangles, materials, lights=(default_light,), screen_size=1536, disc_resolution=52, form_factor=False):
    """Compute monochromatic illumination of triangles using radiosity method.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        materials: (list of tuple) a list of materials defining optical properties of triangles
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode an opaque material characterised by its reflectance
                    A 2-tuple encode a symmetric translucent material defined by a reflectance and a transmittance
                    A 4-tuple encode an asymmetric translucent material defined the reflectance and transmittance
                    of the upper and lower side respectively
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining ligh sources
                By default a normalised zenital light is used.
                Energy is ligth flux passing throuh a unit area (scene unit) horizontal plane.
        screen_size: (int) buffer size for projection images (pixels)
        disc_resolution (int) : size (pixel of the projection disc resolution
        form_factor: (bool) should form factor be returned

    Returns:
        (dict of str:property) properties computed:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debuging)
          - area (float): the individual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
          - form_factor (array): the form factor matrix (only if form_factor is true)
    """

    if len(triangles) <= 1:
        raise ValueError('Radiosity method needs at least two primitives')

    o_string, labels = opt_string_and_labels(materials)
    can_string = triangles_string(triangles, labels)
    sky_string = light_string(lights)

    algo = Caribu(canfile=can_string,
                  skyfile=sky_string,
                  optfiles=o_string,
                  patternfile=None,
                  direct=False,
                  infinitise=False,
                  sphere_diameter=-1,
                  projection_image_size=screen_size,
                  form_factor_data=form_factor,
                  projection_disc_resolution=disc_resolution,
                  resdir=None, resfile=None)
    algo.run()
    out = algo.nrj['band0']['data']
    out['Ei'] = get_incident(out['Eabs'], materials)
    if form_factor:
        out['form_factor'] = algo.FFdat

    return out


def x_radiosity(triangles, x_materials, lights=(default_light,), screen_size=1536):
    """Compute multi-chromatic illumination of triangles using radiosity method.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        x_materials: (dict of list of tuple) a {band_name: [materials]} dict defining optical properties of triangles
                    for different band/wavelength
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode an opaque material characterised by its reflectance
                    A 2-tuple encode a symmetric translucent material defined by a reflectance and a transmittance
                    A 4-tuple encode an asymmetric translucent material defined the reflectance and transmittance
                    of the upper and lower side respectively
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining ligh sources
                By default a normalised zenital light is used.
                Energy is ligth flux passing throuh a unit area (scene unit) horizontal plane.
        screen_size: (int) buffer size for projection images (pixels)

    Returns:
        a {band_name: {property_name:property_values} } dict of dict) with  properties:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debuging)
          - area (float): the individual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
    """

    if len(triangles) <= 1:
        raise ValueError('Radiosity method needs at least two primitives')

    no_soil = {band:-1 for band in x_materials}
    opt_strings, labels = x_opt_strings_and_labels(x_materials, no_soil)
    can_string = triangles_string(triangles, labels)
    sky_string = light_string(lights)

    caribu = Caribu(canfile=can_string,
                    skyfile=sky_string,
                    optfiles=opt_strings.values(),
                    optnames=opt_strings.keys(),
                    patternfile=None,
                    direct=False,
                    infinitise=False,
                    sphere_diameter=-1,
                    projection_image_size=screen_size,
                    resdir=None, resfile=None)
    caribu.run()
    out = {k: v['data'] for k, v in caribu.nrj.iteritems()}
    for band in out:
        out[band]['Ei'] = get_incident(out[band]['Eabs'], x_materials[band])

    return out


def mixed_radiosity(triangles, materials, lights, domain, soil_reflectance,
                    diameter, layers, height, screen_size=1536, disc_resolution=52, form_factor=False, debug=False):
    """Compute monochrome illumination of triangles using mixed-radiosity model.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        materials: (list of tuple) a list of materials defining optical properties of triangles
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode an opaque material characterised by its reflectance
                    A 2-tuple encode a symmetric translucent material defined by a reflectance and a transmittance
                    A 4-tuple encode an asymmetric translucent material defined the reflectance and transmittance
                    of the upper and lower side respectively
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining ligh sources
                Energy is ligth flux passing throuh a unit area (scene unit) horizontal plane.
        domain: (tuple of floats) 2D Coordinates of the domain bounding the scene for its replication.
                 (xmin, ymin, xmax, ymax) scene is not bounded along z axis
        soil_reflectance: (float) the reflectance of the soil
        diameter: diameter (scene unit) of the sphere defining the close neighbourhood for local radiosity.
        layers: vertical subdivisions of scene used for approximation of far contrbution
        height: upper limit of canopy layers (scene unit)
        screen_size: (int) buffer size for projection images (pixels)
        disc_resolution (int) : size (pixel of the projection disc resolution
        form_factor: (bool) should form factor be returned
        debug: (bool) Whether Caribu should be called in debug mode

    Returns:
        (dict of str:property) properties computed:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debuging)
          - area (float): the indiviual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
    """

    if len(triangles) <= 1:
        raise ValueError('Radiosity method needs at least two primitives')

    o_string, labels = opt_string_and_labels(materials, soil_reflectance)
    can_string = triangles_string(triangles, labels)
    sky_string = light_string(lights)
    pattern_str = pattern_string(domain)

    algo = Caribu(canfile=can_string,
                  skyfile=sky_string,
                  optfiles=o_string,
                  patternfile=pattern_str,
                  direct=False,
                  infinitise=True,
                  nb_layers=layers,
                  can_height=height,
                  sphere_diameter=diameter,
                  projection_image_size=screen_size,
                  form_factor_data=form_factor,
                  projection_disc_resolution=disc_resolution,
                  resdir=None, resfile=None, debug=debug)
    algo.run()
    out = algo.nrj['band0']['data']
    out['Ei'] = get_incident(out['Eabs'], materials)

    if form_factor:
        out['form_factor'] = algo.FFdat

    return out


def x_mixed_radiosity(triangles, materials, lights, domain, soil_reflectance,
                      diameter, layers, height, screen_size=1536, disc_resolution=52):
    """Compute multi-chromatic illumination of triangles using mixed-radiosity model.

    Args:
        triangles: (list of list of tuples) a list of triangles, each being defined
                    by an ordered triplet of 3-tuple points coordinates.
        materials: (dict of list of tuple) a {band_name: [materials]} dict defining optical properties of triangles
                    for different band/wavelength
                    A material is a 1-, 2- or 4-tuple depending on its optical behavior.
                    A 1-tuple encode an opaque material characterised by its reflectance
                    A 2-tuple encode a symmetric translucent material defined by a reflectance and a transmittance
                    A 4-tuple encode an asymmetric translucent material defined the reflectance and transmittance
                    of the upper and lower side respectively
        lights: (list of tuples) a list of (Energy, (vx, vy, vz)) tuples defining light sources
                Energy is light flux passing through a unit area (scene unit) horizontal plane.
        domain: (tuple of floats) 2D Coordinates of the domain bounding the scene for its replication.
                 (xmin, ymin, xmax, ymax) scene is not bounded along z axis
        soil_reflectance: (dict of float) a {band_name: reflectance} dict for the reflectances of the soil
        diameter: diameter (scene unit) of the sphere defining the close neighbourhood for local radiosity.
        layers: vertical subdivisions of scene used for approximation of far contribution
        height: upper limit of canopy layers (scene unit)
        screen_size: (int) buffer size for projection images (pixels)


    Returns:
       a ({band_name: {property_name:property_values} } dict of dict) with  properties:
          - index(int) : the indices of the input triangles present in outputs ?
          - label(str) : the internal barcode (canlabel) used by caribu (for debugging)
          - area (float): the individual areas of triangles
          - Eabs (float): the surfacic density of energy absorbed by the triangles (absorbed_energy / area)
          - Ei (float): the surfacic density of energy incoming on the triangles
          - Ei_inf (float): the surfacic density of energy incoming on the inferior face of the triangle
          - Ei_sup (float): the surfacic density of energy incoming on the superior face of the triangle
    """

    if len(triangles) <= 1:
        raise ValueError('Radiosity method needs at least two primitives')

    opt_strings, labels = x_opt_strings_and_labels(materials, soil_reflectance)
    can_string = triangles_string(triangles, labels)
    sky_string = light_string(lights)
    pattern_str = pattern_string(domain)

    caribu = Caribu(canfile=can_string,
                    skyfile=sky_string,
                    optfiles=opt_strings.values(),
                    optnames=opt_strings.keys(),
                    patternfile=pattern_str,
                    direct=False,
                    infinitise=True,
                    nb_layers=layers,
                    can_height=height,
                    sphere_diameter=diameter,
                    projection_image_size=screen_size,
                    projection_disc_resolution=disc_resolution,
                    resdir=None, resfile=None)
    caribu.run()
    out = {k: v['data'] for k, v in caribu.nrj.iteritems()}
    for band in out:
        out[band]['Ei'] = get_incident(out[band]['Eabs'], materials[band])

    return out
