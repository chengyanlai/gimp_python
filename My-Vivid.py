#!/usr/bin/env python
# This is a python-fu to enhance your photo.

from gimpfu import *

def function(img, layer, screen_opacity, overlay_opacity, base_color) :
    '''
    Input Parameter:
    Screen Opacity: The opacity of screen layer.
    Overlay Opacity: The Opacity of overlay layer.
    Base Color: In the channel_mixer, we do the mix on RGB channels.
                (1.0 + c) is Base Color
                In Red-channel
                R: 1.0 + c
                G: -1.*c/2
                B: -1.*c/2
                In Green-channel
                R: -1.*c/2
                G: 1.0 + c
                B: -1.*c/2
                In Blue-channel
                R: -1.*c/2
                G: -1.*c/2
                B: 1.0 + c
    '''
    screen_layer = layer.copy()
    gimp.pdb.gimp_layer_set_opacity(screen_layer, screen_opacity)
    gimp.pdb.gimp_layer_set_mode(screen_layer, SCREEN_MODE)
    gimp.pdb.gimp_layer_set_name(screen_layer, "screen")
    img.add_layer(screen_layer,-1)
    overlay_layer = layer.copy()
    gimp.pdb.gimp_layer_set_opacity(overlay_layer, overlay_opacity)
    gimp.pdb.gimp_layer_set_mode(overlay_layer, OVERLAY_MODE)
    gimp.pdb.gimp_layer_set_name(overlay_layer, "overlay")
    img.add_layer(overlay_layer,-1)
    other_color = (1.0-base_color)/2.0
    pdb.plug_in_colors_channel_mixer(img, overlay_layer, False, base_color, other_color, other_color, other_color, base_color, other_color, other_color, other_color, base_color)
    final_layer = pdb.gimp_image_merge_visible_layers(img, 0)
register(
    "python_fu_build_icon",
    "Color MIx",
    "Overlay and Screen Color Mix.",
    "Chenyen",
    "Open source (BSD 3-clause license)",
    "2013",
    "<Image>/Filters/ChenYen/Color Mix",
    "*",
    [
		(PF_INT, "arg1", "Screen Opacity",  50 ),
		(PF_INT, "arg2", "Overlay Opacity", 100),
        (PF_FLOAT, "arg3", "Base Color", 1.5)
    ],
    [],
    function)

main()
