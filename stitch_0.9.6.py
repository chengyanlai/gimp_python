#!/usr/bin/env python
#
# GIMP plug-in to stitch two images together into a panorama.
#
#   Copyright (C) 2005  Thomas R. Metcalf (helicity314-stitch <at> yahoo <dot> com)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# If you find this code useful, you may use PayPal to contribute to future
# free software development efforts (send to helicity314-stitch <at> yahoo <dot> com).
# This is neither required nor expected, but would be appreciated.  You will get
# nothing for your money other than the knowledge that you are supporting
# the development of free software.
#
# REQUIREMENTS:
#
# - You must have a version of gimp compiled to include python support.
# - python pygtk module >=2.0
#
# INSTALLATION:
#
# Linux:  Copy this file to your gimp plug-in directory, e.g. ~/.gimp-2.2/plug-ins,
#         then restart gimp and stitch panorama should appear in the Xtns/Utils
#         menu.  Make sure the file is executable (chmod +x stitch.py).  Also, make
#         sure to remove any old versions from your plug-in directory.
# Windows: Likely something similar to Linux, but I don't know for sure since I don't
#          run windows.  You will have to edit the very first line of this
#          file to point to python on your system.
#
# VERSION 0.9.2:  Beta test version 2005-May-10
#      - Initial public release
# VERSION 0.9.3:  Beta test version 2005-May-18
#      - Improved blending algorithm
#      - Improved implementation of rotation & scale in correlation
# VERSION 0.9.4:  Beta test version 2005-May-23
#      - Improved the blending algorithm
# VERSION 0.9.5:  Beta test version 2005-May-30
#      - Improved the color balance algorithm
#      - Improved treatment of scaling in correlation.
#      - Fixed transform for two control points
# VERSION 0.9.6: Beta test version 2005-June-07
#      - Added up/down buttons in control point selector
#      - Added color check box in control point selector



'''GIMP plug-in to stitch two images together into a panorama.'''

abort = False

# These should all be standard modules
import sys
import os
import copy
import math
import struct
import time
import gimp
import gimpplugin
from gimpenums import *
import pygtk
pygtk.require('2.0')
import gtk
import cPickle as pickle

#------------ MAIN PLUGIN CLASS

class stitch_plugin(gimpplugin.plugin):
    '''The main plugin class defines and installs the stitch_panorama function.'''
    version = '0.9.6'
    def query(self):
        gimp.install_procedure("stitch_panorama",
                               "Stitch two images together to make a panorama",
                               "Stitch two images together to make a panorama (ver. " + \
                                stitch_plugin.version+")",
                               "Thomas R. Metcalf",
                               "Thomas R. Metcalf",
                               "2005",
                               "<Image>/Filters/ChenYen/Stitch Panorama",
                               "RGB*, GRAY*",EXTENSION,
                               [(PDB_INT32, "run-mode", "interactive/noninteractive"),
                               ],
                               [])

    # stitch_panorama is the main routine where all the work is done.
    
    def stitch_panorama(self, mode, image_list=None, control_points=None):
        '''Stitch together two images into a panorama.

        First get a set of "control points" which define matching
        locations in the two images.  Then use these control points to
        balance the color and warp the images into a third, panoramic
        image.'''

        if not abort:
            if not image_list: image_list = gimp.image_list()
            # Select which image is the reference and which is transformed.
            image_list=select_images(image_list,mode)
            if check_image_list_ok(image_list,mode):
                image_list[0].disable_undo()
                image_list[1].disable_undo()
                # fire up the user interface which does all the work.
                panorama = stitch_control_panel(control_points,image_list,mode)
                # clean up a bit
                for img in image_list:
                    if img:
                        img.clean_all()
                        img.enable_undo()
                        update_image_layers(img)  # is this necessary?
                gimp.pdb.gimp_displays_flush()
                return panorama

# Pau.

#------------ SUPPORTING CLASS DEFINITIONS

class control_point(object):
    '''Each control point gives matching locations in two images.'''
    def __init__(self,x1,y1,x2,y2,correlation=None,colorbalance=True):
        self.xy = (float(x1),float(y1),float(x2),float(y2))
        self.correlation = correlation
        self.colorbalance = colorbalance
    def x1(self): return self.xy[0]
    def y1(self): return self.xy[1]
    def x2(self): return self.xy[2]
    def y2(self): return self.xy[3]
    def cb(self):
        try:
            colorbalance = self.colorbalance
        except AttributeError:
            colorbalance = True
        return colorbalance
    def invert(self):
        try:
            colorbalance = self.colorbalance
        except AttributeError:
            colorbalance = True
        return control_point(self.x2(),self.y2(),self.x1(),self.y1(),
                                           self.correlation,colorbalance)

minradius = 20.0  # min radius for color averaging

class stitchable(object):
    '''Two images and their control points for stitching.'''
    def __init__(self,mode,rimage,timage,control_points=None):
        self.mode = mode                       # Mode: interactive/noninteractive
        self.rimage = rimage                   # the reference image object
        self.timage = timage                   # the transformed image object
        self.cimage = None                     # temporary image for correlation
        self.dimage = None                     # temporary image for undistorted image
        self.rimglayer = None                  # main image layer in reference image
        self.timglayer = None                  # main image layer in transformed image
        self.rcplayer = None                   # the reference control point display layer
        self.tcplayer = None                   # the transform control point display layer
        self.control_points = control_points   # the warping control points
        self.panorama = None                   # the resulting panoramic image
        self.rlayer = None                     # the reference layer in self.panorama
        self.tlayer = None                     # the transformed layer in self.panorama
        self.rmask = None                      # the reference layer mask
        self.tmask = None                      # the transformed layer mask
        self.rxy = None                        # x,y of reference corners [x1,y1,x2,y2]
        self.txy = None                        # x,y of transformed corners [x1,y1,x2,y2]
        self.interpolation = INTERPOLATION_CUBIC
        self.supersample = 1
        self.cpcorrelate = True                # correlate control points?
        self.recursion_level = 5
        self.clip_result = 1   # this must be 1 or gimp will crash (segmentation fault)
        self.colorbalance = True               # color balance?
        self.colorradius = minradius           # color radius
        self.blend = True                      # blend edges?
        self.blend_fraction = 0.25             # size of blend along edges (fraction of image size)
        self.rmdistortion = True               # remove distortion?
        self.condition_number = None           # the condition number of the transform
        self.progressbar = None                # the progress bar widget
        self.update()
    def __getitem__(self,index):
        '''Make the stitchable class indexable over the control points.'''
        return self.control_points[index]
    def update(self):
        if self.control_points:
            self.npoints = len(self.control_points)
            rarray,tarray = self.arrays()
            self.transform = compute_transform_matrix(rarray,tarray,self)
            self.errors = compute_control_point_errors(self)
        else:
            self.npoints = 0
            self.transform = None
            self.errors = None
    def set_control_points(self,control_points):
        '''Se the whole control point list.'''
        self.control_points = control_points
        self.update()
    def add_control_point(self,cp):
        '''Add a control point to the control_points list.
           The control_point parameter should be of the control_point
           class.'''
        assert cp.__class__ is control_point, \
               'control_point parameter is not an instance of the control_point class.'
        if self.control_points:
            self.control_points.append(cp)
        else:
            self.control_points = [cp]
        self.update()
    def delete_control_point(self,index):
        '''Delete a control point from the control point list.'''
        if self.control_points:
            self.control_points.pop(index)
            self.update()
    def replace_control_point(self,cp,index):
        '''Replace a control point in the control point list.'''
        if self.control_points:
            if index < len(self.control_points):
                self.control_points[index] = cp
                self.update()
    def move_control_point_up(self,index):
        if self.control_points:
            if index > 0 and index < self.npoints:
                cp1 = self.control_points[index]
                cp2 = self.control_points[index-1]
                self.control_points[index] = cp2
                self.control_points[index-1] = cp1
                self.update()
    def move_control_point_down(self,index):
        if self.control_points:
            if index >=0 and index <self.npoints-1:
                cp1 = self.control_points[index]
                cp2 = self.control_points[index+1]
                self.control_points[index] = cp2
                self.control_points[index+1] = cp1
                self.update()
    def inverse_control_points(self):
        '''Invert the control point list and return the inverse.'''
        inverse = []
        for c in self.control_points:
            inverse.append(c.invert())
        return inverse
    def arrays(self):
        '''Get the reference and transformed control points as lists.'''
        rarray = []
        tarray = []
        for i in range(self.npoints):
            rarray.append([self.control_points[i].x1(),self.control_points[i].y1(),1.0])
            tarray.append([self.control_points[i].x2(),self.control_points[i].y2(),1.0])
        return (rarray,tarray)
    def color(self,control_point,radius=minradius):
        '''Get the color values at a control point in each image.
           The return value is a two-element tuple in which each entry
           is a color tuple.'''
        assert control_point in self.control_points,'Bad control point'
        rnx = self.rimage.width   # the dimensions of the images
        rny = self.rimage.height
        tnx = self.timage.width
        tny = self.timage.height
        # Make sure that the radius is not so large that the
        # average circle extends beyond the edge.
        if radius > control_point.x1():
            radius = max(control_point.x1(),1.0)
        if radius > control_point.y1():
            radius = max(control_point.y1(),1.0)
        if control_point.x1()+radius > rnx-1:
            radius = max(rnx-control_point.x1()-1,1.0)
        if control_point.y1()+radius > rny-1:
            radius = max(rny-control_point.y1()-1,1.0)
        #if __debug__: print 'radius: ',radius,control_point.x1(),control_point.y1(),rnx,rny
        # the scale of the transformed image may be different from the scale of the
        # reference image.  So, the radius should be scaled as well.
        if self.transform:
            (sscale,srotation) = transform2rs(self.transform)
            tradius = max(radius/sscale,1.0)
        else:
            tradius = radius
        # Check size of tradius
        if tradius > control_point.x2():
            tradius = max(control_point.x2(),1.0)
            if self.transform: radius = max(tradius*sscale,1.0)
        if tradius > control_point.y2():
            tradius = max(control_point.y2(),1.0)
            if self.transform: radius = max(tradius*sscale,1.0)
        if control_point.x2()+tradius > tnx-1:
            tradius = max(tnx-control_point.x2()-1,1.0)
            if self.transform: radius = max(tradius*sscale,1.0)
        if control_point.y2()+tradius > tny-1:
            tradius = max(tny-control_point.y2()-1,1.0)
            if self.transform: radius = max(tradius*sscale,1.0)
        #if __debug__: print 'radius: ',tradius,control_point.x2(),control_point.y2(),tnx,tny
        ##if __debug__: print 'color radii are ',radius,tradius
        ##if __debug__:
        ##    print 'using a color radius of ',radius,tradius
        return ( gimp.pdb.gimp_image_pick_color(self.rimage,
                                                self.rimglayer,
                                                control_point.x1(),
                                                control_point.y1(),
                                                0, # use the composite image, ignore the drawable
                                                1,radius),
                 gimp.pdb.gimp_image_pick_color(self.timage,
                                                self.timglayer,
                                                control_point.x2(),
                                                control_point.y2(),
                                                0, # use the composite image, ignore the drawable
                                                1,tradius)
                )
    def cbtest(self,control_point):
        '''Get the color balance flag for a control point.'''
        assert control_point in self.control_points,'Bad control point'
        return control_point.cb()

    def cbtests(self):
        '''Get flag to determine if a control point will be used in the color balancing.'''
        return [self.cbtest(self.control_points[c])
                    for c in range(self.npoints)] # iterates over self.control_points
    
    def colors(self):
        '''Get the color values at all the control points.'''
        if self.errors:
            return [self.color(self.control_points[c],self.colorradius)
                    for c in range(self.npoints)] # iterates over self.control_points
        else:
            return [self.color(c) for c in self] # iterates over self.control_points
        
    def brightness(self,control_point,radius=minradius):
        '''Compute the brightness of a control point in each image.
           The return value is a two-element tuple in which the entries
           are the brightness of the two images in the stitchable object.'''
        c = self.color(control_point,radius)
        brightness1 = 0
        brightness2 = 0
        n = 0.0
        for b1,b2 in zip(c[0],c[1]):  # iterate over both image colors simultaneously
            brightness1 += b1
            brightness2 += b2
            n += 1.0
        # the brightness is the mean of the values
        return (int(round(brightness1/n)),int(round(brightness2/n)))
    def brightnesses(self):
        '''Get the brightness values at all the control points.'''
        if self.errors:
            return [self.brightness(self.control_points[c],self.colorradius)
                    for c in range(self.npoints)] # iterates over self.control_points
        else:
            return [self.brightness(c) for c in self] # iterates over self.control_points
        
    def value(self,control_point,radius=minradius):
        '''Compute the value of a control point in each image.
           The return value is a two-element tuple in which the entries
           are the value of the two images in the stitchable object.'''
        c = self.color(control_point,radius)
        # the value is the max of the color channels
        return ( max(c[0]), max(c[1]) )
    def values(self):
        '''Get the values at all the control points.'''
        if self.errors:
            return [self.value(self.control_points[c],self.colorradius)
                    for c in range(self.npoints)]
        else:
            return [self.value(c) for c in self] # iterates over self.control_points


#------------ SUPPORTING MODULE FUNCTIONS

def update_image_layers(image):
    '''Update all the layers in an image.'''
    for layer in image.layers:
        layer.update(0,0,layer.width,layer.height)
        layer.flush()
    gimp.pdb.gimp_displays_flush()
        
def error_message(message,mode):
    '''Display an error message for the user.'''
    if mode == RUN_INTERACTIVE or mode == RUN_WITH_LAST_VALS:
        gimp.pdb.gimp_message(message)
    else:
        print message

def select_images(image_list,mode):
    '''Select two of the >2 available images for stitching.
       The first in the list is the reference image and the second
       is the transformed image.'''
    if mode == RUN_NONINTERACTIVE:
        return image_list[0:2]  # just return the first two
    ##if __debug__: print 'this is the image selector.'
    widget = ImageSelectorWidget(image_list,mode)  # make widget
    widget.main()             # call widget
    return widget.image_list

def check_image_list_ok(image_list,mode):
    '''Check the image list to make sure it is suitable for stitching.'''
    if len(image_list) != 2:
        error_message('Error: you must specify two images.',mode)
        return False
    if not image_list[0] or not image_list[1]:
        error_message('Error: you must open at least two images.',mode)
        return False
    for img in image_list:  # Make sure there is something in the images
        try:
            drawable = gimp.pdb.gimp_image_get_active_drawable(img)
        except RuntimeError:
            error_message('Error: image '+img.name+' appears to be empty',mode)
            return False
    if image_list[0] is image_list[1]:
        error_message('Warning: you selected the same image as ' + \
                        'both the reference and the transformed image.',mode)
    return True  # passed the tests

def stitch_control_panel(control_points,image_list,mode):
    '''Instantiate a stitchable object and start the user interface.'''
    ##if __debug__: print 'this is the stitch user interface.'
    # get control points from last run
    if not control_points:
        control_points = get_control_points_from_parasite(image_list[0],image_list[1])
        
    stitch = stitchable(mode,image_list[0],image_list[1],control_points)
    # get the active layer and save for later use.  Another layer will be added
    # later to mark the control points so we will need to be able to copy
    # from just the image layer.
    stitch.rimglayer = stitch.rimage.layers[0]
    stitch.timglayer = stitch.timage.layers[0]
    if len(stitch.rimage.layers) > 1 :
        error_message('Warning: your selected reference image has multiple layers.  '+\
                      'Only the bottom layer will be stitched.  You may want to '+\
                      'flatten the image and rerun stitch panorama.',stitch.mode)
    if len(stitch.timage.layers) > 1 :
        error_message('Warning: your selected transformed image has multiple layers.  '+\
                      'Only the bottom layer will be stitched.  You may want to '+\
                      'flatten the image and rerun stitch panorama.',stitch.mode)

    try:
        if mode == RUN_NONINTERACTIVE:
            go_stitch_panorama(stitch)
        else:
            # Call the user interface
            draw_control_points(stitch)
            widget = ControlPanelWidget(stitch)
            widget.main()
            stitch = widget.stitch
        if stitch.control_points:
            save_control_points_to_parasite(stitch)
    finally:
        # clean up a bit
        if stitch.panorama: stitch.panorama.enable_undo()
        if stitch.rcplayer: stitch.rimage.remove_layer(stitch.rcplayer)
        if stitch.tcplayer: stitch.timage.remove_layer(stitch.tcplayer)
        if stitch.cimage: gimp.pdb.gimp_image_delete(stitch.cimage)
        if stitch.dimage: gimp.pdb.gimp_image_delete(stitch.dimage)
        gimp.pdb.gimp_displays_flush()

    return stitch.panorama

def control_points_editor(stitch):
    '''Set/Edit the control point list.'''
    ##if __debug__: print 'this is the control points editor'
    gimp.pdb.gimp_image_undo_enable(stitch.rimage)
    gimp.pdb.gimp_image_undo_enable(stitch.timage)
    widget = ControlPointEditorWidget(stitch)
    widget.main()
    gimp.pdb.gimp_image_undo_disable(stitch.rimage)
    gimp.pdb.gimp_image_undo_disable(stitch.timage)
    draw_control_points(stitch)
    return widget.stitch

def get_new_control_point(stitch,colorbalance=True):
    '''Get a new control point from the selections in the images.'''
    ##if __debug__: print 'this is get_new_control_point()'
    reference_selection = gimp.pdb.gimp_selection_bounds(stitch.rimage)
    transformed_selection = gimp.pdb.gimp_selection_bounds(stitch.timage)
    if not reference_selection[0]:
        error_message('Error: there is no selection in the reference image',stitch.mode)
    if not transformed_selection[0]:
        error_message('Error: there is no selection in the transformed image',stitch.mode)
    if not reference_selection[0] or not transformed_selection[0]:
        return None
    ##if __debug__:
    ##    print 'reference selection '+str(reference_selection)
    ##    print 'transformed selection '+str(transformed_selection)

    rxsize = reference_selection[3]-reference_selection[1]
    rysize = reference_selection[4]-reference_selection[2]
    txsize = transformed_selection[3]-transformed_selection[1]
    tysize = transformed_selection[4]-transformed_selection[2]

    xscale = max(min(rxsize/8.0,txsize/8.0),1.0) # one eighth the max shift
    yscale = max(min(rysize/8.0,tysize/8.0),1.0)

    # make a temporary image 
    
    xsize = max(rxsize,txsize)
    ysize = max(rysize,tysize)
    
    rx0 = (xsize-rxsize)/2  # starting coordinates of layer data
    ry0 = (ysize-rysize)/2 
    tx0 = (xsize-txsize)/2 
    ty0 = (ysize-tysize)/2 
                               
    ##if __debug__: print 'xsize,ysize: ',xsize,ysize,rx0,ry0,rxsize,rysize
    if stitch.cimage:
        stitch.cimage.resize(xsize,ysize,0,0)
    else:
        stitch.cimage = gimp.pdb.gimp_image_new(xsize,ysize,RGB)

    # Add the reference selection to cimage with a mask
    rlayer = gimp.pdb.gimp_layer_new(stitch.cimage,      # image
                                     xsize,              # width
                                     ysize,              # height
                                     RGB,                # type
                                     'reference',        # name
                                     100,                # opacity
                                     NORMAL_MODE         # layer combination mode
                                     )
    ##if __debug__: print stitch.rimglayer,stitch.timglayer
    gimp.pdb.gimp_image_add_layer(stitch.cimage,rlayer,-1)   # make new layer
    foreground = gimp.pdb.gimp_context_get_foreground()
    background = gimp.pdb.gimp_context_get_background()
    gimp.pdb.gimp_context_set_foreground((0,0,0))
    gimp.pdb.gimp_context_set_background((255,255,255))
    gimp.pdb.gimp_drawable_fill(rlayer,FOREGROUND_FILL)  # erase
    gimp.pdb.gimp_edit_copy(stitch.rimglayer)           # copy selection
    gimp.pdb.gimp_selection_none(stitch.cimage)
    gimp.pdb.gimp_rect_select(stitch.cimage,rx0,ry0,rxsize,rysize,CHANNEL_OP_REPLACE,0,0.0)
    gimp.pdb.gimp_floating_sel_anchor(gimp.pdb.gimp_edit_paste(rlayer,0)) # paste and anchor
    gimp.pdb.gimp_selection_none(stitch.cimage)
    gimp.pdb.gimp_layer_add_alpha(rlayer)              # Add alpha channel
    rmask = gimp.pdb.gimp_layer_create_mask(rlayer,ADD_SELECTION_MASK)
    gimp.pdb.gimp_layer_add_mask(rlayer,rmask)          # Add layer mask
    gimp.pdb.gimp_drawable_fill(rmask,FOREGROUND_FILL)
    gimp.pdb.gimp_selection_none(stitch.cimage) 
    gimp.pdb.gimp_rect_select(stitch.cimage,rx0,ry0,rxsize,rysize,CHANNEL_OP_REPLACE,0,0.0)
    gimp.pdb.gimp_edit_bucket_fill(rmask,
                                   BG_BUCKET_FILL,       # fill mode
                                   NORMAL_MODE,          # paint mode
                                   100.0,                # opacity
                                   0.0,                  # threshhold
                                   0,                    # sample merged
                                   0.0,                  # x if no selection
                                   0.0)                  # y if no selection
    gimp.pdb.gimp_selection_none(stitch.cimage) 
    gimp.pdb.gimp_context_set_foreground(foreground)
    gimp.pdb.gimp_context_set_background(background)

    # Add the transformed selection to cimage with a mask
    tlayer = gimp.pdb.gimp_layer_new(stitch.cimage,      # image
                                     xsize,              # width
                                     ysize,              # height
                                     RGB,                # type
                                     'transformed',      # name
                                     100,                # opacity
                                     NORMAL_MODE         # layer combination mode
                                     )
    gimp.pdb.gimp_image_add_layer(stitch.cimage,tlayer,-1)    # make new layer
    foreground = gimp.pdb.gimp_context_get_foreground()
    background = gimp.pdb.gimp_context_get_background()
    gimp.pdb.gimp_context_set_foreground((0,0,0))
    gimp.pdb.gimp_context_set_background((255,255,255))
    gimp.pdb.gimp_drawable_fill(tlayer,FOREGROUND_FILL)  # erase
    gimp.pdb.gimp_edit_copy(stitch.timglayer)            # copy selection
    gimp.pdb.gimp_selection_none(stitch.cimage)
    gimp.pdb.gimp_rect_select(stitch.cimage,tx0,ty0,txsize,tysize,CHANNEL_OP_REPLACE,0,0.0)
    gimp.pdb.gimp_floating_sel_anchor(gimp.pdb.gimp_edit_paste(tlayer,0)) # paste and anchor
    gimp.pdb.gimp_selection_none(stitch.cimage) 
    gimp.pdb.gimp_layer_add_alpha(tlayer)              # Add alpha channel
    tmask = gimp.pdb.gimp_layer_create_mask(tlayer,ADD_SELECTION_MASK)
    gimp.pdb.gimp_layer_add_mask(tlayer,tmask)          # Add layer mask
    gimp.pdb.gimp_drawable_fill(tmask,FOREGROUND_FILL)
    gimp.pdb.gimp_selection_none(stitch.cimage) 
    gimp.pdb.gimp_rect_select(stitch.cimage,tx0,ty0,txsize,tysize,CHANNEL_OP_REPLACE,0,0.0)
    gimp.pdb.gimp_edit_bucket_fill(tmask,
                                   BG_BUCKET_FILL,       # fill mode
                                   NORMAL_MODE,          # paint mode
                                   100.0,                # opacity
                                   0.0,                  # threshhold
                                   0,                    # sample merged
                                   0.0,                  # x if no selection
                                   0.0)                  # y if no selection
    gimp.pdb.gimp_selection_none(stitch.cimage) 
    gimp.pdb.gimp_context_set_foreground(foreground)
    gimp.pdb.gimp_context_set_background(background)

    rpixels = rlayer.get_pixel_rgn(0,0,          # x,y
                                   xsize, ysize, # width,height
                                   TRUE,        # changes applied to layer
                                   FALSE)        # Shadow
    tpixels = tlayer.get_pixel_rgn(0,0,          # x,y
                                   xsize, ysize, # width,height
                                   TRUE,        # changes applied to layer
                                   FALSE)        # Shadow
    rmpixels = rmask.get_pixel_rgn(0,0,          # x,y
                                   xsize, ysize, # width,height
                                   TRUE,        # changes applied to layer
                                   FALSE)        # Shadow
    tmpixels = tmask.get_pixel_rgn(0,0,          # x,y
                                   xsize, ysize, # width,height
                                   TRUE,        # changes applied to layer
                                   FALSE)        # Shadow

    for i in range (xsize):
        for j in range(ysize):
            # set the alpha channel for the layers
            r,g,b,a = struct.unpack('B'*rpixels.bpp,rpixels[i,j])
            m = struct.unpack('B'*rmpixels.bpp,rmpixels[i,j])
            rpixels[i,j] = struct.pack('B'*rpixels.bpp,r,g,b,m[0])
            r,g,b,a = struct.unpack('B'*tpixels.bpp,tpixels[i,j])
            m = struct.unpack('B'*tmpixels.bpp,tmpixels[i,j])
            tpixels[i,j] = struct.pack('B'*tpixels.bpp,r,g,b,m[0])
    
    tsave  = tpixels[0:xsize,0:ysize]    # store the data for restoration later.

    ##if __debug__:
    ##    rtestcorr = compute_correlation(rpixels,rpixels)
    ##    ttestcorr = compute_correlation(tpixels,tpixels)
    ##    print 'Test corr should be 1.0: ',rtestcorr,ttestcorr

    correlation = compute_correlation(rpixels,tpixels)
    
    ##if __debug__:
    ##    print 'Correlation is ',correlation
    ##    #display = gimp.pdb.gimp_display_new(stitch.cimage)
    ##    #widget=MessageWidget('Debug: press ok to continue.')
    ##    #widget.main()
    ##    #gimp.pdb.gimp_display_delete(display)

    # adjust the control point using the correlation, if requested
    
    xshift = 0.
    yshift = 0.
    rotate = 0.
    scalxy = 1.
    
    if stitch.cpcorrelate:
        # Update the control point by maximizing the correlation

        if stitch.npoints >= 1:
            # get the approximate rotation and scale
            rarray,tarray = stitch.arrays()
            ttrans = compute_transform_matrix(rarray,tarray,stitch)
            (sscale,srotation) = transform2rs(ttrans)
##             if __debug__:
##                 print 'srotation is ',srotation, \
##                       math.atan2(-ttrans[0][1],ttrans[0][0],), \
##                       math.atan2(+ttrans[1][0],ttrans[1][1])
        else:
            srotation = 0.0
            sscale = 1.0

        xs = 0.0
        ys = 0.0
        rs = -srotation
        ss = sscale
        var = [xs,ys,rs,ss]
        data = (tlayer,
                rpixels,tpixels,
                tsave,
                xsize,ysize,
                stitch.progressbar)
        scale = [xscale,yscale,0.10,0.10]
        itmax = 100
        ##if __debug__: print 'Initial scale,rotation ',ss,rs
        
        # Optimizing functions should always be repeated just in
        # case the the algorithm got stuck.  If it did not get stuck,
        # then the second call will be quick.
        for iamoeba in range(2):
            (varbest,correlation,iterations) = amoeba(var,
                                                      scale,
                                                      transform_correlation_func,
                                                      ftolerance=1.e-3,
                                                      xtolerance=1.e-3,
                                                      itmax=itmax,
                                                      data=data)
            var = varbest
            #if __debug__:
            #    print 'Best corr after ', iterations, ' iterations: ',correlation
            
        (xshift,yshift,rotate,scalxy) = varbest
                        
        #if __debug__:
        #    print 'Final corr,xs,ys,rs,ss: ',correlation,xshift,yshift,rotate,scalxy,iterations
        
    update_progress_bar(stitch.progressbar,'Correlating ...',1.0)
    stitch.cimage.remove_layer(rlayer)
    stitch.cimage.remove_layer(tlayer)

    rx = (reference_selection[1]+reference_selection[3])/2.0
    ry = (reference_selection[2]+reference_selection[4])/2.0
    tx = (transformed_selection[1]+transformed_selection[3])/2.0
    ty = (transformed_selection[2]+transformed_selection[4])/2.0

    # inverse transform takes transformed center back to reference center

    transform = matrix_invert(rss2transform(xshift,yshift,rotate,scalxy,xsize,ysize))

    ##if __debug__:
    ##    print 'Test the CP calculation...'
    ##    print 'This should be the identity matrix:'
    ##    print matrixmultiply(transform,rss2transform(xshift,yshift,rotate,scalxy,xsize,ysize))

    # since the images are centered in cimage,
    # tx,ty in the big image corresponds to xcenter,ycenter in cimage.
    xcenter = (xsize-1.0)/2.0
    ycenter = (ysize-1.0)/2.0
    stx,sty = xytransform(transform,xcenter,ycenter)
    ##if __debug__: print 'stx,sty:',stx,sty,tx+stx-xcenter,ty+sty-ycenter
    stx = stx - xcenter
    sty = sty - ycenter

    update_progress_bar(stitch.progressbar,' ',0.0)

    return control_point(rx,ry,tx+stx,ty+sty,correlation,colorbalance)

def rss2transform(xs,ys,rs,ss,xsize,ysize):
    '''Convert rotation, shift and scale to a transform matrix.'''

    # the rotation&scale should be around the center, not the corner
    
    xs2 = (xsize-1)/2.0
    ys2 = (ysize-1)/2.0
    half_shift_minus = [[ 1.0, 0.0, 0.0],
                        [ 0.0, 1.0, 0.0],
                        [-xs2,-ys2, 1.0]]
    half_shift_plus = [[1.0, 0.0, 0.0],
                       [0.0, 1.0, 0.0],
                       [xs2, ys2, 1.0]]

    rotation = [[+math.cos(rs),+math.sin(rs), 0.0],
                [-math.sin(rs),+math.cos(rs), 0.0],
                [0.0,          0.0,           1.0]]
    rotation = matrixmultiply(rotation,half_shift_plus)
    rotation = matrixmultiply(half_shift_minus,rotation)

    scale = [[ss, 0.0,0.0],
             [0.0,ss, 0.0],
             [0.0,0.0,1.0]]
    scale = matrixmultiply(scale,half_shift_plus)
    scale = matrixmultiply(half_shift_minus,scale)

    shift = [[1.0 ,0.0, 0.0],
             [0.0, 1.0, 0.0],
             [xs,  ys,  1.0]]
    
    # put it all together
    
    transform = matrixmultiply(scale,rotation)
    transform = matrixmultiply(shift,transform)
        
    return transform

def transform2rs(transform):
    '''Compute rotation and scale from the tranform matrix.'''

    # this is approximate since the shear would also come into
    # the transform here.
    
    srotation = (math.atan2(-transform[0][1],transform[0][0]) +
                 math.atan2(+transform[1][0],transform[1][1]))/2.0

    # use the inverse rotation matrix to remove the rotation part
    # of the transform.  What's left should be the scaling.

    rinv = [[+math.cos(srotation),-math.sin(srotation)],
            [+math.sin(srotation),+math.cos(srotation)]]
    smat = matrixmultiply(rinv,[[transform[0][0],transform[1][0]],
                                [transform[0][1],transform[1][1]]])
    sscale = abs(smat[0][0]+smat[1][1])/2.0
    sscale = sscale/transform[2][2]  # apply overall scale

    ##if __debug__: print sscale,srotation
        
    return (sscale,srotation)


def transform_correlation_func(var,data):
    (xs,ys,rs,ss) = var
    (tlayer,rpixels,tpixels,tsave,xsize,ysize,pbar) = data
    corr = transform_correlation(tlayer,
                                 rpixels,tpixels,
                                 tsave,
                                 xsize,ysize,
                                 xs,ys,rs,ss)
    update_progress_bar(pbar,'Correlating ...',max(corr,0.0,pbar.get_fraction()))
    ##if __debug__: print 'xs,ys,rs,ss,corr',xs,ys,rs,ss,corr
    return corr

def transform_correlation(tlayer,
                          rpixels,tpixels,
                          tsave,
                          xsize,ysize,
                          xs,ys,rs,ss):

    transform = rss2transform(xs,ys,rs,ss,xsize,ysize)
    
    gimp.pdb.gimp_drawable_transform_matrix(tlayer,
                                            transform[0][0],transform[1][0],transform[2][0],
                                            transform[0][1],transform[1][1],transform[2][1],
                                            transform[0][2],transform[1][2],transform[2][2],
                                            TRANSFORM_FORWARD,   # direction
                                            INTERPOLATION_CUBIC, # interpolation
                                            1,   # supersample
                                            5,   # recursion level
                                            1)   # clip
    
    tlayer.flush()

    corr = compute_correlation(rpixels,tpixels)  # compute correlation for this transform
    tpixels[0:xsize,0:ysize] = tsave     # restore layer to original
    tlayer.flush()
    return corr


def compute_correlation(rpixels,tpixels):
    '''Compute the cross correlation between to pixel regions.'''
    rformat = 'B'*rpixels.bpp  # replicate 'B' by number of bytes
    tformat = 'B'*tpixels.bpp

    assert rpixels.w == tpixels.w
    assert rpixels.h == tpixels.h
    assert rpixels.bpp == 4
    assert tpixels.bpp == 4

    rmean = 0L
    tmean = 0L
    npix = 0L

    # set up empty arrays to store the brightness etc.  I assume this
    # is faster than accessing and unpacking the pixel regions repeatedly.

    rbrightness = [0]*rpixels.h
    tbrightness = [0]*rpixels.h
    ralpha = [0]*rpixels.h
    talpha = [0]*rpixels.h

    for j in range(rpixels.h):
        rbrightness[j] = [0]*rpixels.w  # set up empty arrays on the fly
        tbrightness[j] = [0]*rpixels.w
        ralpha[j] = [0]*rpixels.w
        talpha[j] = [0]*rpixels.w
        for i in range(rpixels.w):
            rr,rg,rb,ra = struct.unpack(rformat,rpixels[i,j])
            tr,tg,tb,ta = struct.unpack(tformat,tpixels[i,j])
            rbrightness[j][i] = int(rr)+int(rg)+int(rb)
            tbrightness[j][i] = int(tr)+int(tg)+int(tb)
            ralpha[j][i] = int(ra)
            talpha[j][i] = int(ta)
            if int(ra) and int(ta):
                rmean += long(rbrightness[j][i])
                tmean += long(tbrightness[j][i])
                npix = npix + 1L

    rsum2 = 0.0
    tsum2 = 0.0
    rtsum = 0.0
    correlation = 0.0
    if npix:
        rmean = float(rmean) / float(npix)
        tmean = float(tmean) / float(npix)
        for i in range(rpixels.w):
            for j in range(rpixels.h):
                if ralpha[j][i] and talpha[j][i]:
                    rval = float(rbrightness[j][i])-rmean
                    tval = float(tbrightness[j][i])-tmean
                    rtsum += rval*tval
                    rsum2 += rval*rval
                    tsum2 += tval*tval
        if rsum2 and tsum2:
            correlation = rtsum/(math.sqrt(rsum2)*math.sqrt(tsum2))

    return correlation

def get_pickle_name(timage):
    return 'stitch_'+timage.name+'-'+str(timage.ID)

def get_control_points_from_parasite(rimage,timage):
    '''Check for and get a list of control points from reference image parasite.'''
    # check the reference image for a parasite named after the transfomed
    # image.  Thus, there is a unique parasite for the pair of images.
    name = get_pickle_name(timage)
    parasite = rimage.parasite_find(name)
    if parasite:
        return pickle.loads(parasite.data)
    else:
        return None

def save_control_points_to_parasite(stitchobj):
    '''Save the control point list to a reference image parasite.'''
    # save the parasite in the reference image named after the transformed
    # image so that there is a unique parasite name for the pair of images.
    # Also save the inverse set of control points to the transformed image
    # in case the user wants to apply the images the other way around.
    if stitchobj.control_points:
        cp_pickle = pickle.dumps(stitchobj.control_points)
        name = get_pickle_name(stitchobj.timage)
        stitchobj.rimage.attach_new_parasite(name,3,cp_pickle)
        cp_pickle = pickle.dumps(stitchobj.inverse_control_points())
        name = get_pickle_name(stitchobj.rimage)
        stitchobj.timage.attach_new_parasite(name,3,cp_pickle)

def compute_transform_matrix(rarray,tarray,stitch=None):
    '''Calculate the transformation matrix which defines how the transformed
    image will be warped onto the reference image.'''

    #if not stitch.npoints or stitch.npoints==0: return None
    
    ##if __debug__: print 'This is compute_transform_matrix'
    #rarray,tarray = stitch.arrays()

    npoints = len(rarray)
    assert npoints == len(tarray),'rarray and tarray must be the same size.'

    if npoints == 1:
        # With one control point, just shift them on top of each other.
        ##if __debug__: print 'npoints is 1.'
        xshift = rarray[0][0]-tarray[0][0]
        yshift = rarray[0][1]-tarray[0][1]
        transform = [[1.0,0.0,0.0],
                     [0.0,1.0,0.0],
                     [xshift,yshift,1.0]]
    elif npoints == 2:
        # With two control points, first shift the averages to the
        # same place, then scale the length to the same value and
        # finally rotate the segments to the same orientation.
        ##if __debug__: print 'npoints is 2.'
        rxavg = (rarray[0][0] + rarray[1][0])/2.0
        txavg = (tarray[0][0] + tarray[1][0])/2.0
        ryavg = (rarray[0][1] + rarray[1][1])/2.0
        tyavg = (tarray[0][1] + tarray[1][1])/2.0
        xshift = rxavg - txavg
        yshift = ryavg - tyavg
        rdist = math.sqrt((rarray[0][0] - rarray[1][0])**2 + (rarray[0][1] - rarray[1][1])**2)
        tdist = math.sqrt((tarray[0][0] - tarray[1][0])**2 + (tarray[0][1] - tarray[1][1])**2)
        if rdist == 0.0 or tdist ==0.0: scale = 1.0
        else: scale = tdist/rdist
        rangle = math.atan2(rarray[0][1] - rarray[1][1],rarray[0][0] - rarray[1][0])
        tangle = math.atan2(tarray[0][1] - tarray[1][1],tarray[0][0] - tarray[1][0])
        angle = rangle - tangle

        # The rotation and scale should be about the average
        
        minus = [[1.0, 0.0, 0.0],
                 [0.0, 1.0, 0.0],
                 [-txavg, -tyavg, 1.0]]
        plus = [[1.0, 0.0, 0.0],
                 [0.0, 1.0, 0.0],
                 [txavg, tyavg, 1.0]]
        mrotation = [[+math.cos(angle),+math.sin(angle), 0.0],
                    [-math.sin(angle),+math.cos(angle), 0.0],
                    [0.0             ,0.0             , 1.0]]
        mscale = [[1./scale, 0.0, 0.0],
                 [0.0, 1./scale, 0.0],
                 [0.0,0.0,1.0]]
        mshift = [[1.0, 0.0, 0.0],
                  [0.0, 1.0, 0.0],
                  [xshift, yshift, 1.0]]
        
        mrotation = matrixmultiply(minus,matrixmultiply(mrotation,plus))
        mscale = matrixmultiply(minus,matrixmultiply(mscale,plus))
        
        transform = matrixmultiply(mscale,matrixmultiply(mrotation,mshift))
        
    else:   # number of control points is 3 or more
        # for the general case of 3 or more, use SVD to get a least squares
        # fit to the transformation.
        ##if __debug__: print 'npoints is 3 or more.'
        u,w,v = svd(tarray)
        ut = transpose(u)
        n = len(w)
        maxw = max(w)
        minw = maxw / 1.e10  # is this the right threshhold?
        wi = []
        wsmall = maxw
        for i in range(n):
            wi.append([0.0]*n)
            if w[i] > minw:
                wi[i][i] = 1.0/w[i]
                if w[i] < wsmall: wsmall=w[i]

        if wsmall and stitch: stitch.condition_number = maxw/wsmall

        b = copy.deepcopy(rarray)
        bu = matrixmultiply(ut,b)
        buw = matrixmultiply(wi,bu)
        buwv = matrixmultiply(v,buw)
        
        transform = buwv

    ##if __debug__:
    ##    print transform
    
    return list(transform)

def matrix_invert(array):
    '''Use SVD to do a matrix inversion.'''
    u,w,v = svd(array)
    ut = transpose(u)
    n = len(w)
    maxw = max(w)
    minw = maxw / 1.e10  # is this the right threshhold?
    wi = []
    for i in range(n):
        wi.append([0.0]*n)
        if w[i] > minw:
            wi[i][i] = 1.0/w[i]
    return matrixmultiply(v,matrixmultiply(wi,ut))

def xytransform(transform,x,y):
    '''Transform x,y to the new coordinate system.'''
    rx = x*transform[0][0] + y*transform[1][0] + transform[2][0]
    ry = x*transform[0][1] + y*transform[1][1] + transform[2][1]
    rh = x*transform[0][2] + y*transform[1][2] + transform[2][2]
    return rx/rh,ry/rh


def compute_control_point_errors(stitch):
    '''Compute the error on each control point based on how well it matches the transform.'''
    
    ##if __debug__: print 'This is compute control_point_errors.'
    if stitch.control_points:
        errors = []
        for i in range(stitch.npoints):
            rxp = stitch.control_points[i].x1()
            ryp = stitch.control_points[i].y1()
            txp = stitch.control_points[i].x2()
            typ = stitch.control_points[i].y2()
            # matrix multiply [tx,ty,1] by the transform matrix and check
            # how well it matches the reference point.
            rx,ry = xytransform(stitch.transform,txp,typ)
            errors.append(math.sqrt((rx-rxp)**2 + (ry-ryp)**2))
    else:
        errors = None
    return errors

def compute_control_point_xyerrors(stitch):
    '''Compute the error on each control point based on how well it matches the transform.'''
    
    ##if __debug__: print 'This is compute control_point_xyerrors.'
    if stitch.control_points:
        x = []
        y = []
        for i in range(stitch.npoints):
            rxp = stitch.control_points[i].x1()
            ryp = stitch.control_points[i].y1()
            txp = stitch.control_points[i].x2()
            typ = stitch.control_points[i].y2()
            # matrix multiply [tx,ty,1] by the transform matrix and check
            # how well it matches the reference point.
            rx,ry = xytransform(stitch.transform,txp,typ)
            x.append(rx-rxp)
            y.append(ry-ryp)
    else:
        x = None
        y = None
    return x,y

def rgb2hsv(rgb):
    '''Convert RGB color to HSV color.'''
    r = rgb[0]
    g = rgb[1]
    b = rgb[2]
    value = max(r,g,b)
    saturation = value - min(r,g,b)
    if saturation:
        if r == value:
            hue = float(g-b)/saturation
        else:
            if g == value:
                hue = 2.0 + float(b-r)/saturation
            else:
                if b == value:
                    hue = 4.0 + float(r-g)/saturation
    else:
        hue = 0.0
    hue = hue * 60.0
    if hue < 0.0: hue += 360.0
    ##if __debug__: print 'RGB,HSV: ',r,g,b,hue,saturation,value
    return (hue,saturation,value)

def color_balance(stitchobj):
    '''Balance the color between the two images at the control points.'''
    ##if __debug__: print 'this is the color_balance function'
    if (not stitchobj.colorbalance or
        stitchobj.npoints < 2 or
        not stitchobj.tlayer): return
    colors = stitchobj.colors()
    cbtests = stitchobj.cbtests()
##     max_value_change = 127      # 255 = accept all changes, 0 = reject all changes
##     max_saturation_change = 127 # 255 = accept all changes, 0 = reject all changes
##     max_hue_change = 45         # 360 = accept all changes, 0 = reject all changes
    # Must lock in 0 and 255 in the splines to keep the channel ranges.
    red = [0,0,255,255]
    green = [0,0,255,255]
    blue = [0,0,255,255]
    for i in range(len(colors)):
        c = colors[i]
        ##if __debug__: print 'color ',i,cbtests[i]
        if cbtests[i]:
            red.append(c[1][0])
            red.append(c[0][0])
            green.append(c[1][1])
            green.append(c[0][1])
            blue.append(c[1][2])
            blue.append(c[0][2])

    # for some reason gimp_curves_spline can only take 34 points,
    # 17 pairs.  2 are used up for 0 and 255, leaving 15 for the
    # control points.  So, only the first 15 control points participate.
    n = len(red)
    if n > 34:
        n=34
        red = red[0:n]
        green = green[0:n]
        blue = blue[0:n]

    if n > 4:
        gimp.pdb.gimp_curves_spline(stitchobj.tlayer,HISTOGRAM_RED,n,red)
        gimp.pdb.gimp_curves_spline(stitchobj.tlayer,HISTOGRAM_GREEN,n,green)
        gimp.pdb.gimp_curves_spline(stitchobj.tlayer,HISTOGRAM_BLUE,n,blue)

    ##if __debug__: print red,green,blue,n/2

def copy_image_to_panorama_layer(panorama,image,imglayer,name):
    '''Copy an image to a layer in the panorama with a layer mask.'''
    # Make layer in the panorama image to hold the reference and transformed images
    gimp.pdb.gimp_displays_flush()  # flush before grabbing the image data
    layer = gimp.pdb.gimp_layer_new(panorama,           # image
                                    image.width,        # width
                                    image.height,       # height
                                    image.base_type,    # type
                                    name,               # name
                                    100,                # opacity
                                    NORMAL_MODE         # layer combination mode
                                    )
    gimp.pdb.gimp_image_add_layer(panorama,layer,1)   # make new layer in panoramic
    gimp.pdb.gimp_selection_none(image)               # turn off selection so copy gets full image
    gimp.pdb.gimp_edit_copy(imglayer)                 # copy image from image layer
    gimp.pdb.gimp_floating_sel_anchor(gimp.pdb.gimp_edit_paste(layer,0)) # paste and anchor
    gimp.pdb.gimp_layer_resize_to_image_size(layer)
    gimp.pdb.gimp_layer_add_alpha(layer)              # Add alpha channel
    gimp.pdb.gimp_rect_select(panorama,0,0,image.width,image.height,CHANNEL_OP_REPLACE,0,0.0)
    mask = gimp.pdb.gimp_layer_create_mask(layer,ADD_SELECTION_MASK)
    gimp.pdb.gimp_layer_add_mask(layer,mask)          # Add layer mask
    gimp.pdb.gimp_selection_none(panorama)
    return layer,mask

def warp_image(stitchobj,progress=None,pbottom=None,ptop=None):
    '''Warp the two images into a third, merged image.'''
    
    ##if __debug__: print 'This is warp_image.'

    # calculate the dimensions of the new image
    
    rnx = stitchobj.rimage.width   # the dimensions of the old image
    rny = stitchobj.rimage.height
    tnx = stitchobj.timage.width
    tny = stitchobj.timage.height
    # find the new coordinates of the corners of the transformed image
    t00 = xytransform(stitchobj.transform,0.0,0.0)
    t10 = xytransform(stitchobj.transform,tnx,0.0)
    t01 = xytransform(stitchobj.transform,0.0,tny)
    t11 = xytransform(stitchobj.transform,tnx,tny)
    x0 = int(round(min(t00[0],t10[0],t01[0],t11[0],0.0)))  # bounding box for new image
    y0 = int(round(min(t00[1],t10[1],t01[1],t11[1],0.0)))
    x1 = int(round(max(t00[0],t10[0],t01[0],t11[0],rnx)))
    y1 = int(round(max(t00[1],t10[1],t01[1],t11[1],rny)))
    # xshift and yshift are the overall shift required to
    # just fit the new layers into the new image.
    xshift = -x0
    yshift = -y0
    x0 += xshift
    x1 += xshift
    y0 += yshift
    y1 += yshift
    nx = x1-x0
    ny = y1-y0
    ##if __debug__: print 'x0,y0,x1,y1,nx,ny,xshift,yshift',x0,y0,x1,y1,nx,ny,xshift,yshift
    ##if __debug__: print 'interp,super,recursion,clip',stitchobj.interpolation, \
    ##                     stitchobj.supersample,stitchobj.recursion_level, \
    ##                     stitchobj.clip_result

    xshift = float(xshift)
    yshift = float(yshift)
    rtransform = [[1.0,0.0,0.0],
                  [0.0,1.0,0.0],
                  [xshift,yshift,1.0]]
    ttransform = stitchobj.transform
    ttransform[2][0] += xshift
    ttransform[2][1] += yshift

    # Make a new image to hold the panorama
    ptype = stitchobj.rimage.base_type
    stitchobj.panorama = gimp.pdb.gimp_image_new(nx,ny,ptype)
    gimp.pdb.gimp_image_undo_disable(stitchobj.panorama)

    rlayer,rmask = copy_image_to_panorama_layer(stitchobj.panorama,stitchobj.rimage,stitchobj.rimglayer,'reference layer')
    tlayer,tmask = copy_image_to_panorama_layer(stitchobj.panorama,stitchobj.timage,stitchobj.timglayer,'transformed layer')

    #gimp.pdb.gimp_progress_init('Stitching Panorama',-1)
    #gimp.pdb.gimp_displays_flush()

    if xshift !=0 or yshift !=0:
        #gimp.pdb.gimp_progress_init('Shifting Reference Layer',-1)
        gimp.pdb.gimp_displays_flush()
        ##if __debug__: print 'shifting reference layer',rtransform
        for rdrawable in (rlayer,rmask):
            # shift the reference layer and mask if necessary
            gimp.pdb.gimp_drawable_transform_matrix(rdrawable,
                                                    rtransform[0][0],rtransform[1][0],rtransform[2][0],
                                                    rtransform[0][1],rtransform[1][1],rtransform[2][1],
                                                    rtransform[0][2],rtransform[1][2],rtransform[2][2],
                                                    TRANSFORM_FORWARD,
                                                    stitchobj.interpolation,
                                                    stitchobj.supersample,
                                                    stitchobj.recursion_level,
                                                    stitchobj.clip_result)
    update_progress_bar(progress,'Warping Images',(pbottom+ptop)/2.0)
    ##if __debug__: print 'warping transformed layer: ',ttransform
    #gimp.pdb.gimp_progress_init('Warping Transformed Layers',-1)
    gimp.pdb.gimp_displays_flush()
    for tdrawable in (tlayer,tmask):
        # warp the transformed layer and mask
        gimp.pdb.gimp_drawable_transform_matrix(tdrawable,
                                                ttransform[0][0],ttransform[1][0],ttransform[2][0],
                                                ttransform[0][1],ttransform[1][1],ttransform[2][1],
                                                ttransform[0][2],ttransform[1][2],ttransform[2][2],
                                                TRANSFORM_FORWARD,
                                                stitchobj.interpolation,
                                                stitchobj.supersample,
                                                stitchobj.recursion_level,
                                                stitchobj.clip_result)

    # Resize the layers to circumscribe the transformed images
    gimp.pdb.gimp_layer_resize(rlayer,rnx,rny,-xshift,-yshift)
    tx0 = int(round(min(t00[0]+xshift,t10[0]+xshift,t01[0]+xshift,t11[0]+xshift)))
    ty0 = int(round(min(t00[1]+yshift,t10[1]+yshift,t01[1]+yshift,t11[1]+yshift)))
    tx1 = int(round(max(t00[0]+xshift,t10[0]+xshift,t01[0]+xshift,t11[0]+xshift)))
    ty1 = int(round(max(t00[1]+yshift,t10[1]+yshift,t01[1]+yshift,t11[1]+yshift)))
    gimp.pdb.gimp_layer_resize(tlayer,tx1-tx0,ty1-ty0,-tx0,-ty0)    
    update_progress_bar(progress,'Warping Images',ptop)

    stitchobj.rlayer = rlayer
    stitchobj.tlayer = tlayer
    stitchobj.rmask = rmask
    stitchobj.tmask = tmask
    stitchobj.rxy = [xshift,yshift,xshift+rnx,yshift+rny]
    stitchobj.txy = [tx0,ty0,tx1,ty1]

def gradient_layer_mask(stitchobj,sprog,eprog):
    '''Add a gradient layer mask to gently blend the edges of the panorama.'''

    ##if __debug__: print 'this is the gradient layer mask function.'
    if not stitchobj.blend: return
    if not stitchobj.rxy or not stitchobj.txy or not stitchobj.rmask:
        error_message('Error: cannot blend layers.',stitchobj.mode)
        return

    ##if __debug__: print stitchobj.rxy,stitchobj.txy
    
    # Find the overlap between the layers and put a gradient in the
    # reference layer mask.

    rx = (stitchobj.rxy[0]+stitchobj.rxy[2])/2.0
    ry = (stitchobj.rxy[1]+stitchobj.rxy[3])/2.0
    tx = (stitchobj.txy[0]+stitchobj.txy[2])/2.0
    ty = (stitchobj.txy[1]+stitchobj.txy[3])/2.0

    if stitchobj.rxy[0] < stitchobj.txy[0]:     # reference is left of transformed
        xfinish = stitchobj.txy[0]
        xstarts = stitchobj.rxy[2]
    else:                                       # reference is right of transformed
        xstarts = stitchobj.rxy[0]
        xfinish = stitchobj.txy[2]
    if stitchobj.rxy[1] < stitchobj.txy[1]:     # reference is above transformed
        yfinish = stitchobj.txy[1]
        ystarts = stitchobj.rxy[3]
    else:                                       # reference is below transformed
        ystarts = stitchobj.rxy[1]
        yfinish = stitchobj.txy[3]

    foreground = gimp.pdb.gimp_context_get_foreground()
    background = gimp.pdb.gimp_context_get_background()

    ##if __debug__: print 'foreground, background: ',foreground,background

    # set colors for the blend to black and white.  Will restore later.
    gimp.pdb.gimp_context_set_foreground((0,0,0))
    gimp.pdb.gimp_context_set_background((255,255,255))

    x0 = min(xstarts,xfinish)
    width = max(xstarts,xfinish)-x0
    y0 = min(ystarts,yfinish)
    height = max(ystarts,yfinish)-y0

    ##if __debug__: print 'blend selection: ',x0,x0+width,y0,y0+height
    
    # Select the overlap region so that the layer mask only applies
    # there.  Unselect any bits of the transformed mask that are
    # not transparant so that the reference image will always be visible
    # in those bits.
    gimp.pdb.gimp_selection_none(stitchobj.panorama)
    gimp.pdb.gimp_rect_select(stitchobj.panorama,
                              x0,
                              y0,
                              width,
                              height,
                              CHANNEL_OP_REPLACE,
                              0,0.0)
    gimp.pdb.gimp_by_color_select(stitchobj.tmask,
                                  gimp.pdb.gimp_context_get_background(), # color
                                  5,      # threshold
                                  CHANNEL_OP_INTERSECT,  # operation
                                  False,  # antialias
                                  0,      # feather
                                  0.0,    # feather radius
                                  0)      # sample merged

    gimp.pdb.gimp_drawable_fill(stitchobj.rmask,BACKGROUND_FILL)
    
    max_blend_size = width*stitchobj.blend_fraction
    
    x1 = xstarts
    if xstarts > xfinish:
        size = min(xstarts-xfinish,max_blend_size)
        x2 = xstarts - size
    else:
        size = min(xfinish-xstarts,max_blend_size)
        x2 = xstarts + size
    y1 = (ystarts+yfinish)/2.0
    y2 = (ystarts+yfinish)/2.0

    ##if __debug__: print 'reference x blend: ',x1,x2,y1,y2
    
    gimp.pdb.gimp_displays_flush()

    gimp.pdb.gimp_edit_blend(stitchobj.rmask,
                             FG_BG_RGB_MODE,        # blend mode
                             NORMAL_MODE,           # paint mode
                             GRADIENT_LINEAR,       # gradient type
                             100.0,                 # opacity
                             0.0,                   # offset
                             REPEAT_NONE,           # repeat
                             False,                 # reverse
                             0,                     # supersample
                             3,                     # recursion levels for super sample
                             0.0,                   # threshhold for super sample
                             True,                  # dither
                             x1-stitchobj.rxy[0],   # x1
                             y1-stitchobj.rxy[1],   # y1
                             x2-stitchobj.rxy[0],   # x2
                             y2-stitchobj.rxy[1])   # y2

    update_progress_bar(stitchobj.progressbar,'Blending Images',sprog+(eprog-sprog)*0.25)

    max_blend_size = height*stitchobj.blend_fraction
    y1 = ystarts
    if ystarts > yfinish:
        size = min(ystarts-yfinish,max_blend_size)
        y2 = ystarts - size
    else:
        size = min(yfinish-ystarts,max_blend_size)
        y2 = ystarts + size
    x1 = (xstarts+xfinish)/2.0
    x2 = (xstarts+xfinish)/2.0
    
    ##if __debug__: print 'reference y blend: ',x1,x2,y1,y2

    gimp.pdb.gimp_displays_flush()

    gimp.pdb.gimp_edit_blend(stitchobj.rmask,
                             FG_BG_RGB_MODE,        # blend mode
                             MULTIPLY_MODE,          # paint mode
                             GRADIENT_LINEAR,       # gradient type
                             100.0,                 # opacity
                             0.0,                   # offset
                             REPEAT_NONE,           # repeat
                             False,                 # reverse
                             0,                     # supersample
                             3,                     # recursion levels for super sample
                             0.0,                   # threshhold for super sample
                             False,                 # dither
                             x1-stitchobj.rxy[0],   # x1
                             y1-stitchobj.rxy[1],   # y1
                             x2-stitchobj.rxy[0],   # x2
                             y2-stitchobj.rxy[1])   # y2
    
    update_progress_bar(stitchobj.progressbar,'Blending Images',sprog+(eprog-sprog)*0.5)

    blend_size_divisor = 3.0

    # use height here even though the blend is horizontal since
    # we are modifying the vertical blend.
    max_blend_size = height*stitchobj.blend_fraction/blend_size_divisor
    
    x1 = xfinish
    if xfinish > xstarts:
        size = min(xfinish-xstarts,max_blend_size)
        x2 = x1 - size
    else:
        size = min(xstarts-xfinish,max_blend_size)
        x2 = x1 + size
    y1 = (ystarts+yfinish)/2.0
    y2 = (ystarts+yfinish)/2.0

    ##if __debug__: print 'reference x blend: ',x1,x2,y1,y2
    
    gimp.pdb.gimp_displays_flush()

    gimp.pdb.gimp_edit_blend(stitchobj.rmask,
                             FG_BG_RGB_MODE,        # blend mode
                             SCREEN_MODE,           # paint mode
                             GRADIENT_LINEAR,       # gradient type
                             100.0,                 # opacity
                             0.0,                   # offset
                             REPEAT_NONE,           # repeat
                             True,                  # reverse
                             0,                     # supersample
                             3,                     # recursion levels for super sample
                             0.0,                   # threshhold for super sample
                             False,                 # dither
                             x1-stitchobj.rxy[0],   # x1
                             y1-stitchobj.rxy[1],   # y1
                             x2-stitchobj.rxy[0],   # x2
                             y2-stitchobj.rxy[1])   # y2
    
    update_progress_bar(stitchobj.progressbar,'Blending Images',sprog+(eprog-sprog)*0.75)

    # use width here even though the blend is vertical since
    # we are modifying the horizontal blend.
    max_blend_size = width*stitchobj.blend_fraction/blend_size_divisor
    
    y1 = yfinish
    if yfinish > ystarts:
        size = min(yfinish-ystarts,max_blend_size)
        y2 = y1 - size
    else:
        size = min(ystarts-yfinish,max_blend_size)
        y2 = y1 + size
    x1 = (xstarts+xfinish)/2.0
    x2 = (xstarts+xfinish)/2.0
    
    ##if __debug__: print 'reference y blend: ',x1,x2,y1,y2

    gimp.pdb.gimp_displays_flush()

    gimp.pdb.gimp_edit_blend(stitchobj.rmask,
                             FG_BG_RGB_MODE,        # blend mode
                             SCREEN_MODE,           # paint mode
                             GRADIENT_LINEAR,       # gradient type
                             100.0,                 # opacity
                             0.0,                   # offset
                             REPEAT_NONE,           # repeat
                             True,                  # reverse
                             0,                     # supersample
                             3,                     # recursion levels for super sample
                             0.0,                   # threshhold for super sample
                             False,                 # dither
                             x1-stitchobj.rxy[0],   # x1
                             y1-stitchobj.rxy[1],   # y1
                             x2-stitchobj.rxy[0],   # x2
                             y2-stitchobj.rxy[1])   # y2
    
    update_progress_bar(stitchobj.progressbar,'Blending Images',sprog+(eprog-sprog)*1.0)

    gimp.pdb.gimp_selection_none(stitchobj.panorama)
    gimp.pdb.gimp_context_set_foreground(foreground)   # restore the foreground color
    gimp.pdb.gimp_context_set_background(background)   # restore the background color
    gimp.pdb.gimp_displays_flush()


def draw_control_points(stitchobj):
    '''Draw circles around the control points to indicate their locations.'''

    ##if __debug__: print 'This is draw_control_points.'

    if not stitchobj.control_points and not stitchobj.rcplayer and not stitchobj.tcplayer: return
    
    if not stitchobj.rcplayer:
        stitchobj.rcplayer = gimp.pdb.gimp_layer_new(stitchobj.rimage,              # image
                                                     stitchobj.rimage.width,        # width
                                                     stitchobj.rimage.height,       # height
                                                     stitchobj.rimage.base_type,    # type
                                                     'Control Points',              # name
                                                     100,                 # opacity
                                                     NORMAL_MODE         # layer combination mode
                                                     )
        gimp.pdb.gimp_image_add_layer(stitchobj.rimage,stitchobj.rcplayer,0)
        gimp.pdb.gimp_layer_add_alpha(stitchobj.rcplayer)              # Add alpha channel
        gimp.pdb.gimp_rect_select(stitchobj.rimage,0,0,stitchobj.rimage.width,
                                  stitchobj.rimage.height,CHANNEL_OP_REPLACE,0,0.0)
        stitchobj.rcpmask = gimp.pdb.gimp_layer_create_mask(stitchobj.rcplayer,ADD_SELECTION_MASK)
        gimp.pdb.gimp_layer_add_mask(stitchobj.rcplayer,stitchobj.rcpmask)          # Add layer mask
        gimp.pdb.gimp_selection_none(stitchobj.rimage)

    if not stitchobj.tcplayer:
        stitchobj.tcplayer = gimp.pdb.gimp_layer_new(stitchobj.timage,              # image
                                                     stitchobj.timage.width,        # width
                                                     stitchobj.timage.height,       # height
                                                     stitchobj.timage.base_type,    # type
                                                     'Control Points',              # name
                                                     100,                 # opacity
                                                     NORMAL_MODE         # layer combination mode
                                                     )
        gimp.pdb.gimp_image_add_layer(stitchobj.timage,stitchobj.tcplayer,0)
        gimp.pdb.gimp_layer_add_alpha(stitchobj.tcplayer)              # Add alpha channel
        gimp.pdb.gimp_rect_select(stitchobj.timage,0,0,stitchobj.timage.width,
                                  stitchobj.timage.height,CHANNEL_OP_REPLACE,0,0.0)
        stitchobj.tcpmask = gimp.pdb.gimp_layer_create_mask(stitchobj.tcplayer,ADD_SELECTION_MASK)
        gimp.pdb.gimp_layer_add_mask(stitchobj.tcplayer,stitchobj.tcpmask)          # Add layer mask
        gimp.pdb.gimp_selection_none(stitchobj.timage)

    gimp.pdb.gimp_selection_none(stitchobj.rimage)
    gimp.pdb.gimp_selection_none(stitchobj.timage)
    foreground = gimp.pdb.gimp_context_get_foreground()
    background = gimp.pdb.gimp_context_get_background()
    gimp.pdb.gimp_context_set_foreground((0,0,0))
    gimp.pdb.gimp_context_set_background((255,0,0))
    gimp.pdb.gimp_drawable_fill(stitchobj.rcplayer,BACKGROUND_FILL)  # erase
    gimp.pdb.gimp_drawable_fill(stitchobj.tcplayer,BACKGROUND_FILL)
    gimp.pdb.gimp_drawable_fill(stitchobj.rcpmask,FOREGROUND_FILL)  # erase
    gimp.pdb.gimp_drawable_fill(stitchobj.tcpmask,FOREGROUND_FILL)
    gimp.pdb.gimp_context_set_background((255,255,255))
    
    radius = 10.0
    
    if stitchobj.control_points:
    
        for cp in stitchobj.control_points:
            rx = cp.x1()
            ry = cp.y1()
            tx = cp.x2()
            ty = cp.y2()
            ##if __debug__: print rx,ry,tx,ty,radius,rx+radius,ry+radius
            gimp.pdb.gimp_ellipse_select(stitchobj.rimage,       # image
                                         rx-radius,              # x
                                         ry-radius,              # y
                                         radius*2,               # width
                                         radius*2,               # height
                                         CHANNEL_OP_REPLACE,     # mode
                                         True,                   # antialias
                                         False,                  # feather
                                         0.0)                    # feather radius
            gimp.pdb.gimp_edit_bucket_fill(stitchobj.rcpmask,
                                           BG_BUCKET_FILL,       # fill mode
                                           NORMAL_MODE,          # paint mode
                                           30.0,                 # opacity
                                           0.0,                  # threshhold
                                           0,                    # sample merged
                                           0.0,                  # x if no selection
                                           0.0)                  # y if no selection
            gimp.pdb.gimp_ellipse_select(stitchobj.timage,
                                         tx-radius,              # x
                                         ty-radius,              # y
                                         radius*2,               # width
                                         radius*2,               # height
                                         CHANNEL_OP_REPLACE,     # mode
                                         False,                  # antialias
                                         False,                  # feather
                                         0.0)                    # feather radius
            gimp.pdb.gimp_edit_bucket_fill(stitchobj.tcpmask,
                                           BG_BUCKET_FILL,
                                           NORMAL_MODE,
                                           30.0,
                                           0.0,
                                           0,
                                           0.0,
                                           0.0)
            
##             gimp.pdb.gimp_ellipse_select(stitchobj.rimage,       # image
##                                          rx-radius/4,            # x
##                                          ry-radius/4,            # y
##                                          radius/2,               # width
##                                          radius/2,               # height
##                                          CHANNEL_OP_REPLACE,     # mode
##                                          True,                   # antialias
##                                          False,                  # feather
##                                          0.0)                    # feather radius
##             gimp.pdb.gimp_edit_bucket_fill(stitchobj.rcpmask,
##                                            FG_BUCKET_FILL,       # fill mode
##                                            NORMAL_MODE,          # paint mode
##                                            30.0,                 # opacity
##                                            0.0,                  # threshhold
##                                            0,                    # sample merged
##                                            0.0,                  # x if no selection
##                                            0.0)                  # y if no selection
##             gimp.pdb.gimp_ellipse_select(stitchobj.timage,
##                                          tx-radius/4,            # x
##                                          ty-radius/4,            # y
##                                          radius/2,               # width
##                                          radius/2,               # height
##                                          CHANNEL_OP_REPLACE,     # mode
##                                          False,                  # antialias
##                                          False,                  # feather
##                                          0.0)                    # feather radius
##             gimp.pdb.gimp_edit_bucket_fill(stitchobj.tcpmask,
##                                            FG_BUCKET_FILL,
##                                            NORMAL_MODE,
##                                            30.0,
##                                            0.0,
##                                            0,
##                                            0.0,
##                                            0.0)
        
    gimp.pdb.gimp_context_set_foreground(foreground)
    gimp.pdb.gimp_context_set_background(background)
    gimp.pdb.gimp_selection_none(stitchobj.rimage)
    gimp.pdb.gimp_selection_none(stitchobj.timage)
    gimp.pdb.gimp_displays_flush()


## def on_same_side(xp0,yp0,xk0,yk0,xi0,yi0,xj0,yj0):
##     '''Is p on the same side as k of line i,j.'''
##     # shift xj,yj to 0,0
##     xp = xp0 - xj0
##     yp = yp0 - yj0
##     xk = xk0 - xj0
##     yk = yk0 - yj0
##     xi = xi0 - xj0
##     yi = yi0 - yj0
##     # rotate line i,j to horizontal
##     a = -math.atan2(yi,xi)
##     #xpr = +xp*math.cos(a)+yp*math.sin(a)
##     ypr = -xp*math.sin(a)+yp*math.cos(a)
##     #xkr = +xk*math.cos(a)+yk*math.sin(a)
##     ykr = -xk*math.sin(a)+yk*math.cos(a)
##     # Since the line is horizontal, do ypr and ykr have same sign?
##     if ypr != 0.0: psign = ypr/abs(ypr)
##     else: psign = 1.0
##     if ykr != 0.0: ksign = ykr/abs(ykr)
##     else: ksign = 1.0
##     if abs(psign-ksign) < 1.0: return True
##     return False

## def is_inside_triangle(tarr,p,i,j,k):
##     '''Check if point tarr[p] is inside triangle tarr[i],tarr[j],tarr[k].'''
    
##     xi = tarr[i][0]
##     yi = tarr[i][1]
    
##     xj = tarr[j][0]
##     yj = tarr[j][1]
    
##     xk = tarr[k][0]
##     yk = tarr[k][1]

##     xp = tarr[p][0]
##     yp = tarr[p][1]
    
##     # is p on the k side of line i,j?
##     inside_ij = on_same_side(xp,yp,xk,yk,xi,yi,xj,yj)
##     # is p on the j side of line i,k?
##     inside_ik = on_same_side(xp,yp,xj,yj,xi,yi,xk,yk)
##     # is p on the i side of line j,k?
##     inside_jk = on_same_side(xp,yp,xi,yi,xj,yj,xk,yk)

##     if inside_ij and inside_ik and inside_jk:
##         return True
    
##     return False


def get_triangle_center(x1,y1,x2,y2,x3,y3):
    '''Find center of the circle that circumscribes a triangle.'''
    # The center of the circumscribing circle is at the intersection
    # of the perpendicular bisectors of the edges.
    # get bisector 1
    mx1 = (x2+x3)/2.0
    my1 = (y2+y3)/2.0
    if my1 != y2:
        b1 = -(mx1-x2)/(my1-y2) # slope
        a1 = my1 - b1*mx1
        vertical1 = False
    else:
        vertical1 = True
    # get bisector 2
    mx2 = (x1+x3)/2.0
    my2 = (y1+y3)/2.0
    if my2 != y3:
        b2 = -(mx2-x3)/(my2-y3) # slope
        a2 = my2 - b2*mx2
        vertical2 = False
    else:
        vertical2 = True
    # get bisector 3
    mx3 = (x1+x2)/2.0
    my3 = (y1+y2)/2.0
    if my3 != y2:
        b3 = -(mx3-x2)/(my3-y2) # slope
        a3 = my3 - b3*mx3
        vertical3 = False
    else:
        vertical3 = True
    # these should all give the same answer
    if not vertical1 and not vertical2 and b2!=b1:
        xcenter = (a1-a2)/(b2-b1)
        ycenter = a1+b1*xcenter
    if not vertical1 and not vertical3 and b3!=b1:
        xcenter = (a1-a3)/(b3-b1)
        ycenter = a1+b1*xcenter
    if not vertical3 and not vertical2 and b2!=b3:
        xcenter = (a3-a2)/(b2-b3)
        ycenter = a3+b3*xcenter
    return (xcenter,ycenter)
        
def is_delaunay_triangle(tarr,i,j,k):
    '''Check if a triangle is a Delaunay triangle.'''
    
    # The Delaunay triangulation is defined as the set of triangles
    # whose circumscribing circles are otherwise empty.  So, find
    # the circumcirce and check if it is empty.  Return True if this
    # is a Delaunay triangle.
    
    npoints = len(tarr)
    xcenter,ycenter = get_triangle_center(tarr[i][0],tarr[i][1],
                                          tarr[j][0],tarr[j][1],
                                          tarr[k][0],tarr[k][1])
    # these radii should all be the same.
    radius = min([math.sqrt((xcenter-tarr[i][0])**2 + (ycenter-tarr[i][1])**2),
                  math.sqrt((xcenter-tarr[j][0])**2 + (ycenter-tarr[j][1])**2),
                  math.sqrt((xcenter-tarr[k][0])**2 + (ycenter-tarr[k][1])**2)])
##     if __debug__:
##         print 'triangle, check same', \
##               math.sqrt((xcenter-tarr[i][0])**2 + (ycenter-tarr[i][1])**2),\
##               math.sqrt((xcenter-tarr[j][0])**2 + (ycenter-tarr[j][1])**2),\
##               math.sqrt((xcenter-tarr[k][0])**2 + (ycenter-tarr[k][1])**2)
    for p in range(npoints):
        if p != i and p != j and p != k:
            # Check if there is a point inside the cicumscribing circle.
            x = tarr[p][0]
            y = tarr[p][1]
            distance = math.sqrt((xcenter-x)**2 + (ycenter-y)**2)
            if distance < radius: return False
    return True
    
def triangulate(tarr):
    '''Split the area covered by tarr into simple triangles.'''

    npoints = len(tarr)
    ntriangles = 0
    # find all the triangles
    for i in range(npoints):
        for j in range(npoints):
            if j > i:
                for k in range(npoints):
                    if k > i and k > j:
                        dt = is_delaunay_triangle(tarr,i,j,k)
                        if dt:
                            if ntriangles == 0:
                                triangles = [[i,j,k]]
                            else:
                                triangles.append([i,j,k])
                            ntriangles += 1
                        ##if __debug__:
                        ##    if dt: print i,j,k,' is Delaunay.'
##     if __debug__:
##         print 'Triangulate: ',ntriangles,' triangles'
##         widget=MessageWidget('Debug: press ok to continue.')
##         widget.main()                    
        
    return triangles


def remove_distortion(stitchobj,progress=None,pbottom=None,ptop=None):
    '''Remove any remaining non-linear distortion.'''
    
    ##if __debug__: print 'This is remove_distortion.'

    if stitchobj.rmdistortion and stitchobj.npoints > 3:
        
        stitchobj.dimage = gimp.pdb.gimp_image_new(stitchobj.timage.width,stitchobj.timage.height,RGB)
        dlayer = gimp.pdb.gimp_layer_new_from_drawable(stitchobj.timglayer,stitchobj.dimage)
        tlayer = gimp.pdb.gimp_layer_new_from_drawable(stitchobj.timglayer,stitchobj.dimage)
        gimp.pdb.gimp_image_add_layer(stitchobj.dimage,dlayer,0)
        gimp.pdb.gimp_image_add_layer(stitchobj.dimage,tlayer,1)  # temporary layer must be on top

        try:

            tpixels = tlayer.get_pixel_rgn(0,0,               # x,y
                                           tlayer.width, tlayer.height, # width,height
                                           TRUE,              # changes applied to layer
                                           FALSE)             # Shadow
            dpixels = dlayer.get_pixel_rgn(0,0,               # x,y
                                           dlayer.width, dlayer.height, # width,height
                                           TRUE,              # changes applied to layer
                                           FALSE)             # Shadow
            tpsave = tpixels[0:tlayer.width,0:tlayer.height]

            rarr,ttarr = stitchobj.arrays()                        # the control points
            tarr = copy.deepcopy(ttarr)
            xerr,yerr = compute_control_point_xyerrors(stitchobj) # the control point errors
            # add corners to tarr to make sure they are fixed
            c1 = [0.0,0.0,1.0]
            c2 = [0.0,dlayer.height,1.0]
            c3 = [dlayer.width,0.0,1.0]
            c4 = [dlayer.width,dlayer.height,1.0]
            tarr.append(c1)
            tarr.append(c2)
            tarr.append(c3)
            tarr.append(c4)
            xerr.append(0.0)
            xerr.append(0.0)
            xerr.append(0.0)
            xerr.append(0.0)
            yerr.append(0.0)
            yerr.append(0.0)
            yerr.append(0.0)
            yerr.append(0.0)
            triangles = triangulate(tarr) # Get Delaunay triangulation
            #gimp.pdb.gimp_progress_init('Removing distortion',-1)
            ntriangles = len(triangles)
            for i in range(ntriangles):
                ss0 = triangles[i][0]
                ss1 = triangles[i][1]
                ss2 = triangles[i][2]
                ##if __debug__: print tarr[ss0][0],tarr[ss0][1],tarr[ss1][0],tarr[ss1][1],tarr[ss2][0],tarr[ss2][1]
                ##if __debug__: print ss0,ss1,ss2,xerr[ss0],yerr[ss0],xerr[ss1],yerr[ss1],xerr[ss2],yerr[ss2]
                # get warping for triangle
                rnew = [[tarr[ss0][0]-xerr[ss0],tarr[ss0][1]-yerr[ss0]],
                        [tarr[ss1][0]-xerr[ss1],tarr[ss1][1]-yerr[ss1]],
                        [tarr[ss2][0]-xerr[ss2],tarr[ss2][1]-yerr[ss2]]]
                rtri = [[tarr[ss0][0]-xerr[ss0],tarr[ss0][1]-yerr[ss0],1.0],
                        [tarr[ss1][0]-xerr[ss1],tarr[ss1][1]-yerr[ss1],1.0],
                        [tarr[ss2][0]-xerr[ss2],tarr[ss2][1]-yerr[ss2],1.0]]
                ttri = [[tarr[ss0][0],          tarr[ss0][1],          1.0],
                        [tarr[ss1][0],          tarr[ss1][1],          1.0],
                        [tarr[ss2][0],          tarr[ss2][1],          1.0]]
                transform = compute_transform_matrix(rtri,ttri)
                # warp image
                # select only the required area for transformation - more efficient
                # than transforming the whole image.
                maxerr = max([abs(xerr[ss0]),abs(xerr[ss1]),abs(xerr[ss2]),
                              abs(yerr[ss0]),abs(yerr[ss1]),abs(yerr[ss2])])*2.0+5.0
                x0 = max([min([rnew[0][0],rnew[1][0],rnew[2][0]])-maxerr,0.0])
                y0 = max([min([rnew[0][1],rnew[1][1],rnew[2][1]])-maxerr,0.0])
                x1 = min([max([rnew[0][0],rnew[1][0],rnew[2][0]])+maxerr,stitchobj.dimage.width-1])
                y1 = min([max([rnew[0][1],rnew[1][1],rnew[2][1]])+maxerr,stitchobj.dimage.height-1])
                gimp.pdb.gimp_selection_none(stitchobj.dimage)
                gimp.pdb.gimp_rect_select(stitchobj.dimage,  # image
                                          x0,       # x
                                          y0,       # y
                                          x1-x0+1,  # width
                                          y1-y0+1,  # height
                                          2,        # replace
                                          0,        # feather
                                          0.)       # radius
                gimp.pdb.gimp_drawable_transform_matrix(tlayer,
                                                transform[0][0],transform[1][0],transform[2][0],
                                                transform[0][1],transform[1][1],transform[2][1],
                                                transform[0][2],transform[1][2],transform[2][2],
                                                TRANSFORM_FORWARD,
                                                stitchobj.interpolation,
                                                stitchobj.supersample,
                                                stitchobj.recursion_level,
                                                stitchobj.clip_result)
                flayer = gimp.pdb.gimp_image_get_floating_sel(stitchobj.dimage)
                gimp.pdb.gimp_floating_sel_anchor(flayer)
                # select triangle
                for j in range(len(rtri)):   # make sure the indices are in range
                    if rnew[j][0] < 0.0: rnew[j][0] = 0.0
                    if rnew[j][0] > dlayer.width-1: rnew[j][0] = dlayer.width-1
                    if rnew[j][1] < 0.0: rnew[j][1] = 0.0
                    if rnew[j][1] > dlayer.height-1: rnew[j][1] = dlayer.height-1
                gimp.pdb.gimp_selection_none(stitchobj.dimage)
                gimp.pdb.gimp_free_select(stitchobj.dimage,    # image
                                          6,                   # n points
                                          [rnew[0][0],rnew[0][1],
                                           rnew[1][0],rnew[1][1],
                                           rnew[2][0],rnew[2][1]],   # point list
                                          2,                   # replace
                                          1,                   # antialias
                                          1,                   # feather
                                          2.0)                 # feather radius
                # insert triangle into undistorted image (dlayer)
                gimp.pdb.gimp_edit_copy(tlayer)
                gimp.pdb.gimp_floating_sel_anchor(gimp.pdb.gimp_edit_paste(dlayer,0))
                gimp.pdb.gimp_selection_none(stitchobj.dimage)
                # reset temporary layer for next transform
                tpixels[0:tlayer.width, 0:tlayer.height] = tpsave
                #gimp.pdb.gimp_progress_update(float(i+1.0)/ntriangles)
                if progress:
                    update_progress_bar(progress,
                                        'Removing Distortion',
                                        pbottom+(ptop-pbottom)*((i+1.0)/ntriangles))

            # set the transformed layer to the distortion free layer.  Hence the
            # undistorted layer will be used from now on as the transformed
            # image as it is warped onto the reference image, color balanced, etc.
            stitchobj.timglayer = dlayer
            stitchobj.timage = stitchobj.dimage

        finally:
            # clean up
            gimp.pdb.gimp_selection_none(stitchobj.dimage)
            gimp.pdb.gimp_image_remove_layer(stitchobj.dimage,tlayer)


def go_stitch_panorama(stitchobj):
    '''Stitch the panorama.'''

    # save control points before we call remove_distortion
    # which will change the transformed image to a temorary
    # image (stitcobj.dimage)
    if stitchobj.control_points:
        save_control_points_to_parasite(stitchobj)
            
    if stitchobj.transform:

        # Remove and flush out the control point displays
        if stitchobj.rcplayer:
            gimp.pdb.gimp_image_remove_layer(stitchobj.rimage,stitchobj.rcplayer)
            stitchobj.rcplayer = None
        if stitchobj.tcplayer:
            gimp.pdb.gimp_image_remove_layer(stitchobj.timage,stitchobj.tcplayer)
            stitchobj.tcplayer = None
        update_image_layers(stitchobj.rimage)
        update_image_layers(stitchobj.timage)
        gimp.pdb.gimp_displays_flush()

        update_progress_bar(stitchobj.progressbar,'Removing Distortion',0.00)
        remove_distortion(stitchobj,stitchobj.progressbar,0.,0.25) # remove non-linear distortion
        update_progress_bar(stitchobj.progressbar,'Warping Images',0.25)
        warp_image(stitchobj,stitchobj.progressbar,0.25,0.50)  # warp the second image onto the first.
        update_progress_bar(stitchobj.progressbar,'Balancing Color',0.50)
        color_balance(stitchobj)  # balance color between the two images.
        update_progress_bar(stitchobj.progressbar,'Blending Images',0.75)
        gradient_layer_mask(stitchobj,0.75,0.99)  # add a gradient layer mask to merge the edges.
        update_progress_bar(stitchobj.progressbar,'Overlaying Images',0.99)
        gimp.pdb.gimp_display_new(stitchobj.panorama)  # display the panoramic image
        update_progress_bar(stitchobj.progressbar,'',1.0)
    else:
        error_message('Error: you did not set any control points.',stitchobj.mode)

def update_progress_bar(progress,text,fraction):
    if progress:
        if text: progress.set_text(text)
        progress.set_fraction(min(fraction,1.0))
        #if __debug__: print text
        while gtk.events_pending():
            gtk.main_iteration()

#-------------------- WIDGET DEFINITIONS

class ControlPanelWidget:
    '''This is the main control panel.'''
    
    def destroy(self,widget,data=None):
        '''got a destroy signal.'''
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        '''got a delete_event signal.'''
        return gtk.FALSE
    
    def transform_table_fill(self):
        ''' Fill the transform table with the warping matrix.'''
        if self.stitch.transform:
            for i in range(3):
                for j in range(3):      
                    label = gtk.Label('%8.2f ' % self.stitch.transform[i][j])
                    self.transform_table.attach(label,j,j+1,i,i+1,
                                                    yoptions=gtk.FILL,
                                                    xoptions=gtk.FILL)
                    label.show()
            if self.stitch.condition_number:
                label = gtk.Label('Condition Number: %8.2f' % self.stitch.condition_number)
                self.transform_table.attach(label,0,3,3,4,
                                            yoptions=gtk.FILL,
                                            xoptions=gtk.FILL)
                label.show()
            
    def create_new_transform_table(self):
        '''Create and fill the table of control points in the widget.'''
        self.transform_table = gtk.Table(3,4,homogeneous=gtk.FALSE)
        self.transform_table.set_row_spacings(5)
        self.transform_table.set_col_spacings(5)
        self.scrolled_window.add_with_viewport(self.transform_table)
        self.transform_table.show()
        self.transform_table_fill()

    def cancel(self,widget,data=None):
        '''Deal with a press of the cancel button.'''
        gtk.main_quit()
        gtk.Widget.destroy(self.window)
 
    def update_transform_table(self):
        '''Redraw the control point table.'''
        gtk.Widget.destroy(self.transform_table)
        self.create_new_transform_table()

    def update_widget(self):
        '''Redraw anything that has changed in the widget.'''
        self.update_transform_table()
        self.widget_set_sensitivity()

    def add_control_points(self,widget,data=None):
        '''Call the control point editor widget.'''
        # call the user interface to get new or edit old control points
        self.stitch_button.set_sensitive(gtk.FALSE)           
        self.cancel_button.set_sensitive(gtk.FALSE)           
        self.add_button.set_sensitive(gtk.FALSE)           
        self.stitch = control_points_editor(self.stitch)
        self.update_widget()

    def stitch_panorama(self,widget,data=None):
        self.stitch_button.set_sensitive(gtk.FALSE)           
        self.cancel_button.set_sensitive(gtk.FALSE)           
        self.add_button.set_sensitive(gtk.FALSE)
        update_progress_bar(self.progressbar,'Stitching ...',0.0)
        try:
            go_stitch_panorama(self.stitch)
        finally:
            self.stitch_button.set_sensitive(gtk.TRUE)           
            self.cancel_button.set_sensitive(gtk.TRUE)           
            self.add_button.set_sensitive(gtk.TRUE)   
        gtk.Widget.destroy(self.window)
        
    def widget_set_sensitivity(self):
        '''Grey out edit,delete,save buttons if there are no control points.'''
        self.cancel_button.set_sensitive(gtk.TRUE)
        self.add_button.set_sensitive(gtk.TRUE)
        if not self.stitch.control_points:
            self.stitch_button.set_sensitive(gtk.FALSE)  # greyed out
        else:
            self.stitch_button.set_sensitive(gtk.TRUE)  # not greyed out
            
    def set_interpolation(self,combobox,data=None):
        index = combobox.get_active()
        ##if __debug__: print 'interpolation index is ',index
        if index == 0: self.stitch.interpolation = INTERPOLATION_NONE
        if index == 1: self.stitch.interpolation = INTERPOLATION_LINEAR
        if index == 2: self.stitch.interpolation = INTERPOLATION_CUBIC

    def set_blend_size(self,combobox,data=None):
        index = combobox.get_active()
        if index == 0: self.stitch.blend_fraction = 0.05
        if index == 1: self.stitch.blend_fraction = 0.10
        if index == 2: self.stitch.blend_fraction = 0.15
        if index == 3: self.stitch.blend_fraction = 0.25
        if index == 4: self.stitch.blend_fraction = 0.50
        if index == 5: self.stitch.blend_fraction = 0.75
        if index == 6: self.stitch.blend_fraction = 1.00
        ##if __debug__: print 'blend size is ',index,self.stitch.blend_fraction

    def set_color_radius(self,combobox,data=None):
        index = combobox.get_active()
        if index == 0: self.stitch.colorradius = 1.0
        if index == 1: self.stitch.colorradius = 2.0
        if index == 2: self.stitch.colorradius = 5.0
        if index == 3: self.stitch.colorradius = 10.0
        if index == 4: self.stitch.colorradius = 15.0
        if index == 5: self.stitch.colorradius = 20.0
        if index == 6: self.stitch.colorradius = 25.0
        if index == 7: self.stitch.colorradius = 50.0
        if index == 8: self.stitch.colorradius = 75.0
        if index == 9: self.stitch.colorradius = 100.0
        if index == 10: self.stitch.colorradius = 150.0
        if index == 11: self.stitch.colorradius = 200.0
        ##if __debug__: print 'color radius is ',index,self.stitch.colorradius

    def super_sample_check_event(self,check,data=None):
        if check.get_active():
            self.stitch.supersample=1
        else:
            self.stitch.supersample=0
        ##if __debug__: print 'supersample is now',self.stitch.supersample
        
    def correlate_check_event(self,check,data=None):
        if check.get_active():
            self.stitch.cpcorrelate=True
        else:
            self.stitch.cpcorrelate=False
        ##if __debug__: print 'correlation is now',self.stitch.cpcorrelate
                
                
    def blend_check_event(self,check,data=None):
        if check.get_active():
            self.stitch.blend=True
            self.bcombobox.set_sensitive(gtk.TRUE)
        else:
            self.stitch.blend=False
            self.bcombobox.set_sensitive(gtk.FALSE)
        ##if __debug__: print 'blend is now',self.stitch.blend

    def distort_check_event(self,check,data=None):
        if check.get_active():
            self.stitch.rmdistortion=True
        else:
            self.stitch.rmdistortion=False
        ##if __debug__: print 'remove distortion is now',self.stitch.rmdistortion
                
    def color_balance_check_event(self,check,data=None):
        if check.get_active():
            self.stitch.colorbalance=True
            self.ccombobox.set_sensitive(gtk.TRUE)
        else:
            self.stitch.colorbalance=False
            self.ccombobox.set_sensitive(gtk.FALSE)
        ##if __debug__: print 'color balance is now',self.stitch.colorbalance

    def __init__(self,stitch):
        '''Set up the control point editor widget.'''
        # Save control_point data
        self.stitch = stitch
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_event)
        self.window.connect("destroy",self.destroy)
        self.window.set_title('Stitch Panorama Control Panel')
        self.window.set_border_width(10)
        self.tooltips = gtk.Tooltips()
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # Give the image names
        table = gtk.Table(2,2,homogeneous=gtk.FALSE)
        table.set_row_spacings(5)
        table.set_col_spacings(5)
        label = gtk.Label('Reference Image: ')
        table.attach(label,0,1,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        label = gtk.Label(stitch.rimage.name+'-'+str(stitch.rimage.ID))
        table.attach(label,1,2,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        label = gtk.Label('Transformed Image: ')
        table.attach(label,0,1,1,2,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        label = gtk.Label(stitch.timage.name+'-'+str(stitch.timage.ID))
        table.attach(label,1,2,1,2,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        table.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # label the widget
        label = gtk.Label("Transformation Matrix")
        label.set_alignment(0,0)
        vbox.pack_start(label,gtk.FALSE,gtk.FALSE,0)
        label.show()
        # The transformation matrix display area
        self.scrolled_window = gtk.ScrolledWindow()
        self.scrolled_window.set_border_width(10)
        self.scrolled_window.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
        vbox.pack_start(self.scrolled_window,gtk.TRUE,gtk.TRUE,0)
        self.scrolled_window.show()
        # create a table of the control point data
        self.create_new_transform_table()
        # control point correlation selector
        self.correlate_check = gtk.CheckButton(label='Correlate Control Points')
        self.correlate_check.connect("toggled",self.correlate_check_event)
        if self.stitch.cpcorrelate: self.correlate_check.set_active(gtk.TRUE)
        else: self.correlate_check.set_active(gtk.FALSE)
        self.correlate_check.show()
        vbox.pack_start(self.correlate_check,gtk.FALSE,gtk.FALSE,0)
        self.tooltips.set_tip(self.correlate_check,"Maximize the correlation between "+ \
                              "the contol point selections.")
        # editing buttons, add, edit, delete
        # add button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        self.add_button = gtk.Button("Set/Edit/View Control Points")
        self.add_button.connect("clicked", self.add_control_points)
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.add_button,expand,fill,padding)
        self.tooltips.set_tip(self.add_button,"Add/Edit Control Points which will "+ \
                              "be used to define the transformation.")
        self.add_button.show()
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        hbox.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # interpolation selector
        table = gtk.Table(2,1,homogeneous=gtk.FALSE)
        table.set_row_spacings(10)
        table.set_col_spacings(10)
        label = gtk.Label("Interpolation Method:")
        table.attach(label,0,1,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        self.tcombobox = gtk.combo_box_new_text()
        self.tcombobox.append_text("None")
        self.tcombobox.append_text("Linear")
        self.tcombobox.append_text("Cubic")
        self.tcombobox.connect("changed",self.set_interpolation)
        self.tcombobox.set_active(2)
        table.attach(self.tcombobox,1,2,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        self.tcombobox.show()
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        table.show()
        # blend width selector
        table = gtk.Table(2,1,homogeneous=gtk.FALSE)
        table.set_row_spacings(10)
        table.set_col_spacings(10)
        label = gtk.Label("Blend Size:")
        table.attach(label,0,1,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        self.bcombobox = gtk.combo_box_new_text()
        self.bcombobox.append_text("5%")
        self.bcombobox.append_text("10%")
        self.bcombobox.append_text("15%")
        self.bcombobox.append_text("25%")
        self.bcombobox.append_text("50%")
        self.bcombobox.append_text("75%")
        self.bcombobox.append_text("100%")
        self.bcombobox.connect("changed",self.set_blend_size)
        self.bcombobox.set_active(2)
        table.attach(self.bcombobox,1,2,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        self.bcombobox.show()
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        table.show()
        self.tooltips.set_tip(self.bcombobox,"The size of the blend as a percentage of the image overlap.")
        # color radius selector
        table = gtk.Table(3,1,homogeneous=gtk.FALSE)
        table.set_row_spacings(10)
        table.set_col_spacings(10)
        label = gtk.Label("Color Radius:")
        table.attach(label,0,1,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        label = gtk.Label("Pixels")
        table.attach(label,2,3,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        self.ccombobox = gtk.combo_box_new_text()
        self.ccombobox.append_text("1")
        self.ccombobox.append_text("2")
        self.ccombobox.append_text("5")
        self.ccombobox.append_text("10")
        self.ccombobox.append_text("15")
        self.ccombobox.append_text("20")
        self.ccombobox.append_text("25")
        self.ccombobox.append_text("50")
        self.ccombobox.append_text("75")
        self.ccombobox.append_text("100")
        self.ccombobox.append_text("150")
        self.ccombobox.append_text("200")
        self.ccombobox.connect("changed",self.set_color_radius)
        self.ccombobox.set_active(7)
        table.attach(self.ccombobox,1,2,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        self.ccombobox.show()
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        table.show()
        self.tooltips.set_tip(self.ccombobox,"Colors are averaged over this radius during color balancing.")
        # supersample selector
        self.super_sample_check = gtk.CheckButton(label='Supersample')
        self.super_sample_check.connect("toggled",self.super_sample_check_event)
        if self.stitch.supersample: self.super_sample_check.set_active(gtk.TRUE)
        else: self.super_sample_check.set_active(gtk.FALSE)
        self.super_sample_check.show()
        vbox.pack_start(self.super_sample_check,gtk.FALSE,gtk.FALSE,0)
        # color balance selector
        self.color_balance_check = gtk.CheckButton(label='Color Balance')
        self.color_balance_check.connect("toggled",self.color_balance_check_event)
        if self.stitch.colorbalance: self.color_balance_check.set_active(gtk.TRUE)
        else: self.color_balance_check.set_active(gtk.FALSE)
        self.color_balance_check.show()
        vbox.pack_start(self.color_balance_check,gtk.FALSE,gtk.FALSE,0)
        self.tooltips.set_tip(self.color_balance_check,"Match the colors between the images.")
        # Blend selector
        self.blend_check = gtk.CheckButton(label='Blend Images')
        self.blend_check.connect("toggled",self.blend_check_event)
        if self.stitch.blend: self.blend_check.set_active(gtk.TRUE)
        else: self.blend_check.set_active(gtk.FALSE)
        self.blend_check.show()
        vbox.pack_start(self.blend_check,gtk.FALSE,gtk.FALSE,0)
        self.tooltips.set_tip(self.blend_check,"Blend the images with a layer mask.")
        # Remove distortion selector
        self.distort_check = gtk.CheckButton(label='Remove Distortion')
        self.distort_check.connect("toggled",self.distort_check_event)
        if self.stitch.rmdistortion: self.distort_check.set_active(gtk.TRUE)
        else: self.distort_check.set_active(gtk.FALSE)
        self.distort_check.show()
        vbox.pack_start(self.distort_check,gtk.FALSE,gtk.FALSE,0)
        self.tooltips.set_tip(self.distort_check,"Remove distortion in the images.")
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # stitch button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        self.stitch_button = gtk.Button("Stitch Panorama")
        self.stitch_button.connect("clicked", self.stitch_panorama)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.stitch_button,expand,fill,padding)
        self.stitch_button.show()
        self.tooltips.set_tip(self.stitch_button,"Compute the panorama.")
        # cancel button
        self.cancel_button = gtk.Button("Cancel")
        self.cancel_button.connect("clicked", self.cancel)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.cancel_button,expand,fill,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        self.cancel_button.show()
        hbox.show()
        # Progress bar
        hbox = gtk.HBox(gtk.TRUE,5)
        self.progressbar = gtk.ProgressBar()
        self.stitch.progressbar = self.progressbar
        hbox.pack_start(self.progressbar,expand,gtk.TRUE,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,10)
        self.progressbar.show()
        hbox.show()
        self.progressbar.set_text('')
        self.progressbar.set_fraction(0.0)
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
        self.widget_set_sensitivity()
    def main(self):
        gtk.main()


class ImageSelectorWidget:
    '''Widget to select the reference and transformed images.'''
    def destroy(self,widget,data=None):
        '''got a destroy signal.'''
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        '''got a delete_event signal.'''
        return gtk.FALSE

    def go_image_set(self,combobox,title,i):
        '''Callback function to deal with the image menu selection.'''
        index = combobox.get_active()
        if index > len(self.full_image_list)-1:
            # Read from file
            widget = FileSelector("Select "+title+" Image",self.filename)
            widget.main()
            if widget.filename:
                ##if __debug__: print widget.filename
                self.filename = widget.filename
                try:
                    self.image_list[i] = gimp.pdb.gimp_file_load(widget.filename,
                                                                 self.mode)
                    gimp.pdb.gimp_display_new(self.image_list[i])
                except IOError:
                    error_message('Could not read file '+widget.filename)
                    self.image_list[i] = None
            else:
                error_message('Could not grok file name',self.mode)
                self.image_list[i] = None
        else:   
            self.image_list[i] = self.full_image_list[index]
        ##if __debug__: print title+' image set to '+str(index)
    def accept(self,widget,data=None):
        self.go_image_set(self.rcombobox,'Reference',0)
        time.sleep(0.1)
        self.go_image_set(self.tcombobox,'Transformed',1)
        self.window.emit("destroy")
    def cancel(self,widget,data=None):
        self.image_list = []
        self.window.emit("destroy")
        
    def __init__(self,image_list,mode=None):
        '''Set up the widget.'''
        # store the image_list data
        self.full_image_list = image_list
        self.image_list = [None,None] # by default take the first two.
        self.mode = mode
        self.filename = None
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_event)
        self.window.connect("destroy",self.destroy)
        self.window.set_title('Panorama Image Selection')
        self.window.set_border_width(10)
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # formatting table
        table = gtk.Table(2,4,homogeneous=gtk.FALSE)
        table.set_row_spacings(10)
        table.set_col_spacings(10)
        # label the widget
        label = gtk.Label("Select the reference and transformed images.")
        label.set_alignment(0,0)
        table.attach(label,0,2,0,1,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        # Separator
        separator = gtk.HSeparator()
        table.attach(separator,0,2,1,2,yoptions=gtk.FILL,xoptions=gtk.FILL)
        separator.show()
        # Reference Image selector
        label = gtk.Label("Reference Image:")
        table.attach(label,0,1,2,3,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        self.rcombobox = gtk.combo_box_new_text()
        nimages = len(image_list)
        for index in range(nimages):
            self.rcombobox.append_text(str(image_list[index].ID)+'. '+image_list[index].name)
        self.rcombobox.append_text('Load from file')
        #self.rcombobox.connect("changed",self.reference_image_set)
        self.rcombobox.set_active(min(1,nimages))
        table.attach(self.rcombobox,1,2,2,3,yoptions=gtk.FILL,xoptions=gtk.FILL)
        self.rcombobox.show()
        # Transformed Image selector
        label = gtk.Label("Transformed Image:")
        table.attach(label,0,1,3,4,yoptions=gtk.FILL,xoptions=gtk.FILL)
        label.show()
        self.tcombobox = gtk.combo_box_new_text()
        nimages = len(image_list)
        for index in range(nimages):
             self.tcombobox.append_text(str(image_list[index].ID)+'. '+image_list[index].name)
        self.tcombobox.append_text('Load from file')
        #self.tcombobox.connect("changed",self.transformed_image_set)
        self.tcombobox.set_active(min((0,nimages)))
        table.attach(self.tcombobox,1,2,3,4,yoptions=gtk.FILL,xoptions=gtk.FILL)
        self.tcombobox.show()
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        table.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # accept button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button("Accept")
        button.connect("clicked", self.accept)
        #button.connect("clicked", lambda w: gtk.main_quit())
        #button.connect_object("clicked", gtk.Widget.destroy, self.window)
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        # cancel button
        button = gtk.Button("Cancel")
        button.connect("clicked", self.cancel)
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        button.show()
        hbox.show()
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
    def main(self):
        gtk.main()
        gtk.Widget.destroy(self.window)


class ControlPointEditorWidget:
    '''Widget to implement the control point editor.'''

    def update_control_point_table(self):
        '''Redraw the control point table.'''
        gtk.Widget.destroy(self.control_point_table)
        self.create_new_control_point_table()
        self.button_set_sensitivity() # grey out buttons?
        draw_control_points(self.stitch)
    
    def add_control_point(self,widget,data=None):
        '''Add a new control point to the updated_control_point list.'''
        
        self.add_button.set_sensitive(gtk.FALSE)  # greyed out
        self.edit_button.set_sensitive(gtk.FALSE)
        self.delete_button.set_sensitive(gtk.FALSE)
        self.save_button.set_sensitive(gtk.FALSE)
        self.restore_button.set_sensitive(gtk.FALSE)
        
        cp = get_new_control_point(self.stitch,True)
        
        self.add_button.set_sensitive(gtk.TRUE)  # not greyed out
        self.edit_button.set_sensitive(gtk.TRUE)
        self.delete_button.set_sensitive(gtk.TRUE)
        self.save_button.set_sensitive(gtk.TRUE)
        self.restore_button.set_sensitive(gtk.TRUE)
        
        if cp:
            self.stitch.add_control_point(cp)
            self.update_control_point_table()
            
    def edit_control_point(self,widget,data=None):
        '''Edit one control point from the control point list.'''
        old_control_point = self.stitch.control_points[self.selected_control_point_index]
        widget = EditSingleControlPointWidget(old_control_point,self.stitch.mode)
        widget.main()
        if widget.new_control_point:
            assert widget.new_control_point.__class__ is control_point, \
               'control_point parameter is not an instance of the control_point class.'
            self.stitch.replace_control_point(widget.new_control_point,
                                              self.selected_control_point_index)
            self.update_control_point_table()
            
    def delete_control_point(self,widget,data=None):
        '''Delete one control point from the control point list.'''
        if self.stitch.control_points:
            self.stitch.delete_control_point(self.selected_control_point_index)
            self.update_control_point_table()

    def move_control_point_up(self,widget,data=None):
        '''Move one control point up in the control point list.'''
        if self.stitch.control_points:
            index = self.selected_control_point_index
            self.stitch.move_control_point_up(index)
            gtk.Widget.destroy(self.control_point_table)
            self.create_new_control_point_table()
            self.button_set_sensitivity() # grey out buttons?
            if index > 0:
                self.radiolist[index-1].set_active(gtk.TRUE)
                self.control_point_radio_event(self.radiolist[index-1],index-1)
    
    
    def move_control_point_down(self,widget,data=None):
        '''Move one control point down in the control point list.'''
        if self.stitch.control_points:
            index = self.selected_control_point_index
            self.stitch.move_control_point_down(index)
            gtk.Widget.destroy(self.control_point_table)
            self.create_new_control_point_table()
            self.button_set_sensitivity() # grey out buttons?
            if index < self.stitch.npoints-1:
                self.radiolist[index+1].set_active(gtk.TRUE)
                self.control_point_radio_event(self.radiolist[index+1],index+1)
                
    def save_control_points(self,widget,data=None):
        '''Save the control points to a file.'''
        
        self.add_button.set_sensitive(gtk.FALSE)  # greyed out
        self.edit_button.set_sensitive(gtk.FALSE)  # greyed out
        self.delete_button.set_sensitive(gtk.FALSE)
        self.save_button.set_sensitive(gtk.FALSE)
        self.restore_button.set_sensitive(gtk.FALSE)
        
        widget = FileSelector("Select Save File",self.filename)
        widget.main()
        if widget.filename:
            self.filename = widget.filename
            if os.path.isfile(self.filename):
                qw = QueryWidget('File '+self.filename+' exists.  Overwrite?')
                qw.main()
                if not qw.answer: self.filename=''
            if self.filename:
                try:
                    fobj = file(self.filename,'wb')
                    pickle.dump(self.stitch.control_points,fobj,True)
                    fobj.close()
                except IOError:
                    error_message('Error: could not save to file '+
                                  self.filename+':\n'+
                                  str(sys.exc_value),self.mode)
        self.button_set_sensitivity()
                    
    def restore_control_points(self,widget,data=None):
        '''Restore a file of control points.'''
        
        self.add_button.set_sensitive(gtk.FALSE)  # greyed out
        self.edit_button.set_sensitive(gtk.FALSE)  # greyed out
        self.delete_button.set_sensitive(gtk.FALSE)
        self.save_button.set_sensitive(gtk.FALSE)
        self.restore_button.set_sensitive(gtk.FALSE)
        
        widget = FileSelector("Select Restore File",self.filename)
        widget.main()
        
        if widget.filename:
            self.filename = widget.filename
            if self.stitch.control_points:
                qw = QueryWidget('Overwrite the control point list?')
                qw.main()
                if not qw.answer: self.filename=''
            if self.filename:
                try:
                    fobj = file(self.filename,'rb')
                    control_points = pickle.load(fobj)
                    self.stitch.set_control_points(control_points)
                    ##if __debug__: print 'Number of imported control points: ',self.stitch.npoints
                    fobj.close()
                except IOError:
                    error_message('Error: could not restore from file '+
                                  self.filename+':\n'+
                                  str(sys.exc_value),self.mode)
                else:
                    self.update_control_point_table()
        self.button_set_sensitivity()

    def button_set_sensitivity(self):
        '''Grey out edit,delete,save, etc. buttons as needed.'''
        self.restore_button.set_sensitive(gtk.TRUE)  # not greyed out
        self.add_button.set_sensitive(gtk.TRUE)  # not greyed out
        if not self.stitch.control_points:
            self.edit_button.set_sensitive(gtk.FALSE)  # greyed out
            self.delete_button.set_sensitive(gtk.FALSE)
            self.save_button.set_sensitive(gtk.FALSE)
            self.up_button.set_sensitive(gtk.FALSE)   # greyed out
            self.down_button.set_sensitive(gtk.FALSE)
        else:
            self.edit_button.set_sensitive(gtk.TRUE)  # not greyed out
            self.delete_button.set_sensitive(gtk.TRUE)
            self.save_button.set_sensitive(gtk.TRUE)
            if self.stitch.npoints <= 1:
                self.up_button.set_sensitive(gtk.FALSE)   # greyed out
                self.down_button.set_sensitive(gtk.FALSE)
            else:
                self.up_button.set_sensitive(gtk.TRUE)   # not greyed out
                self.down_button.set_sensitive(gtk.TRUE)
                if self.selected_control_point_index == 0:
                    self.up_button.set_sensitive(gtk.FALSE)
                if self.selected_control_point_index == self.stitch.npoints-1:
                    self.down_button.set_sensitive(gtk.FALSE)
            for i in range(len(self.cblist)):
                if self.ncbselected >= 15:
                    if self.cblist[i].get_active():
                        self.cblist[i].set_sensitive(gtk.TRUE)
                    else:
                        self.cblist[i].set_sensitive(gtk.FALSE)
                else:
                    self.cblist[i].set_sensitive(gtk.TRUE)
            
    def control_point_radio_event(self,widget,index=None):
        '''A radio button was toggled, keep track of the index.'''
        if widget.get_active():
            ##if __debug__: print 'radio index is set to '+str(index)
            self.selected_control_point_index = index  # keep track of selected index
            self.button_set_sensitivity()

    def color_balance_check_event(self,widget,index=None):
        '''A radio button was toggled, keep track of the index.'''
        ##if __debug__: print 'cb index is set to '+str(index)
        if widget.get_active():
            self.stitch.control_points[index].colorbalance=True
            self.ncbselected += 1
        else:
            self.stitch.control_points[index].colorbalance=False
            self.ncbselected -= 1
        self.button_set_sensitivity()
        ##if __debug__: print 'ncbselected = ',self.ncbselected

    def control_point_table_fill(self):
        ''' Fill the control point table with radio buttons.'''
        if self.stitch.control_points:
            label0 = gtk.Label(' ')
            label1 = gtk.Label('Reference ')
            label2 = gtk.Label('Transform ')
            label3 = gtk.Label(' Corr ')
            label4 = gtk.Label(' Error ')
            labelc = gtk.Label('Color')
            self.control_point_table.attach(label0,0,1,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label1,1,2,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label2,2,3,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label3,3,4,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label4,4,5,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(labelc,5,6,0,1,
                                            yoptions=gtk.FILL,xoptions=gtk.FILL)
            label0.show() ; labelc.show(); label1.show() ; label2.show()
            label3.show() ; label4.show()
        row = 1
        radio = None
        cb = None
        self.ncbselected = 0
        self.selected_control_point_index = 0
        self.radiolist = []
        self.cblist = []
        for i in range(self.stitch.npoints):
            cp = self.stitch.control_points[i]
##             c = self.stitch.color(cp,50.0)  # get the colors around this control point
##             ccorr = (c[0][0]*c[1][0]+c[0][1]*c[1][1]+c[0][2]*c[1][2])/ \
##                     (math.sqrt(c[0][0]*c[0][0]+c[0][1]*c[0][1]+c[0][2]*c[0][2]) * \
##                      math.sqrt(c[1][0]*c[1][0]+c[1][1]*c[1][1]+c[1][2]*c[1][2]))
##             cdiff = abs(c[0][0]-c[1][0]) + abs(c[0][1]-c[1][1]) + abs(c[0][2]-c[1][2])
##             if __debug__: print 'color,ccorr: ',c,ccorr,cdiff
##             #clabel = '%5.2f' % ccorr
##             clabel = '%5.0f' % cdiff
            rnx = self.stitch.rimage.width   # the dimensions of the images
            rny = self.stitch.rimage.height
            tnx = self.stitch.timage.width
            tny = self.stitch.timage.height
            close_to_edge=False
            r = self.stitch.colorradius
            if cp.x1()<r or cp.y1()<r or cp.x2()<r or cp.y2()<r or \
               cp.x1()>rnx-r-1. or cp.y1()>rny-r-1. or cp.x2()>tnx-r-1. or cp.y2()>tny-r-1.:
                close_to_edge=True
            clabel = ''
            if close_to_edge: clabel='<edge>'
            radio = gtk.RadioButton(group=radio,label='')
            cb = gtk.CheckButton(clabel)
            self.radiolist.append(radio)
            self.cblist.append(cb)
            self.control_point_table.attach(radio,0,1,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(cb,5,6,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            label1 = gtk.Label('%7.2f %7.2f ' % (cp.x1(),cp.y1()))
            label2 = gtk.Label('%7.2f %7.2f ' % (cp.x2(),cp.y2()))
            if cp.correlation:
                label3 = gtk.Label('%7.2f ' % cp.correlation)
            else:
                label3 = gtk.Label(' ')
            label4 = gtk.Label('%7.2f ' % self.stitch.errors[i])
            self.control_point_table.attach(label1,1,2,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label2,2,3,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label3,3,4,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            self.control_point_table.attach(label4,4,5,row,row+1,yoptions=gtk.FILL,xoptions=gtk.FILL)
            label1.show() ; label2.show() ; label3.show() ; label4.show()
            radio.connect("toggled",self.control_point_radio_event,row-1)
            cb.connect("toggled",self.color_balance_check_event,row-1)
            radio.show()
            cb.show()
            if cp.cb():
                if self.ncbselected >= 15:
                    cp.colorbalance = False
                    cb.set_active(gtk.FALSE)
                else:
                    cb.set_active(gtk.TRUE)
            else:
                cb.set_active(gtk.FALSE)
            if row == self.stitch.npoints:  # initialization on the initially selected button
                radio.set_active(gtk.TRUE)
                self.control_point_radio_event(radio,row-1)
            row += 1
            
    def create_new_control_point_table(self):
        '''Create and fill the table of control points in the widget.'''
        if self.stitch.control_points:
            npoints = len(self.stitch.control_points)
            ##if __debug__: print 'create_new_control_point_table: ',npoints,' control points.'
            self.control_point_table = gtk.Table(npoints+1,6,homogeneous=gtk.FALSE)
            self.control_point_table.set_row_spacings(2)
            self.control_point_table.set_col_spacings(5)
        else: # make an empty table since there are no control points
            self.control_point_table = gtk.Table(1,6,homogeneous=gtk.FALSE)
        self.scrolled_window.add_with_viewport(self.control_point_table)
        self.control_point_table.show()
        self.control_point_table_fill()

    def cancel(self,widget,data=None):
        '''Deal with a press of the cancel button.'''
        self.stitch.set_control_points(self.original_control_points) # revert to original
        gtk.Widget.destroy(self.window)
        gtk.main_quit()
        
    def __init__(self,stitch):
        '''Set up the control point editor widget.'''
        # Save control_point data
        self.original_control_points = copy.copy(stitch.control_points) # save a copy
        self.stitch = stitch
        self.filename = None
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", lambda a1, a2: gtk.main_quit())
        self.window.connect("destroy",lambda wid: gtk.main_quit())
        self.window.set_title('Define control points')
        self.window.set_border_width(10)
        self.tooltips = gtk.Tooltips()
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # label the widget
        label = gtk.Label("Set the control points for the image transformation.")
        label.set_alignment(0,0)
        vbox.pack_start(label,gtk.FALSE,gtk.FALSE,0)
        label.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # The control point display area
        self.scrolled_window = gtk.ScrolledWindow()
        self.scrolled_window.set_border_width(10)
        self.scrolled_window.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
        vbox.pack_start(self.scrolled_window,gtk.TRUE,gtk.TRUE,0)
        self.scrolled_window.show()
        # editing buttons, add, edit, delete
        # add button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        self.add_button = gtk.Button("Add")
        self.add_button.connect("clicked", self.add_control_point)
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.add_button,expand,fill,padding)
        self.tooltips.set_tip(self.add_button,"To add a control point, select small, " + \
                                              "corresponding regions in each image and press Add")
        self.add_button.show()
        # edit button
        self.edit_button = gtk.Button("Edit")
        self.edit_button.connect("clicked", self.edit_control_point)
        if not self.stitch.control_points:
            self.edit_button.set_sensitive(gtk.FALSE)  # greyed out
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.edit_button,expand,fill,padding)
        self.edit_button.show()
        # delete button
        self.delete_button = gtk.Button("Delete")
        self.delete_button.connect("clicked", self.delete_control_point)
        if not self.stitch.control_points:
            self.delete_button.set_sensitive(gtk.FALSE)  # greyed out
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.delete_button,expand,fill,padding)
        self.delete_button.show()
        # up button
        self.up_button = gtk.Button("Up")
        self.up_button.connect("clicked",self.move_control_point_up)
        if self.stitch.npoints <= 15:
            self.up_button.set_sensitive(gtk.FALSE) # greyed out
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.up_button,expand,fill,padding)
        self.up_button.show()
        # down button
        self.down_button = gtk.Button("Down")
        self.down_button.connect("clicked",self.move_control_point_down)
        if self.stitch.npoints <= 15:
            self.down_button.set_sensitive(gtk.FALSE) # greyed out
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.down_button,expand,fill,padding)
        self.down_button.show()
        # save button
        self.save_button = gtk.Button("Save")
        self.save_button.connect("clicked", self.save_control_points)
        if not self.stitch.control_points:
            self.save_button.set_sensitive(gtk.FALSE)  # greyed out
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.save_button,expand,fill,padding)
        self.save_button.show()
        # restore button
        self.restore_button = gtk.Button("Restore")
        self.restore_button.connect("clicked", self.restore_control_points)
        expand = gtk.FALSE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(self.restore_button,expand,fill,padding)
        self.restore_button.show()
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        hbox.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # accept button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button("Accept")
        button.connect("clicked", lambda w: gtk.main_quit())
        button.connect_object("clicked", gtk.Widget.destroy, self.window)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        # cancel button
        button = gtk.Button("Cancel")
        button.connect("clicked", self.cancel)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        button.show()
        hbox.show()
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
        # create a table of the control point data
        self.create_new_control_point_table()
    def main(self):
        gtk.main()

class EditSingleControlPointWidget:
    '''Widget to edit a control point.'''
    def accept(self,widget,data=None):
        '''Call back for accept button.'''
        try:
            x1 = float(self.rxentry.get_text())
            y1 = float(self.ryentry.get_text())
            x2 = float(self.txentry.get_text())
            y2 = float(self.tyentry.get_text())
        except ValueError:
            error_message('Error: please enter only numbers.',self.mode)
        else:
            self.new_control_point = control_point(x1,y1,x2,y2)
            gtk.Widget.destroy(self.window)
    def __init__(self,control_point=None,mode=None):
        '''Set up the widget.'''
        # Save control_point data
        self.old_control_point = control_point
        self.new_control_point = None
        self.mode = mode
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", lambda a1, a2: gtk.main_quit())
        self.window.connect("destroy",lambda wid: gtk.main_quit())
        self.window.set_title('Edit Control Point')
        self.window.set_border_width(10)
        self.tooltips = gtk.Tooltips()
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # label the widget
        label = gtk.Label("Edit Control Point.")
        label.set_alignment(0,0)
        vbox.pack_start(label,gtk.FALSE,gtk.FALSE,0)
        label.show()
        # Separator
        separator = gtk.HSeparator()
        vbox.pack_start(separator,gtk.FALSE,gtk.TRUE,5)
        separator.show()
        # table
        table = gtk.Table(1,1,gtk.FALSE)
        table.set_row_spacings(0)
        table.set_col_spacings(0)
        table.show()
        # Reference Text entries
        label = gtk.Label("Reference Image:")
        label.set_alignment(0,0)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        table.attach(label,0,1,0,1)
        label.show()
        self.rxentry = gtk.Entry(max=0)
        self.rxentry.set_text(str(control_point.x1()))
        self.rxentry.set_editable(gtk.TRUE)
        self.ryentry = gtk.Entry(max=0)
        self.ryentry.set_text(str(control_point.y1()))
        self.ryentry.set_editable(gtk.TRUE)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        table.attach(self.rxentry,1,2,0,1)
        table.attach(self.ryentry,2,3,0,1)
        self.rxentry.show()
        self.ryentry.show()
        # Transformed text entries
        label = gtk.Label("Transformed Image:")
        label.set_alignment(0,0)
        table.attach(label,0,1,1,2)
        label.show()
        self.txentry = gtk.Entry(max=0)
        self.txentry.set_text(str(control_point.x2()))
        self.txentry.set_editable(gtk.TRUE)
        self.tyentry = gtk.Entry(max=0)
        self.tyentry.set_text(str(control_point.y2()))
        self.tyentry.set_editable(gtk.TRUE)
        table.attach(self.txentry,1,2,1,2)
        table.attach(self.tyentry,2,3,1,2)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        vbox.pack_start(table,gtk.FALSE,gtk.FALSE,0)
        self.txentry.show()
        self.tyentry.show()
        table.show()
        # accept button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button("Accept")
        button.connect("clicked", self.accept)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        # cancel button
        button = gtk.Button("Cancel")
        button.connect("clicked", lambda w: gtk.main_quit())
        button.connect_object("clicked", gtk.Widget.destroy, self.window)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        button.show()
        hbox.show()
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
    def main(self):
        gtk.main()

class FileSelector:
    def destroy(self,widget,data=None):
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        return gtk.FALSE
    def cancel(self,widget,data=None):
        self.filename = None
        self.filew.emit("destroy")
    def file_ok_sel(self,widget,data=None):
        self.filename = self.filew.get_filename()
        self.filew.emit("destroy")
    def __init__(self,title=None,file=None):
        '''Set up the widget.'''
        self.filename = file
        # file widget
        self.filew = gtk.FileSelection(title)
        self.filew.connect("delete_event", self.delete_event)
        self.filew.connect("destroy", self.destroy)
        self.filew.ok_button.connect("clicked",self.file_ok_sel)
        self.filew.cancel_button.connect("clicked",self.cancel)
        self.filew.hide_fileop_buttons()
        if file: self.filew.set_filename(file)
        self.filew.show()
    def main(self):
        gtk.main()
        gtk.Widget.destroy(self.filew)


class QueryWidget:
    '''Widget to ask a binary question.
    QueryWidget(question,yeslabel,nolabel)'''
    def destroy(self,widget,data=None):
        '''got a destroy signal.'''
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        '''got a delete_event signal.'''
        return gtk.FALSE
    def clicked_yes(self,widget,data=None):
        '''The user clicked on the yes button.'''
        self.answer = True
        self.window.emit("destroy")
    def clicked_no(self,widget,data=None):
        '''The user clicked on the no button.'''
        self.answer = False
        self.window.emit("destroy")
    def __init__(self,question,yes='Yes',no='No'):
        self.answer = False
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_event)
        self.window.connect("destroy",self.destroy)
        self.window.set_title('Query')
        self.window.set_border_width(10)
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # label the widget
        label = gtk.Label(question)
        label.set_alignment(0,0)
        vbox.pack_start(label,gtk.FALSE,gtk.FALSE,0)
        label.show()
        # yes button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button(yes)
        button.connect("clicked",self.clicked_yes)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        # no button
        button = gtk.Button(no)
        button.connect("clicked",self.clicked_no)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        button.show()
        hbox.show()
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
    def main(self):
        gtk.main()
        gtk.Widget.destroy(self.window)

class MessageWidget:
    '''Widget to state a message.
    MessageWidget(message)'''
    def destroy(self,widget,data=None):
        '''got a destroy signal.'''
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        '''got a delete_event signal.'''
        return gtk.FALSE
    def clicked_ok(self,widget,data=None):
        '''The user clicked on the ok button.'''
        self.answer = True
        self.window.emit("destroy")
    def __init__(self,message):
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_event)
        self.window.connect("destroy",self.destroy)
        self.window.set_title('Message')
        self.window.set_border_width(10)
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # label the widget
        label = gtk.Label(message)
        label.set_alignment(0,0)
        vbox.pack_start(label,gtk.FALSE,gtk.FALSE,0)
        label.show()
        # ok button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button('OK')
        button.connect("clicked",self.clicked_ok)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        hbox.show()
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
    def main(self):
        gtk.main()
        gtk.Widget.destroy(self.window)
class ProgressWidget:
    '''Widget to display progress.
    MessageWidget(message)'''
    def destroy(self,widget,data=None):
        '''got a destroy signal.'''
        gtk.main_quit()
    def delete_event(self,widget,event,data=None):
        '''got a delete_event signal.'''
        return gtk.FALSE
    def clicked_ok(self,widget,data=None):
        '''The user clicked on the ok button.'''
        self.answer = True
        self.window.emit("destroy")
    def __init__(self):
        # basic setup, similar for all windows
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", self.delete_event)
        self.window.connect("destroy",self.destroy)
        self.window.set_title('Progress')
        self.window.set_border_width(10)
        # This is the main vertical box
        vbox = gtk.VBox(gtk.FALSE,0)
        # label the widget
        self.progress = gtk.ProgressBar()
        vbox.pack_start(self.progress,gtk.FALSE,gtk.FALSE,0)
        self.progress.show()
        # ok button
        homogeneous = gtk.FALSE ; spacing = 0
        hbox = gtk.HBox(homogeneous,spacing)
        button = gtk.Button('OK')
        button.connect("clicked",self.clicked_ok)
        expand = gtk.TRUE ; fill = gtk.FALSE; padding = 0
        hbox.pack_start(button,expand,fill,padding)
        button.show()
        hbox.show()
        vbox.pack_start(hbox,gtk.FALSE,gtk.FALSE,0)
        # Display everything
        self.window.add(vbox)
        vbox.show()
        self.window.show()
    def main(self):
        gtk.main()
        gtk.Widget.destroy(self.window)

#---------------------- Numerical Functions



# Almost exact translation of the ALGOL SVD algorithm published in
# Numer. Math. 14, 403-420 (1970) by G. H. Golub and C. Reinsch
#
# Copyright (c) 2005 by Thomas R. Metcalf, helicity314-stitch@yahoo.com
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Pure Python SVD algorithm.
# Input: 2-D list (m by n) with m >= n
# Output: U,W V so that A = U*W*VT
#    Note this program returns V not VT (=transpose(V))
#    On error, a ValueError is raised.
#
# Here is the test case (first example) from Golub and Reinsch
#
# a = [[22.,10., 2.,  3., 7.],
#      [14., 7.,10.,  0., 8.],
#      [-1.,13.,-1.,-11., 3.],
#      [-3.,-2.,13., -2., 4.],
#      [ 9., 8., 1., -2., 4.],
#      [ 9., 1.,-7.,  5.,-1.],
#      [ 2.,-6., 6.,  5., 1.],
#      [ 4., 5., 0., -2., 2.]]
#
# import svd
# import math
# u,w,vt = svd.svd(a)
# print w
#
# [35.327043465311384, 1.2982256062667619e-15,
#  19.999999999999996, 19.595917942265423, 0.0]
#
# the correct answer is (the order may vary)
#
# print (math.sqrt(1248.),20.,math.sqrt(384.),0.,0.)
#
# (35.327043465311391, 20.0, 19.595917942265423, 0.0, 0.0)
#
# transpose and matrix multiplication functions are also included
# to facilitate the solution of linear systems.
#
# Version 1.0 2005 May 01


def svd(a):
    '''Compute the singular value decomposition of a.'''

    # Golub and Reinsch state that eps should not be smaller than the
    # machine precision, ie the smallest number
    # for which 1+e>1.  tol should be beta/e where beta is the smallest
    # positive number representable in the computer.
    eps = 1.e-15  # assumes double precision
    tol = 1.e-64/eps
    assert 1.0+eps > 1.0 # if this fails, make eps bigger
    assert tol > 0.0     # if this fails, make tol bigger
    itmax = 50
    u = copy.deepcopy(a)
    m = len(a)
    n = len(a[0])
    #if __debug__: print 'a is ',m,' by ',n

    if m < n:
        if __debug__: print 'Error: m is less than n'
        raise ValueError,'SVD Error: m is less than n.'

    e = [0.0]*n  # allocate arrays
    q = [0.0]*n
    v = []
    for k in range(n): v.append([0.0]*n)
 
    # Householder's reduction to bidiagonal form

    g = 0.0
    x = 0.0

    for i in range(n):
        e[i] = g
        s = 0.0
        l = i+1
        for j in range(i,m): s += (u[j][i]*u[j][i])
        if s <= tol:
            g = 0.0
        else:
            f = u[i][i]
            if f < 0.0:
                g = math.sqrt(s)
            else:
                g = -math.sqrt(s)
            h = f*g-s
            u[i][i] = f-g
            for j in range(l,n):
                s = 0.0
                for k in range(i,m): s += u[k][i]*u[k][j]
                f = s/h
                for k in range(i,m): u[k][j] = u[k][j] + f*u[k][i]
        q[i] = g
        s = 0.0
        for j in range(l,n): s = s + u[i][j]*u[i][j]
        if s <= tol:
            g = 0.0
        else:
            f = u[i][i+1]
            if f < 0.0:
                g = math.sqrt(s)
            else:
                g = -math.sqrt(s)
            h = f*g - s
            u[i][i+1] = f-g
            for j in range(l,n): e[j] = u[i][j]/h
            for j in range(l,m):
                s=0.0
                for k in range(l,n): s = s+(u[j][k]*u[i][k])
                for k in range(l,n): u[j][k] = u[j][k]+(s*e[k])
        y = abs(q[i])+abs(e[i])
        if y>x: x=y
    # accumulation of right hand gtransformations
    for i in range(n-1,-1,-1):
        if g != 0.0:
            h = g*u[i][i+1]
            for j in range(l,n): v[j][i] = u[i][j]/h
            for j in range(l,n):
                s=0.0
                for k in range(l,n): s += (u[i][k]*v[k][j])
                for k in range(l,n): v[k][j] += (s*v[k][i])
        for j in range(l,n):
            v[i][j] = 0.0
            v[j][i] = 0.0
        v[i][i] = 1.0
        g = e[i]
        l = i
    #accumulation of left hand transformations
    for i in range(n-1,-1,-1):
        l = i+1
        g = q[i]
        for j in range(l,n): u[i][j] = 0.0
        if g != 0.0:
            h = u[i][i]*g
            for j in range(l,n):
                s=0.0
                for k in range(l,m): s += (u[k][i]*u[k][j])
                f = s/h
                for k in range(i,m): u[k][j] += (f*u[k][i])
            for j in range(i,m): u[j][i] = u[j][i]/g
        else:
            for j in range(i,m): u[j][i] = 0.0
        u[i][i] += 1.0
    #diagonalization of the bidiagonal form
    eps = eps*x
    for k in range(n-1,-1,-1):
        for iteration in range(itmax):
            # test f splitting
            for l in range(k,-1,-1):
                goto_test_f_convergence = False
                if abs(e[l]) <= eps:
                    # goto test f convergence
                    goto_test_f_convergence = True
                    break  # break out of l loop
                if abs(q[l-1]) <= eps:
                    # goto cancellation
                    break  # break out of l loop
            if not goto_test_f_convergence:
                #cancellation of e[l] if l>0
                c = 0.0
                s = 1.0
                l1 = l-1
                for i in range(l,k+1):
                    f = s*e[i]
                    e[i] = c*e[i]
                    if abs(f) <= eps:
                        #goto test f convergence
                        break
                    g = q[i]
                    h = pythag(f,g)
                    q[i] = h
                    c = g/h
                    s = -f/h
                    for j in range(m):
                        y = u[j][l1]
                        z = u[j][i]
                        u[j][l1] = y*c+z*s
                        u[j][i] = -y*s+z*c
            # test f convergence
            z = q[k]
            if l == k:
                # convergence
                if z<0.0:
                    #q[k] is made non-negative
                    q[k] = -z
                    for j in range(n):
                        v[j][k] = -v[j][k]
                break  # break out of iteration loop and move on to next k value
            if iteration >= itmax-1:
                if __debug__: print 'Error: no convergence.'
                # should this move on the the next k or exit with error??
                #raise ValueError,'SVD Error: No convergence.'  # exit the program with error
                break  # break out of iteration loop and move on to next k
            # shift from bottom 2x2 minor
            x = q[l]
            y = q[k-1]
            g = e[k-1]
            h = e[k]
            f = ((y-z)*(y+z)+(g-h)*(g+h))/(2.0*h*y)
            g = pythag(f,1.0)
            if f < 0:
                f = ((x-z)*(x+z)+h*(y/(f-g)-h))/x
            else:
                f = ((x-z)*(x+z)+h*(y/(f+g)-h))/x
            # next QR transformation
            c = 1.0
            s = 1.0
            for i in range(l+1,k+1):
                g = e[i]
                y = q[i]
                h = s*g
                g = c*g
                z = pythag(f,h)
                e[i-1] = z
                c = f/z
                s = h/z
                f = x*c+g*s
                g = -x*s+g*c
                h = y*s
                y = y*c
                for j in range(n):
                    x = v[j][i-1]
                    z = v[j][i]
                    v[j][i-1] = x*c+z*s
                    v[j][i] = -x*s+z*c
                z = pythag(f,h)
                q[i-1] = z
                c = f/z
                s = h/z
                f = c*g+s*y
                x = -s*g+c*y
                for j in range(m):
                    y = u[j][i-1]
                    z = u[j][i]
                    u[j][i-1] = y*c+z*s
                    u[j][i] = -y*s+z*c
            e[l] = 0.0
            e[k] = f
            q[k] = x
            # goto test f splitting
        
            
    #vt = transpose(v)
    #return (u,q,vt)
    return (u,q,v)

def pythag(a,b):
    absa = abs(a)
    absb = abs(b)
    if absa > absb: return absa*math.sqrt(1.0+(absb/absa)**2)
    else:
        if absb == 0.0: return 0.0
        else: return absb*math.sqrt(1.0+(absa/absb)**2)

def transpose(a):
    '''Compute the transpose of a matrix.'''
    m = len(a)
    n = len(a[0])
    at = []
    for i in range(n): at.append([0.0]*m)
    for i in range(m):
        for j in range(n):
            at[j][i]=a[i][j]
    return at

def matrixmultiply(a,b):
    '''Multiply two matrices.
    a must be two dimensional
    b can be one or two dimensional.'''
    
    am = len(a)
    bm = len(b)
    an = len(a[0])
    try:
        bn = len(b[0])
    except TypeError:
        bn = 1
    if an != bm:
        raise ValueError, 'matrixmultiply error: array sizes do not match.'
    cm = am
    cn = bn
    if bn == 1:
        c = [0.0]*cm
    else:
        c = []
        for k in range(cm): c.append([0.0]*cn)
    for i in range(cm):
        for j in range(cn):
            for k in range(an):
                if bn == 1:
                    c[i] += a[i][k]*b[k]
                else:
                    c[i][j] += a[i][k]*b[k][j]
    
    return c
 
 

# -------------------------------------------

def amoeba(var,scale,func,ftolerance=1.e-4,xtolerance=1.e-4,itmax=500,data=None):
    '''Use the simplex method to maximize a function of 1 or more variables.
    
       Input:
              var = the initial guess, a list with one element for each variable
              scale = the search scale for each variable, a list with one
                      element for each variable.
              func = the function to maximize.
              
       Optional Input:
              ftolerance = convergence criterion on the function values (default = 1.e-4)
              xtolerance = convergence criterion on the variable values (default = 1.e-4)
              itmax = maximum number of iterations allowed (default = 500).
              data = data to be passed to func (default = None).
              
       Output:
              (varbest,funcvalue,iterations)
              varbest = a list of the variables at the maximum.
              funcvalue = the function value at the maximum.
              iterations = the number of iterations used.

       - Setting itmax to zero disables the itmax check and the routine will run
         until convergence, even if it takes forever.
       - Setting ftolerance or xtolerance to 0.0 turns that convergence criterion
         off.  But do not set both ftolerance and xtolerance to zero or the routine
         will exit immediately without finding the maximum.
       - To check for convergence, check if (iterations < itmax).
              
       The function should be defined like func(var,data) where
       data is optional data to pass to the function.

       Example:
       
           import amoeba
           def afunc(var,data=None): return 1.0-var[0]*var[0]-var[1]*var[1]
           print amoeba.amoeba([0.25,0.25],[0.5,0.5],afunc)

       Version 1.0 2005-March-28 T. Metcalf
               1.1 2005-March-29 T. Metcalf - Use scale in simsize calculation.
                                            - Use func convergence *and* x convergence
                                              rather than func convergence *or* x
                                              convergence.
       '''

    nvar = len(var)       # number of variables in the minimization
    nsimplex = nvar + 1   # number of vertices in the simplex
    
    # first set up the simplex

    simplex = [0]*(nvar+1)  # set the initial simplex
    simplex[0] = var[:]
    for i in range(nvar):
        simplex[i+1] = var[:]
        simplex[i+1][i] += scale[i]

    fvalue = []
    for i in range(nsimplex):  # set the function values for the simplex
        fvalue.append(func(simplex[i],data=data))

    # Ooze the simplex to the maximum

    iteration = 0
    
    while 1:
        # find the index of the best and worst vertices in the simplex
        ssworst = 0
        ssbest  = 0
        for i in range(nsimplex):
            if fvalue[i] > fvalue[ssbest]:
                ssbest = i
            if fvalue[i] < fvalue[ssworst]:
                ssworst = i
        
        # get the average of the nsimplex-1 best vertices in the simplex
        pavg = [0.0]*nvar
        for i in range(nsimplex):
            if i != ssworst:
                for j in range(nvar): pavg[j] += simplex[i][j]
        for j in range(nvar): pavg[j] = pavg[j]/nvar  # nvar is nsimplex-1
        simscale = 0.0
        for i in range(nvar):
            simscale += abs(pavg[i]-simplex[ssworst][i])/scale[i]
        simscale = simscale/nvar

        # find the range of the function values
        fscale = (abs(fvalue[ssbest])+abs(fvalue[ssworst]))/2.0
        if fscale != 0.0:
            frange = abs(fvalue[ssbest]-fvalue[ssworst])/fscale
        else:
            frange = 0.0  # all the fvalues are zero in this case

        # have we converged?
        if (((ftolerance <= 0.0 or frange < ftolerance) and    # converged to maximum
             (xtolerance <= 0.0 or simscale < xtolerance)) or  # simplex contracted enough
            (itmax and iteration >= itmax)):                   # ran out of iterations
            return simplex[ssbest],fvalue[ssbest],iteration

        # reflect the worst vertex
        pnew = [0.0]*nvar
        for i in range(nvar):
            pnew[i] = 2.0*pavg[i] - simplex[ssworst][i]
        fnew = func(pnew,data=data)
        if fnew <= fvalue[ssworst]:
            # the new vertex is worse than the worst so shrink
            # the simplex.
            for i in range(nsimplex):
                if i != ssbest and i != ssworst:
                    for j in range(nvar):
                        simplex[i][j] = 0.5*simplex[ssbest][j] + 0.5*simplex[i][j]
                    fvalue[i] = func(simplex[i],data=data)
            for j in range(nvar):
                pnew[j] = 0.5*simplex[ssbest][j] + 0.5*simplex[ssworst][j]
            fnew = func(pnew,data=data)
        elif fnew >= fvalue[ssbest]:
            # the new vertex is better than the best so expand
            # the simplex.
            pnew2 = [0.0]*nvar
            for i in range(nvar):
                pnew2[i] = 3.0*pavg[i] - 2.0*simplex[ssworst][i]
            fnew2 = func(pnew2,data=data)
            if fnew2 > fnew:
                # accept the new vertex in the simplex
                pnew = pnew2
                fnew = fnew2
        # replace the worst vertex with the new vertex
        for i in range(nvar):
            simplex[ssworst][i] = pnew[i]
        fvalue[ssworst] = fnew
        iteration += 1
        #if __debug__: print ssbest,fvalue[ssbest]



#----------------- Go!

# Last, but not least, run the plugin!

if __name__ == '__main__': stitch_plugin().start()

#----------------- GNU Public License


## 		    GNU GENERAL PUBLIC LICENSE
## 		       Version 2, June 1991

##  Copyright (C) 1989, 1991 Free Software Foundation, Inc.
##                        59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
##  Everyone is permitted to copy and distribute verbatim copies
##  of this license document, but changing it is not allowed.

## 			    Preamble

##   The licenses for most software are designed to take away your
## freedom to share and change it.  By contrast, the GNU General Public
## License is intended to guarantee your freedom to share and change free
## software--to make sure the software is free for all its users.  This
## General Public License applies to most of the Free Software
## Foundation's software and to any other program whose authors commit to
## using it.  (Some other Free Software Foundation software is covered by
## the GNU Library General Public License instead.)  You can apply it to
## your programs, too.

##   When we speak of free software, we are referring to freedom, not
## price.  Our General Public Licenses are designed to make sure that you
## have the freedom to distribute copies of free software (and charge for
## this service if you wish), that you receive source code or can get it
## if you want it, that you can change the software or use pieces of it
## in new free programs; and that you know you can do these things.

##   To protect your rights, we need to make restrictions that forbid
## anyone to deny you these rights or to ask you to surrender the rights.
## These restrictions translate to certain responsibilities for you if you
## distribute copies of the software, or if you modify it.

##   For example, if you distribute copies of such a program, whether
## gratis or for a fee, you must give the recipients all the rights that
## you have.  You must make sure that they, too, receive or can get the
## source code.  And you must show them these terms so they know their
## rights.

##   We protect your rights with two steps: (1) copyright the software, and
## (2) offer you this license which gives you legal permission to copy,
## distribute and/or modify the software.

##   Also, for each author's protection and ours, we want to make certain
## that everyone understands that there is no warranty for this free
## software.  If the software is modified by someone else and passed on, we
## want its recipients to know that what they have is not the original, so
## that any problems introduced by others will not reflect on the original
## authors' reputations.

##   Finally, any free program is threatened constantly by software
## patents.  We wish to avoid the danger that redistributors of a free
## program will individually obtain patent licenses, in effect making the
## program proprietary.  To prevent this, we have made it clear that any
## patent must be licensed for everyone's free use or not licensed at all.

##   The precise terms and conditions for copying, distribution and
## modification follow.
## 
## 		    GNU GENERAL PUBLIC LICENSE
##    TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION

##   0. This License applies to any program or other work which contains
## a notice placed by the copyright holder saying it may be distributed
## under the terms of this General Public License.  The "Program", below,
## refers to any such program or work, and a "work based on the Program"
## means either the Program or any derivative work under copyright law:
## that is to say, a work containing the Program or a portion of it,
## either verbatim or with modifications and/or translated into another
## language.  (Hereinafter, translation is included without limitation in
## the term "modification".)  Each licensee is addressed as "you".

## Activities other than copying, distribution and modification are not
## covered by this License; they are outside its scope.  The act of
## running the Program is not restricted, and the output from the Program
## is covered only if its contents constitute a work based on the
## Program (independent of having been made by running the Program).
## Whether that is true depends on what the Program does.

##   1. You may copy and distribute verbatim copies of the Program's
## source code as you receive it, in any medium, provided that you
## conspicuously and appropriately publish on each copy an appropriate
## copyright notice and disclaimer of warranty; keep intact all the
## notices that refer to this License and to the absence of any warranty;
## and give any other recipients of the Program a copy of this License
## along with the Program.

## You may charge a fee for the physical act of transferring a copy, and
## you may at your option offer warranty protection in exchange for a fee.

##   2. You may modify your copy or copies of the Program or any portion
## of it, thus forming a work based on the Program, and copy and
## distribute such modifications or work under the terms of Section 1
## above, provided that you also meet all of these conditions:

##     a) You must cause the modified files to carry prominent notices
##     stating that you changed the files and the date of any change.

##     b) You must cause any work that you distribute or publish, that in
##     whole or in part contains or is derived from the Program or any
##     part thereof, to be licensed as a whole at no charge to all third
##     parties under the terms of this License.

##     c) If the modified program normally reads commands interactively
##     when run, you must cause it, when started running for such
##     interactive use in the most ordinary way, to print or display an
##     announcement including an appropriate copyright notice and a
##     notice that there is no warranty (or else, saying that you provide
##     a warranty) and that users may redistribute the program under
##     these conditions, and telling the user how to view a copy of this
##     License.  (Exception: if the Program itself is interactive but
##     does not normally print such an announcement, your work based on
##     the Program is not required to print an announcement.)
## 
## These requirements apply to the modified work as a whole.  If
## identifiable sections of that work are not derived from the Program,
## and can be reasonably considered independent and separate works in
## themselves, then this License, and its terms, do not apply to those
## sections when you distribute them as separate works.  But when you
## distribute the same sections as part of a whole which is a work based
## on the Program, the distribution of the whole must be on the terms of
## this License, whose permissions for other licensees extend to the
## entire whole, and thus to each and every part regardless of who wrote it.

## Thus, it is not the intent of this section to claim rights or contest
## your rights to work written entirely by you; rather, the intent is to
## exercise the right to control the distribution of derivative or
## collective works based on the Program.

## In addition, mere aggregation of another work not based on the Program
## with the Program (or with a work based on the Program) on a volume of
## a storage or distribution medium does not bring the other work under
## the scope of this License.

##   3. You may copy and distribute the Program (or a work based on it,
## under Section 2) in object code or executable form under the terms of
## Sections 1 and 2 above provided that you also do one of the following:

##     a) Accompany it with the complete corresponding machine-readable
##     source code, which must be distributed under the terms of Sections
##     1 and 2 above on a medium customarily used for software interchange; or,

##     b) Accompany it with a written offer, valid for at least three
##     years, to give any third party, for a charge no more than your
##     cost of physically performing source distribution, a complete
##     machine-readable copy of the corresponding source code, to be
##     distributed under the terms of Sections 1 and 2 above on a medium
##     customarily used for software interchange; or,

##     c) Accompany it with the information you received as to the offer
##     to distribute corresponding source code.  (This alternative is
##     allowed only for noncommercial distribution and only if you
##     received the program in object code or executable form with such
##     an offer, in accord with Subsection b above.)

## The source code for a work means the preferred form of the work for
## making modifications to it.  For an executable work, complete source
## code means all the source code for all modules it contains, plus any
## associated interface definition files, plus the scripts used to
## control compilation and installation of the executable.  However, as a
## special exception, the source code distributed need not include
## anything that is normally distributed (in either source or binary
## form) with the major components (compiler, kernel, and so on) of the
## operating system on which the executable runs, unless that component
## itself accompanies the executable.

## If distribution of executable or object code is made by offering
## access to copy from a designated place, then offering equivalent
## access to copy the source code from the same place counts as
## distribution of the source code, even though third parties are not
## compelled to copy the source along with the object code.
## 
##   4. You may not copy, modify, sublicense, or distribute the Program
## except as expressly provided under this License.  Any attempt
## otherwise to copy, modify, sublicense or distribute the Program is
## void, and will automatically terminate your rights under this License.
## However, parties who have received copies, or rights, from you under
## this License will not have their licenses terminated so long as such
## parties remain in full compliance.

##   5. You are not required to accept this License, since you have not
## signed it.  However, nothing else grants you permission to modify or
## distribute the Program or its derivative works.  These actions are
## prohibited by law if you do not accept this License.  Therefore, by
## modifying or distributing the Program (or any work based on the
## Program), you indicate your acceptance of this License to do so, and
## all its terms and conditions for copying, distributing or modifying
## the Program or works based on it.

##   6. Each time you redistribute the Program (or any work based on the
## Program), the recipient automatically receives a license from the
## original licensor to copy, distribute or modify the Program subject to
## these terms and conditions.  You may not impose any further
## restrictions on the recipients' exercise of the rights granted herein.
## You are not responsible for enforcing compliance by third parties to
## this License.

##   7. If, as a consequence of a court judgment or allegation of patent
## infringement or for any other reason (not limited to patent issues),
## conditions are imposed on you (whether by court order, agreement or
## otherwise) that contradict the conditions of this License, they do not
## excuse you from the conditions of this License.  If you cannot
## distribute so as to satisfy simultaneously your obligations under this
## License and any other pertinent obligations, then as a consequence you
## may not distribute the Program at all.  For example, if a patent
## license would not permit royalty-free redistribution of the Program by
## all those who receive copies directly or indirectly through you, then
## the only way you could satisfy both it and this License would be to
## refrain entirely from distribution of the Program.

## If any portion of this section is held invalid or unenforceable under
## any particular circumstance, the balance of the section is intended to
## apply and the section as a whole is intended to apply in other
## circumstances.

## It is not the purpose of this section to induce you to infringe any
## patents or other property right claims or to contest validity of any
## such claims; this section has the sole purpose of protecting the
## integrity of the free software distribution system, which is
## implemented by public license practices.  Many people have made
## generous contributions to the wide range of software distributed
## through that system in reliance on consistent application of that
## system; it is up to the author/donor to decide if he or she is willing
## to distribute software through any other system and a licensee cannot
## impose that choice.

## This section is intended to make thoroughly clear what is believed to
## be a consequence of the rest of this License.
## 
##   8. If the distribution and/or use of the Program is restricted in
## certain countries either by patents or by copyrighted interfaces, the
## original copyright holder who places the Program under this License
## may add an explicit geographical distribution limitation excluding
## those countries, so that distribution is permitted only in or among
## countries not thus excluded.  In such case, this License incorporates
## the limitation as if written in the body of this License.

##   9. The Free Software Foundation may publish revised and/or new versions
## of the General Public License from time to time.  Such new versions will
## be similar in spirit to the present version, but may differ in detail to
## address new problems or concerns.

## Each version is given a distinguishing version number.  If the Program
## specifies a version number of this License which applies to it and "any
## later version", you have the option of following the terms and conditions
## either of that version or of any later version published by the Free
## Software Foundation.  If the Program does not specify a version number of
## this License, you may choose any version ever published by the Free Software
## Foundation.

##   10. If you wish to incorporate parts of the Program into other free
## programs whose distribution conditions are different, write to the author
## to ask for permission.  For software which is copyrighted by the Free
## Software Foundation, write to the Free Software Foundation; we sometimes
## make exceptions for this.  Our decision will be guided by the two goals
## of preserving the free status of all derivatives of our free software and
## of promoting the sharing and reuse of software generally.

## 			    NO WARRANTY

##   11. BECAUSE THE PROGRAM IS LICENSED FREE OF CHARGE, THERE IS NO WARRANTY
## FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW.  EXCEPT WHEN
## OTHERWISE STATED IN WRITING THE COPYRIGHT HOLDERS AND/OR OTHER PARTIES
## PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED
## OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
## MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.  THE ENTIRE RISK AS
## TO THE QUALITY AND PERFORMANCE OF THE PROGRAM IS WITH YOU.  SHOULD THE
## PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF ALL NECESSARY SERVICING,
## REPAIR OR CORRECTION.

##   12. IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING
## WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MAY MODIFY AND/OR
## REDISTRIBUTE THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES,
## INCLUDING ANY GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING
## OUT OF THE USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED
## TO LOSS OF DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY
## YOU OR THIRD PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER
## PROGRAMS), EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGES.

## 		     END OF TERMS AND CONDITIONS
## 

