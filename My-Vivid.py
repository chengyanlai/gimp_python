#!/usr/bin/env python
#
# -------------------------------------------------------------------------------------
#
# Copyright (c) 2013, Jose F. Maldonado
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, 
# are permitted provided that the following conditions are met:
#
#    - Redistributions of source code must retain the above copyright notice, this 
#    list of conditions and the following disclaimer.
#    - Redistributions in binary form must reproduce the above copyright notice, 
#    this list of conditions and the following disclaimer in the documentation and/or 
#    other materials provided with the distribution.
#    - Neither the name of the author nor the names of its contributors may be used 
#    to endorse or promote products derived from this software without specific prior 
#    written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY 
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES 
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT 
# SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, 
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR 
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN 
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN 
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH 
# DAMAGE.
#
# -------------------------------------------------------------------------------------
#
# This file is a basic example of a Python plug-in for GIMP.
#
# It can be executed by selecting the menu option: 'Filters/Test/Invert layer'
# or by writing the following lines in the Python console (that can be opened with the
# menu option 'Filters/Python-Fu/Console'):
# >>> image = gimp.image_list()[0]
# >>> layer = image.layers[0]
# >>> gimp.pdb.python_fu_test_invert_layer(image, layer)

from gimpfu import *

def channel_mix(img, layer, screen_opacity, overlay_opacity) :
    ''' Inverts the colors of the selected layer.
    
    Parameters:
    img : image The current image.
    layer : layer The layer of the image that is selected.
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
    pdb.plug_in_colors_channel_mixer(img, overlay_layer, False, 1.50, -0.25, -0.25, -0.25, 1.50, -0.25, -0.25, -0.25, 1.50)
    final_layer = pdb.gimp_image_merge_visible_layers(img, 0)
register(
    "python_fu_channel_mix_layer",
    "Channel Mix",
    "Add overlay layer and do channel mix",
    "Chenyen",
    "Open source (BSD 3-clause license)",
    "2013",
    "<Image>/Filters/ChenYen/Color_Mix",
    "*",
    [
		(PF_INT, "arg1", "Screen Opacity",  50 ),
		(PF_INT, "arg2", "Overlay Opacity", 100),
    ],
    [],
    channel_mix)

main()
