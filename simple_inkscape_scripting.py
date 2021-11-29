#! /usr/bin/env python

'''
Copyright (C) 2021 Scott Pakin, scott-ink@pakin.org

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

'''

import inkex
import PIL.Image
import base64
import io
import os
import sys

# The following imports are provided for user convenience.
from math import *
from random import *


# ----------------------------------------------------------------------

# The following definitions are utilized by the user convenience
# functions.

# Define a prefix for all IDs we assign.  This contains randomness so
# running the same script repeatedly will be unlikely to produce
# conflicting IDs.
_id_prefix = 'simp-ink-scr-%d-' % randint(100000, 999999)

# Keep track of the next ID to append to _id_prefix.
_next_obj_id = 1

# Store all SimpleObjects the user creates in _simple_objs.
_simple_objs = []

# Store the user-specified default style in _default_style.
_default_style = {}

# Most shapes use this as their default style.
_common_shape_style = {'stroke': 'black',
                       'fill': 'none'}

# Store the default transform in _default_transform.
_default_transform = None

# Store the SVG definitions in _svg_defs.
_svg_defs = None


def unique_id():
    'Return a unique ID.'
    global _id_prefix, _next_obj_id
    tag = '%s%d' % (_id_prefix, _next_obj_id)
    _next_obj_id += 1
    return tag


class SimpleObject(object):
    'Encapsulate an Inkscape object and additional metadata.'

    def __init__(self, obj, transform, conn_avoid, shape_style, obj_style):
        'Wrap an Inkscape object within a SimpleObject.'
        # Combine the current and default transforms.
        ts = []
        if transform is not None and transform != '':
            ts.append(transform)
        if _default_transform is not None and _default_transform != '':
            ts.append(_default_transform)
        if ts != []:
            obj.transform = ' '.join(ts)

        # Optionally indicate that connectors are to avoid this object.
        if conn_avoid:
            obj.set('inkscape:connector-avoid', 'true')

        # Combine the current and default styles.
        ext_style = self._construct_style(shape_style, obj_style)
        if ext_style != '':
            obj.style = ext_style

        # Assign the object a unique ID.
        obj.set_id(unique_id())

        # Store the modified Inkscape object.
        self._inkscape_obj = obj
        _simple_objs.append(self)

    def __str__(self):
        '''Return the object as a string of the form "url(#id)".  This
        enables the object to be used as a value in style key=value
        arguments such as shape_inside.'''
        return 'url(#%s)' % self._inkscape_obj.get_id()

    def _construct_style(self, shape_style, new_style):
        '''Combine a shape default style, a global default style, and an
        object-specific style and return the result as a string.'''
        # Start with the default style for the shape type.
        style = shape_style.copy()

        # Update the style according to the current global default style.
        style.update(_default_style)

        # Update the style based on the object-specific style.
        for k, v in new_style.items():
            k = k.replace('_', '-')
            if v is None:
                style[k] = None
            else:
                style[k] = str(v)

        # Remove all keys whose value is None.
        style = {k: v for k, v in style.items() if v is not None}

        # Concatenate the style into a string.
        return ';'.join(['%s:%s' % kv for kv in style.items()])

    def _get_bbox_center(self):
        "Return the center of an object's bounding box."
        bbox = self._inkscape_obj.bounding_box()
        return (bbox.center_x, bbox.center_y)

    def bounding_box(self):
        "Return the object's bounding box as an inkex.transforms.BoundingBox."
        return self._inkscape_obj.bounding_box()


class SimpleGroup(SimpleObject):
    'Represent a group of objects.'

    def __init__(self, obj, transform, conn_avoid, shape_style, obj_style):
        super().__init__(obj, transform, conn_avoid, shape_style, obj_style)
        self._children = []

    def __len__(self):
        return len(self._children)

    def __getitem__(self, idx):
        return self._children[idx]

    def __iter__(self):
        yield from self._children

    def add(self, obj):
        'Add a SimpleObject to the group.'
        # Ensure the addition is legitimate.
        global _simple_objs
        if not isinstance(obj, SimpleObject):
            inkex.utils.errormsg(_('Only Simple Inkscape Scripting objects '
                                   'can be added to a group'))
            return
        if obj not in _simple_objs:
            inkex.utils.errormsg(_('Only objects not already in a group '
                                   'can be added to a group'))
            return

        # Remove the object from the top-level set of objects.
        _simple_objs = [o for o in _simple_objs if o is not obj]

        # Add the object to both the SimpleGroup and the SVG group.
        self._children.append(obj)
        self._inkscape_obj.add(obj._inkscape_obj)


class SimpleFilter(object):
    'Represent an SVG filter effect.'

    def __init__(self, defs, name=None, pt1=None, pt2=None,
                 filter_units=None, primitive_units=None, **style):
        self.filt = defs.add(inkex.Filter())
        if name is not None and name != '':
            self.filt.set('inkscape:label', name)
        if pt1 is not None or pt2 is not None:
            x0 = float(pt1[0] or 0)
            y0 = float(pt1[1] or 0)
            x1 = float(pt2[0] or 1)
            y1 = float(pt2[1] or 1)
            self.filt.set('x', x0)
            self.filt.set('y', y0)
            self.filt.set('width', x1 - x0)
            self.filt.set('height', y1 - y0)
        if filter_units is not None:
            self.filt.set('filterUnits', filter_units)
        if primitive_units is not None:
            self.filt.set('primitiveUnits', primitive_units)
        style_str = str(inkex.Style(**style))
        if style_str != '':
            self.filt.set('style', style_str)

    def __str__(self):
        return 'url(#%s)' % self.filt.get_id()

    class SimpleFilterPrimitive(object):
        'Represent one component of an SVG filter effect.'

        def __init__(self, filt, ftype, **kw_args):
            # Assign a random ID for the default result.
            all_args = {'result': unique_id()}

            # Make "src1" and "src2" smart aliases for "in" and "in2".
            s2i = {'src1': 'in', 'src2': 'in2'}
            for k, v in kw_args.items():
                k = k.replace('_', '-')
                if k in s2i:
                    # src1 and src2 accept either SimpleFilterPrimitive
                    # objects -- extracting their "result" string -- or
                    # ordinary strings.
                    if isinstance(v, self.__class__):
                        v = v.prim.get('result')
                    all_args[s2i[k]] = v
                elif type(v) == str:
                    # Strings are used unmodified.
                    all_args[k] = v
                else:
                    try:
                        # Sequences (other than strings, which are
                        # sequences of characters) are converted to a
                        # string of space-separated values.
                        all_args[k] = ' '.join([str(e) for e in v])
                    except TypeError:
                        # Scalars are converted to strings.
                        all_args[k] = str(v)

            # Add a primitive to the filter.
            self.prim = filt.add_primitive(ftype, **all_args)

    def add(self, ftype, **kw_args):
        'Add a primitive to a filter and return an object representation.'
        return self.SimpleFilterPrimitive(self.filt, 'fe' + ftype, **kw_args)


class SimpleLinearGradient(object):
    'Represent an SVG linear gradient pattern.'

    # Map Inkscape repetition names to SVG names.
    repeat_to_spread = {'none':      'pad',
                        'reflected': 'reflect',
                        'direct':    'repeat'}

    def __init__(self, defs, pt1=None, pt2=None, repeat=None,
                 gradient_units=None, template=None, transform=None,
                 **style):
        grad = inkex.LinearGradient()
        if pt1 is not None:
            grad.set('x1', pt1[0])
            grad.set('y1', pt1[1])
        if pt2 is not None:
            grad.set('x2', pt2[0])
            grad.set('y2', pt2[1])
        if repeat is not None:
            try:
                spread = self.repeat_to_spread[repeat]
            except KeyError:
                spread = repeat
            grad.set('spreadMethod', spread)
        if gradient_units is not None:
            grad.set('gradientUnits', gradientUnits)
        if template is not None:
            tmpl_name = str(template)[5:-1]  # Strip the 'url(#' and the ')'.
            grad.set('href', '#%s' % tmpl_name)        # No Inkscape support
            grad.set('xlink:href', '#%s' % tmpl_name)  # Deprecated by SVG
        if transform is not None:
            grad.set('gradientTransform', transform)
        style_str = str(inkex.Style(**style))
        if style_str != '':
            grad.set('style', style_str)
        self.grad = defs.add(grad)

    def __str__(self):
        return 'url(#%s)' % self.grad.get_id()

    def add_stop(self, ofs, **style):
        'Add a stop to a linear gradient.'
        stop = inkex.Stop()
        stop.offset = ofs
        style_str = str(inkex.Style(**style))
        if style_str != '':
            stop.set('style', style_str)
        self.grad.append(stop)


# ----------------------------------------------------------------------

# The following functions represent the Simple Inkscape Scripting API
# and are intended to be called by user code.

def style(**kwargs):
    'Modify the default style.'
    global _default_style
    for k, v in kwargs.items():
        k = k.replace('_', '-')
        if v is None:
            _default_style[k] = None
        else:
            _default_style[k] = str(v)


def transform(t):
    'Set the default transform.'
    global _default_transform
    _default_transform = t.strip()


def circle(center, r, transform=None, conn_avoid=False, **style):
    'Draw a circle.'
    obj = inkex.Circle(cx=str(center[0]), cy=str(center[1]), r=str(r))
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def ellipse(center, rx, ry, transform=None, conn_avoid=False, **style):
    'Draw an ellipse.'
    obj = inkex.Ellipse(cx=str(center[0]), cy=str(center[1]),
                        rx=str(rx), ry=str(ry))
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def rect(pt1, pt2, round=None, transform=None, conn_avoid=False, **style):
    'Draw a rectangle.'
    # Convert pt1 and pt2 to an upper-left starting point and
    # rectangle dimensions.
    x0 = min(pt1[0], pt2[0])
    y0 = min(pt1[1], pt2[1])
    x1 = max(pt1[0], pt2[0])
    y1 = max(pt1[1], pt2[1])
    wd = x1 - x0
    ht = y1 - y0

    # Draw the rectangle.
    obj = inkex.Rectangle(x=str(x0), y=str(y0),
                          width=str(wd), height=str(ht))

    # Optionally round the corners.
    if round is not None:
        try:
            rx, ry = round
        except TypeError:
            rx, ry = round, round
        obj.set('rx', str(rx))
        obj.set('ry', str(ry))
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def line(pt1, pt2, transform=None, conn_avoid=False, **style):
    'Draw a line.'
    obj = inkex.Line(x1=str(pt1[0]), y1=str(pt1[1]),
                     x2=str(pt2[0]), y2=str(pt2[1]))
    shape_style = {'stroke': 'black'}  # No need for fill='none' here.
    return SimpleObject(obj, transform, conn_avoid, shape_style, style)


def polyline(*coords, transform=None, conn_avoid=False, **style):
    'Draw a polyline.'
    if len(coords) < 2:
        inkex.utils.errormsg(_('A polyline must contain at least two points.'))
        return
    pts = ' '.join(["%s,%s" % (str(x), str(y)) for x, y in coords])
    obj = inkex.Polyline(points=pts)
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def polygon(*coords, transform=None, conn_avoid=False, **style):
    'Draw a polygon.'
    if len(coords) < 3:
        inkex.utils.errormsg(_('A polygon must contain'
                               ' at least three points.'))
        return
    pts = ' '.join(["%s,%s" % (str(x), str(y)) for x, y in coords])
    obj = inkex.Polygon(points=pts)
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def regular_polygon(sides, center, r, angle=-pi/2, round=0.0, random=0.0,
                    transform=None, conn_avoid=False, **style):
    'Draw a regular polygon.'
    # Create a star object, which is also used for regular polygons.
    if sides < 3:
        inkex.utils.errormsg(_('A regular polygon must contain at least '
                               'three points.'))
        return
    obj = inkex.PathElement.star(center, (r, r/2), sides, round)

    # Set all the regular polygon's parameters.
    obj.set('sodipodi:arg1', angle)
    obj.set('sodipodi:arg2', angle + pi/sides)
    obj.set('inkscape:flatsided', 'true')   # Regular polygon, not star
    obj.set('inkscape:rounded', round)
    obj.set('inkscape:randomized', random)
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def star(sides, center, radii, angles=None, round=0.0, random=0.0,
         transform=None, conn_avoid=False, **style):
    'Draw a star.'
    # Create a star object.
    if sides < 3:
        inkex.utils.errormsg(_('A star must contain at least three points.'))
        return
    obj = inkex.PathElement.star(center, radii, sides, round)

    # If no angles were specified, point the star upwards.
    if angles is not None:
        pass
    elif radii[0] >= radii[1]:
        angles = (-pi/2, pi/sides - pi/2)
    else:
        angles = (pi/2, pi/sides + pi/2)

    # Set all the star's parameters.
    obj.set('sodipodi:arg1', angles[0])
    obj.set('sodipodi:arg2', angles[1])
    obj.set('inkscape:flatsided', 'false')   # Star, not regular polygon
    obj.set('inkscape:rounded', round)
    obj.set('inkscape:randomized', random)
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def arc(center, rx, ry, ang1, ang2, arc_type='arc',
        transform=None, conn_avoid=False, **style):
    'Draw an arc.'
    # Construct the arc proper.
    obj = inkex.PathElement.arc(center, rx, ry, start=ang1, end=ang2)
    if arc_type in ['arc', 'slice', 'chord']:
        obj.set('sodipodi:arc-type', arc_type)
    else:
        inkex.utils.errormsg(_('Invalid arc_type "%s"' % str(arc_type)))

    # The arc is visible only in Inkscape because it lacks a path.
    # Here we manually add a path to the object.  (Is there a built-in
    # method for doing this?)
    p = []
    ang1 %= 2*pi
    ang2 %= 2*pi
    x0 = rx*cos(ang1) + center[0]
    y0 = ry*sin(ang1) + center[1]
    p.append(inkex.paths.Move(x0, y0))
    delta_ang = (ang2 - ang1) % (2*pi)
    if delta_ang == 0.0:
        delta_ang = 2*pi   # Special case for full ellipses
    n_segs = int((delta_ang + pi/2) / (pi/2))
    for s in range(n_segs):
        a = ang1 + delta_ang*(s + 1)/n_segs
        x1 = rx*cos(a) + center[0]
        y1 = ry*sin(a) + center[1]
        p.append(inkex.paths.Arc(rx, ry, 0, False, True, x1, y1))
    if arc_type == 'arc':
        obj.set('sodipodi:open', 'true')
    elif arc_type == 'slice':
        p.append(inkex.paths.Line(center[0], center[1]))
        p.append(inkex.paths.ZoneClose())
    elif arc_type == 'chord':
        p.append(inkex.paths.ZoneClose())
    else:
        inkex.utils.errormsg(_('Invalid arc_type "%s"' % str(arc_type)))
    obj.path = inkex.Path(p)

    # Return a Simple Inkscape Scripting object.
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def path(*elts, transform=None, conn_avoid=False, **style):
    'Draw an arbitrary path.'
    if len(elts) == 0:
        inkex.utils.errormsg(_('A path must contain at least'
                               ' one path element.'))
        return
    d = ' '.join([str(e) for e in elts])
    obj = inkex.PathElement(d=d)
    return SimpleObject(obj, transform, conn_avoid, _common_shape_style, style)


def connector(obj1, obj2, ctype='polyline', curve=0,
              transform=None, conn_avoid=False, **style):
    'Connect two objects with a path.'
    # Create a path that links the two objects' centers.
    center1 = obj1._get_bbox_center()
    center2 = obj2._get_bbox_center()
    d = 'M %g,%g L %g,%g' % (center1[0], center1[1], center2[0], center2[1])
    path = inkex.PathElement(d=d)

    # Mark the path as a connector.
    path.set('inkscape:connector-type', str(ctype))
    path.set('inkscape:connector-curvature', str(curve))
    path.set('inkscape:connection-start', '#%s' % obj1._inkscape_obj.get_id())
    path.set('inkscape:connection-end', '#%s' % obj2._inkscape_obj.get_id())

    # Store the connector as its own object.
    return SimpleObject(path, transform, conn_avoid,
                        _common_shape_style, style)


def text(msg, base, path=None, transform=None, conn_avoid=False, **style):
    'Typeset a piece of text, optionally along a path.'
    # Create the basic text object.
    obj = inkex.TextElement(x=str(base[0]), y=str(base[1]))
    obj.set('xml:space', 'preserve')
    obj.text = msg

    # Optionally place the text along a path.
    if path is not None:
        tp = obj.add(inkex.TextPath())
        tp.href = path._inkscape_obj.get_id()

    # Wrap the text object within a SimpleObject.
    return SimpleObject(obj, transform, conn_avoid, {}, style)


def more_text(msg, base=None, conn_avoid=False, **style):
    'Append text to the preceding object, which must be text.'
    if len(_simple_objs) == 0 or \
       not isinstance(_simple_objs[-1]._inkscape_obj, inkex.TextElement):
        inkex.utils.errormsg(_('more_text must immediately follow'
                               ' text or another more_text'))
        return
    obj = _simple_objs[-1]
    tspan = inkex.Tspan()
    tspan.text = msg
    tspan.style = obj._construct_style({}, style)
    if base is not None:
        tspan.set('x', str(base[0]))
        tspan.set('y', str(base[1]))
    obj._inkscape_obj.append(tspan)
    return obj


def image(fname, ul, embed=True, transform=None, conn_avoid=False, **style):
    'Include an image, either embedded or linked.'
    obj = inkex.Image()
    obj.set('x', ul[0])
    obj.set('y', ul[1])
    if embed:
        # Read and embed the named file.
        img = PIL.Image.open(fname)
        data = io.BytesIO()
        img.save(data, img.format)
        mime = PIL.Image.MIME[img.format]
        b64 = base64.b64encode(data.getvalue()).decode('utf-8')
        uri = 'data:%s;base64,%s' % (mime, b64)
    else:
        # Point to an external file.
        uri = fname
    obj.set('xlink:href', uri)
    return SimpleObject(obj, transform, conn_avoid, {}, style)


def clone(obj, transform=None, conn_avoid=False, **style):
    'Return a linked clone of the object.'
    c = inkex.Use(obj._inkscape_obj)
    c.href = obj._inkscape_obj.get_id()
    return SimpleObject(c, transform, conn_avoid, {}, style)


def group(objs=[], transform=None, conn_avoid=False, **style):
    'Create a container for other objects.'
    g = inkex.Group()
    obj = SimpleGroup(g, transform, conn_avoid, {}, style)
    for o in objs:
        obj.add(o)
    return obj


def inkex_object(obj, transform=None, conn_avoid=False, **style):
    'Expose an arbitrary inkex-created object to Simple Inkscape Scripting.'
    return SimpleObject(obj, transform, conn_avoid, {}, style)


def filter_effect(name=None, pt1=None, pt2=None,
                  filter_units=None, primitive_units=None, **style):
    'Return an object representing an empty filter effect.'
    global _svg_defs
    return SimpleFilter(_svg_defs, name, pt1, pt2,
                        filter_units, primitive_units, **style)


def linear_gradient(pt1=None, pt2=None, repeat=None, gradient_units=None,
                    template=None, transform=None, **style):
    global _svg_defs
    return SimpleLinearGradient(_svg_defs, pt1, pt2, repeat,
                                gradient_units, template, transform,
                                **style)


# ----------------------------------------------------------------------

class SimpleInkscapeScripting(inkex.GenerateExtension):
    'Help the user create Inkscape objects with a simple API.'

    def add_arguments(self, pars):
        'Process program parameters passed in from the UI.'
        pars.add_argument('--tab', dest='tab',
                          help='The selected UI tab when OK was pressed')
        pars.add_argument('--program', type=str,
                          help='Python code to execute')
        pars.add_argument('--py-source', type=str,
                          help='Python source file to execute')

    def container_transform(self):
        '''Return an empty tranform so as to preserve user-specified
        coordinates.'''
        return inkex.Transform()

    def generate(self):
        'Generate objects from user-provided Python code.'
        global _svg_defs
        _svg_defs = self.svg.defs
        global width, height
        width, height = self.svg.width, self.svg.height  # For user convenience
        code = '''\
global width, height
print = inkex.utils.debug

'''
        py_source = self.options.py_source
        if py_source != "" and not os.path.isdir(py_source):
            # The preceding test for isdir is explained in
            # https://gitlab.com/inkscape/inkscape/-/issues/2822
            with open(self.options.py_source) as fd:
                code += fd.read()
            code += "\n"
        if self.options.program is not None:
            code += self.options.program.replace(r'\n', '\n')
        exec(code)
        for obj in _simple_objs:
            yield obj._inkscape_obj


if __name__ == '__main__':
    SimpleInkscapeScripting().run()
