# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import nuke
import nukescripts

import sgtk

from sgtk import TankError
from sgtk.platform.qt import QtGui

import sys
sys.path.append("/barcelonafs/2d_share/shotgunPipelineConfigurations/sg_API__sg_Daemon")
import shotgun_api3
sg = shotgun_api3.Shotgun("https://gwbar.shotgunstudio.com",
                          script_name="connectionScript",
                          api_key="rvwhwpefu~evfjmog7hbGzqoe")

HookClass = sgtk.get_hook_baseclass()


class SceneOperation(HookClass):
    """
    Hook called to perform an operation with the
    current scene
    """

    def execute(self, operation, file_path, context, parent_action, file_version, read_only, **kwargs):
        """
        Main hook entry point

        :param operation:       String
                                Scene operation to perform

        :param file_path:       String
                                File path to use if the operation
                                requires it (e.g. open)

        :param context:         Context
                                The context the file operation is being
                                performed in.

        :param parent_action:   This is the action that this scene operation is
                                being executed for.  This can be one of:
                                - open_file
                                - new_file
                                - save_file_as
                                - version_up

        :param file_version:    The version/revision of the file to be opened.  If this is 'None'
                                then the latest version should be opened.

        :param read_only:       Specifies if the file should be opened read-only or not

        :returns:               Depends on operation:
                                'current_path' - Return the current scene
                                                 file path as a String
                                'reset'        - True if scene was reset to an empty
                                                 state, otherwise False
                                all others     - None
        """
        # We need to see which mode of Nuke we're in. If this is Hiero or
        # Nuke Studio, then we have a separate scene operation routine to
        # use. We're checking that the "hiero_enabled" attribute exists
        # to ensure that this works properly with pre-v0.4.x versions of
        # the tk-nuke engine. If that one attribute exists, then we can be
        # confident that the "studio_enabled" attribute is also available,
        # so there's no need to check that.
        #
        # If there is ever a situation where Hiero- or Nuke Studio-specific
        # logic is required that doesn't also apply to the other, then this
        # conditional could be broken up between hiero_enabled and
        # studio_enabled cases that call through to Nuke Studio and Hiero
        # specific methods.

        engine = self.parent.engine

        if hasattr(engine, "hiero_enabled") and (engine.hiero_enabled or engine.studio_enabled):
            return self._scene_operation_hiero_nukestudio(
                operation,
                file_path,
                context,
                parent_action,
                file_version,
                read_only,
                **kwargs
            )

        # If we didn't hit the Hiero or Nuke Studio case above, we can
        # continue with the typical Nuke scene operation logic.
        if file_path:
            file_path = file_path.replace("/", os.path.sep)

        if operation == "current_path":
            # return the current script path
            return nuke.root().name().replace("/", os.path.sep)

        if operation == "prepare_new":
            # get the app from the hook
            app = self.parent
            # now get work files settings so that we can work out what template we should be using to save with
            app_settings = sgtk.platform.find_app_settings(
                app.engine.name, app.name, app.sgtk, context, app.engine.instance_name
            )
            # get the template name from the settings
            template_name = app_settings[0]['settings']['template_work']
            # using the template name get an template object
            template = app.sgtk.templates[template_name]

            # now use the context to resolve as many of the template fields as possible
            fields = context.as_template_fields(template)

            # The name of the shot
            entity = context.entity
            shotEntity = entity['name']
            shotName = shotEntity.replace("_", "")
            fields['name'] = shotName
            # The version can't be resolved from context so we must add the value
            fields['version'] = 1

            # now resolve the template path using the field values.
            resolved_path = template.apply_fields(fields)
            nuke.scriptSaveAs(resolved_path)
            self._projectSettingsDefault()
            self._productionInfo()
	    self._viewerInput()
            self._createReadNode()
            self._createReadNode2()
            self._createReadNode3()
            self._createReadNode4()
            self._create_quicktime()


        elif operation == "open":
            # open the specified script
            nuke.scriptOpen(file_path)

            # reset any write node render paths:
            if self._reset_write_node_render_paths():
                # something changed so make sure to save the script again:
                nuke.scriptSave()

        elif operation == "save":
            # save the current script:
            nuke.scriptSave()

        elif operation == "save_as":
            old_path = nuke.root()["name"].value()
            try:
                # rename script:
                nuke.root()["name"].setValue(file_path)

                # reset all write nodes:
                self._reset_write_node_render_paths()

                # save script:
                nuke.scriptSaveAs(file_path, -1)
            except Exception, e:
                # something went wrong so reset to old path:
                nuke.root()["name"].setValue(old_path)
                raise TankError("Failed to save scene %s", e)

        elif operation == "reset":
            """
            Reset the scene to an empty state
            """
            while nuke.root().modified():
                # changes have been made to the scene
                res = QtGui.QMessageBox.question(None,
                                                 "Save your script?",
                                                 "Your script has unsaved changes. Save before proceeding?",
                                                 QtGui.QMessageBox.Yes|QtGui.QMessageBox.No|QtGui.QMessageBox.Cancel)

                if res == QtGui.QMessageBox.Cancel:
                    return False
                elif res == QtGui.QMessageBox.No:
                    break
                else:
                    nuke.scriptSave()

            # now clear the script:
            nuke.scriptClear()

            return True

    def _get_current_hiero_project(self):
        """
        Returns the current project based on where in the UI the user clicked
        """
        import hiero

        # get the menu selection from hiero engine
        selection = self.parent.engine.get_menu_selection()

        if len(selection) != 1:
            raise TankError("Please select a single Project!")

        if not isinstance(selection[0] , hiero.core.Bin):
            raise TankError("Please select a Hiero Project!")

        project = selection[0].project()
        if project is None:
            # apparently bins can be without projects (child bins I think)
            raise TankError("Please select a Hiero Project!")

        return project

    def _reset_write_node_render_paths(self):
        """
        Use the tk-nuke-writenode app interface to find and reset
        the render path of any Shotgun Write nodes in the current script
        """
        write_node_app = self.parent.engine.apps.get("tk-nuke-writenode")
        if not write_node_app:
            return False

        # only need to forceably reset the write node render paths if the app version
        # is less than or equal to v0.1.11
        from distutils.version import LooseVersion
        if (write_node_app.version == "Undefined"
            or LooseVersion(write_node_app.version) > LooseVersion("v0.1.11")):
            return False

        write_nodes = write_node_app.get_write_nodes()
        for write_node in write_nodes:
            write_node_app.reset_node_render_path(write_node)

        return len(write_nodes) > 0

    def _scene_operation_hiero_nukestudio(
        self, operation, file_path, context, parent_action, file_version, read_only, **kwargs
    ):
        """
        Scene operation logic for Hiero and Nuke Studio modes of Nuke.

        :param operation:       String
                                Scene operation to perform

        :param file_path:       String
                                File path to use if the operation
                                requires it (e.g. open)

        :param context:         Context
                                The context the file operation is being
                                performed in.

        :param parent_action:   This is the action that this scene operation is
                                being executed for.  This can be one of:
                                - open_file
                                - new_file
                                - save_file_as
                                - version_up

        :param file_version:    The version/revision of the file to be opened.  If this is 'None'
                                then the latest version should be opened.

        :param read_only:       Specifies if the file should be opened read-only or not

        :returns:               Depends on operation:
                                'current_path' - Return the current scene
                                                 file path as a String
                                'reset'        - True if scene was reset to an empty
                                                 state, otherwise False
                                all others     - None
        """
        import hiero

        if operation == "current_path":
            # return the current script path
            project = self._get_current_hiero_project()
            curr_path = project.path().replace("/", os.path.sep)
            return curr_path

        elif operation == "open":
            # Manually fire the kBeforeProjectLoad event in order to work around a bug in Hiero.
            # The Foundry has logged this bug as:
            #   Bug 40413 - Python API - kBeforeProjectLoad event type is not triggered
            #   when calling hiero.core.openProject() (only triggered through UI)
            # It exists in all versions of Hiero through (at least) v1.9v1b12.
            #
            # Once this bug is fixed, a version check will need to be added here in order to
            # prevent accidentally firing this event twice. The following commented-out code
            # is just an example, and will need to be updated when the bug is fixed to catch the
            # correct versions.
            # if (hiero.core.env['VersionMajor'] < 1 or
            #     hiero.core.env['VersionMajor'] == 1 and hiero.core.env['VersionMinor'] < 10:
            hiero.core.events.sendEvent("kBeforeProjectLoad", None)

            # open the specified script
            hiero.core.openProject(file_path.replace(os.path.sep, "/"))

        elif operation == "save":
            # save the current script:
            project = self._get_current_hiero_project()
            project.save()

        elif operation == "save_as":
            project = self._get_current_hiero_project()
            project.saveAs(file_path.replace(os.path.sep, "/"))

            # ensure the save menus are displayed correctly
            _update_save_menu_items(project)

        elif operation == "reset":
            # do nothing and indicate scene was reset to empty
            return True

        elif operation == "prepare_new":
            # add a new project to hiero
            hiero.core.newProject()

    def _projectSettingsDefault(self):
        ###project settings###
        nuke.root().knob('fps').setValue(24)
        RCR = '3840 2160 RCR'
        nuke.addFormat(RCR)
        nuke.Root().knob('format').setValue('RCR')
        nuke.Root().knob('first_frame').setValue(1001)
        nuke.Root().knob('last_frame').setValue(1100)



    #def _acesProjectSettings(self):
    #    nuke.root().knob('colorManagement').setValue(1)
    #    nuke.root().knob('OCIO_config').setValue(3)
    #    nuke.root().knob('workingSpaceLUT').setValue('ACES - ACES2065-1')
    #    nuke.root().knob('monitorLut').setValue('ACES/Rec.709')
    #    nuke.root().knob('int16Lut').setValue('ACES - ACES2065-1')
    #    nuke.root().knob('floatLut').setValue('ACES - ACES2065-1')

    def _productionInfo(self):

        import sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        #tk = currentEngine.sgtk
        # get th3e current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name

        shot_data = sg.find_one("Shot", [["id", "is", ctx.entity["id"]]], ["sg_prod_notes"])
        # adding data from sg submission note column
        data = {
            "sg_prod_notes": (shot_data["sg_prod_notes"] or "")
        }
        sgProdNote = data["sg_prod_notes"]

        stickyProduction = nuke.createNode("StickyNote")
        stickyProduction.knob("label").setValue(sgProdNote)
        stickyProduction.knob("note_font_size").setValue(20)

        stickyProduction.setXpos(-185)
        stickyProduction.setXpos(-274)

    def _createReadNode(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get th3e current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate1"]
        listPath = tk.paths_from_template(outputTemplate, {entityType:entityName})
        if not listPath:
            message = 'there is no scan, please remind to set manually your project range'
            nuke.message(message)
        else:
            apath = listPath[0]
            b = os.path.splitext(apath)
            c = b[0]
            d = os.path.splitext(c)
            e = d[1]
            extLen = len(e)
            iSeqLength01 = e[1:extLen]
            iSeqLength02 = len(iSeqLength01)
            iSeqLengthStr = str(iSeqLength02)
            iSeqValue = '%0'+ iSeqLengthStr +'d'
            pathName = d[0]+ '.' + iSeqValue + '.dpx'
            bpath = pathName.replace('\\', '\\\\')
            path = bpath.replace('\\\\', '/')


            ###read node settings###
            read_node = nuke.createNode("Read")
            read_node["file"].setValue(path)
            read_node['frame_mode'].setValue('1')
            read_node['frame'].setValue('1001')
	    read_node['name'].setValue('PLATE 01')

            read_node.knob('colorspace').setValue(0)
            read_node.setXpos( -300 )
            read_node.setXpos( -500 )

	    ###create reformat foor readnode###
	    reformat = nuke.createNode('Reformat')
	    reformat.knob('filter').setValue(8)
	    reformat.knob('name').setValue('UHD 4K')
	    reformat.knob('black_outside').setValue(1)

            # find the sequence range if it has one:
            seq_range = self._find_sequence_range()

            if seq_range:
                # override the detected frame range.
                read_node["first"].setValue(seq_range[0])
                read_node["last"].setValue(seq_range[1])
                read_node["origfirst"].setValue(seq_range[0])
                read_node["origlast"].setValue(seq_range[1])

            ###frame range set up on project settings###
            nuke.Root().knob('first_frame').setValue(1001)
            nuke.Root().knob('lock_range').setValue(1)
            nuke.Root().knob('proxy_scale').setValue(1)
            a = read_node['first'].value()
            b = read_node['last'].value()
            c = b - a
            d = c + 1001
            nuke.Root().knob('last_frame').setValue(d)

    def _find_sequence_range(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate1"]
        listPath = tk.paths_from_template(outputTemplate, {entityType:entityName})

        frames = []
        for a in listPath:
            fields = outputTemplate.get_fields(a)
            frames.append(fields['SEQ'])

        # return the range
        return (min(frames), max(frames))

    def _createReadNode2(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get th3e current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate2"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})
        if not listPath:
            print ("scan 02 folder is empty")
        else:
            apath = listPath[0]
            b = os.path.splitext(apath)
            c = b[0]
            d = os.path.splitext(c)
            e = d[1]
            extLen = len(e)
            iSeqLength01 = e[1:extLen]
            iSeqLength02 = len(iSeqLength01)
            iSeqLengthStr = str(iSeqLength02)
            iSeqValue = '%0' + iSeqLengthStr + 'd'
            pathName = d[0] + '.' + iSeqValue + '.dpx'
            bpath = pathName.replace('\\', '\\\\')
            path = bpath.replace('\\\\', '/')

            ###read node settings###
            read_node = nuke.createNode("Read")
            read_node["file"].setValue(path)
            read_node['frame_mode'].setValue('1')
            read_node['frame'].setValue('1001')
            read_node.knob('colorspace').setValue(0)
	    read_node['name'].setValue('PLATE 02')

	    ###create reformat foor readnode###
	    reformat = nuke.createNode('Reformat')
	    reformat.knob('filter').setValue(8)
	    reformat.knob('name').setValue('UHD 4K')
	    reformat.knob('black_outside').setValue(1)

            # find the sequence range if it has one:
            seq_range = self._find_sequence_range02()

            if seq_range:
                # override the detected frame range.
                read_node["first"].setValue(seq_range[0])
                read_node["last"].setValue(seq_range[1])
                read_node["origfirst"].setValue(seq_range[0])
                read_node["origlast"].setValue(seq_range[1])

    def _find_sequence_range02(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate2"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})

        frames = []
        for a in listPath:
            fields = outputTemplate.get_fields(a)
            frames.append(fields['SEQ'])

        # return the range
        return (min(frames), max(frames))

    def _createReadNode3(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get th3e current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate3"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})
        if not listPath:
            print ("scan 03 folder is empty")
        else:
            apath = listPath[0]
            b = os.path.splitext(apath)
            c = b[0]
            d = os.path.splitext(c)
            e = d[1]
            extLen = len(e)
            iSeqLength01 = e[1:extLen]
            iSeqLength02 = len(iSeqLength01)
            iSeqLengthStr = str(iSeqLength02)
            iSeqValue = '%0' + iSeqLengthStr + 'd'
            pathName = d[0] + '.' + iSeqValue + '.dpx'
            bpath = pathName.replace('\\', '\\\\')
            path = bpath.replace('\\\\', '/')

            ###read node settings###
            read_node = nuke.createNode("Read")
            read_node["file"].setValue(path)
            read_node['frame_mode'].setValue('1')
            read_node['frame'].setValue('1001')
            read_node.knob('colorspace').setValue(0)
	    read_node['name'].setValue('PLATE 02')


	    ###create reformat foor readnode###
	    reformat = nuke.createNode('Reformat')
	    reformat.knob('filter').setValue(8)
	    reformat.knob('name').setValue('UHD 4K')
	    reformat.knob('black_outside').setValue(1)

            # find the sequence range if it has one:
            seq_range = self._find_sequence_range03()

            if seq_range:
                # override the detected frame range.
                read_node["first"].setValue(seq_range[0])
                read_node["last"].setValue(seq_range[1])
                read_node["origfirst"].setValue(seq_range[0])
                read_node["origlast"].setValue(seq_range[1])

    def _find_sequence_range03(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate3"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})

        frames = []
        for a in listPath:
            fields = outputTemplate.get_fields(a)
            frames.append(fields['SEQ'])

        # return the range
        return (min(frames), max(frames))

    def _createReadNode4(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get th3e current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate4"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})
        if not listPath:
            print ("scan 04 folder is empty")
        else:
            apath = listPath[0]
            b = os.path.splitext(apath)
            c = b[0]
            d = os.path.splitext(c)
            e = d[1]
            extLen = len(e)
            iSeqLength01 = e[1:extLen]
            iSeqLength02 = len(iSeqLength01)
            iSeqLengthStr = str(iSeqLength02)
            iSeqValue = '%0' + iSeqLengthStr + 'd'
            pathName = d[0] + '.' + iSeqValue + '.dpx'
            bpath = pathName.replace('\\', '\\\\')
            path = bpath.replace('\\\\', '/')

            ###read node settings###
            read_node = nuke.createNode("Read")
            read_node["file"].setValue(path)
            read_node['frame_mode'].setValue('1')
            read_node['frame'].setValue('1001')
            read_node.knob('colorspace').setValue(0)
	    read_node['name'].setValue('PLATE 02')

	    ###create reformat foor readnode###
	    reformat = nuke.createNode('Reformat')
	    reformat.knob('filter').setValue(8)
	    reformat.knob('name').setValue('UHD 4K')
	    reformat.knob('black_outside').setValue(1)

            # find the sequence range if it has one:
            seq_range = self._find_sequence_range04()

            if seq_range:
                # override the detected frame range.
                read_node["first"].setValue(seq_range[0])
                read_node["last"].setValue(seq_range[1])
                read_node["origfirst"].setValue(seq_range[0])
                read_node["origlast"].setValue(seq_range[1])

    def _find_sequence_range04(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["plate4"]
        listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})

        frames = []
        for a in listPath:
            fields = outputTemplate.get_fields(a)
            frames.append(fields['SEQ'])

        # return the range
        return (min(frames), max(frames))

    def _viewerInput(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["shot_lut"]
        lutKey = tk.paths_from_template(outputTemplate, {entityType: entityName})
        lutString = ''.join(lutKey)
        lutName = lutString.replace("\\", "/")

	# create vectorfield
	vectorfield = nuke.createNode('Vectorfield')
	vectorfield.knob('name').setValue('VIEWER_INPUT')
	vectorfield.knob('vfield_file').setValue(lutName)
	vectorfield.knob('colorspaceIn').setValue(3)
	vectorfield.knob('colorspaceOut').setValue(1)
	vectorfield.setXpos(-82)
	vectorfield.setXpos(-58)

    def _create_quicktime(self):
        ###find read path###
        import sgtk
        # get the engine we are running
        currentEngine = sgtk.platform.current_engine()
        # get shotgun engine and installation path (shotgun API)
        tk = currentEngine.sgtk
        # get the engine we are currently running in
        currentEngine = sgtk.platform.current_engine()
        # get the current context, entity type and entity name
        ctx = currentEngine.context
        # giving shot type, id, entity name
        entity = ctx.entity
        entityType = entity['type']
        entityName = entity['name']
        outputTemplate = tk.templates["edit_quicktime"]
        qtList = tk.paths_from_template(outputTemplate, {entityType: entityName})
        if not qtList:
            message = 'there is not quicktime reference from client for this shot'
            nuke.message(message)
        else:
            qtString = ''.join(qtList)
            qtName = qtString.replace("\\", "/")
            ###read node settings###
            read_node = nuke.createNode("Read")
            read_node.setXpos( 300 )
            read_node.setXpos( 30 )
            #read_node.knob('colorspace').setValue(137)
            read_node["file"].fromUserText(qtName)
            read_node.knob('name').setValue('QUICKTIME REFERENCE')
            read_node.knob('note_font_size').setValue(15)
            time_offset = nuke.createNode("TimeOffset")
            time_offset["time_offset"].setValue(10)
            nuke.autoplace(time_offset)



    def _update_save_menu_items(project):
        """
        There's a bug in Hiero when using `project.saveAs()` whereby the file menu
        text is not updated. This is a workaround for that to find the menu
        QActions and update them manually to match what Hiero should display.
        """

        import hiero

        project_path = project.path()

        # get the basename of the path without the extension
        file_base = os.path.splitext(os.path.basename(project_path))[0]

        save_action = hiero.ui.findMenuAction('foundry.project.save')
        save_action.setText("Save Project (%s)" % (file_base,))

        save_as_action = hiero.ui.findMenuAction('foundry.project.saveas')
        save_as_action.setText("Save Project As (%s)..." % (file_base,))
