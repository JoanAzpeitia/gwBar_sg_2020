import sgtk
import os
import sys
import nuke

import sys
sys.path.append("/barcelonafs/2d_share/shotgunPipelineConfigurations/sg_API__sg_Daemon")
import shotgun_api3
sg = shotgun_api3.Shotgun("https://gwbar.shotgunstudio.com",
                          script_name="connectionScript",
                          api_key="rvwhwpefu~evfjmog7hbGzqoe")


# get the engine we are running
currentEngine = sgtk.platform.current_engine()
# get shotgun engine and installation path (shotgun API)
tk = currentEngine.sgtk
# get the engine we are currently running in
currentEngine = sgtk.platform.current_engine()
ctx = currentEngine.context
# giving shot type, id, entity name
entity = ctx.entity
entityName = entity['name']
entityType = entity['type']
outputTemplate = tk.templates["nuke_shot_render_exr"]
listPath = tk.paths_from_template(outputTemplate, {entityType: entityName})
versionList = []
for a in listPath:
    fields = outputTemplate.get_fields(a)
    versionList.append(fields['version'])
    version = max(versionList)
    template = tk.templates['nuke_shot_render_exr']
    fields = ctx.as_template_fields(template)
    fields['version'] = version
    fields['name'] = entityName
    renderPath = template.apply_fields(fields)

    quicktimeTemplate = tk.templates["nuke_shot_render_movie"]
    fields['version'] = version
    qtRenderPath = quicktimeTemplate.apply_fields(fields)


# finding lut path
lutTemplate = tk.templates["shot_lut"]
lutList = tk.paths_from_template(lutTemplate, {entityType: entityName})
if not lutList:
    message = 'there is no LUT for this shot'
    nuke.message(message)
else:
    lutPath = ''.join(lutList)


# find needed information in nuke script
a = nuke.root()
b = a.knob('first_frame').getValue()
first_frame = int(b)
d = a.knob('last_frame').getValue()
last_frame = int(d)

def render():
    # create group where everything happens
    group = nuke.nodes.Group()
    # now operate inside this group
    group.begin()
    try:
        # create read node
        read = nuke.nodes.Read(name="source", file=renderPath)
        read["on_error"].setValue("black")
        read["first"].setValue(first_frame)
        read["last"].setValue(last_frame)
        read["colorspace"].setValue('linear')

        # Create the shot LUT file
        nukeLUTNode = nuke.createNode("Vectorfield")
        nukeLUTNode.setInput(0, read)
        nukeLUTNode.knob("vfield_file").setValue(lutPath)
        nukeLUTNode.knob("colorspaceIn").setValue(0)
        nukeLUTNode.knob("colorspaceOut").setValue(3)

        # create a scale node
        scale = nuke.createNode("Reformat")
        scale.setInput(0, nukeLUTNode)
        scale["type"].setValue("to box")
        scale["box_width"].setValue(1920)
        scale["box_height"].setValue(1080)
        scale["resize"].setValue("fit")
        scale["box_fixed"].setValue(True)
        scale["center"].setValue(True)
        scale["black_outside"].setValue(True)

        # find the version
        path = nuke.root().name()
        split = os.path.split(path)
        split_end = split[1]
        length = len(split_end)
        len1 = length - 3
        len2 = length - 6
        version = split_end[len2:len1]


        # now create the overlay
        netflixOverlay = nuke.nodePaste(
            "/barcelonafs/2d_share/NUKE/WORKGROUP/netflixSlate/Netflix_VFX_MEI_Template_Overlay.nk")
        netflixOverlay.setInput(0, scale)
        netflixOverlay.knob("topleft").setValue("GLASSWORKS")
        netflixOverlay.knob("topcenter").setValue("RACER")
        netflixOverlay.knob("bottomleft").setValue(version)


        # now create the slate with Netflix settings
        netflixSlate = nuke.nodePaste(
            "/barcelonafs/2d_share/NUKE/WORKGROUP/netflixSlate/Netflix_VFX_MEI_Template_Slate.nk")
        netflixSlate.setInput(0, netflixOverlay)
        netflixSlate.knob("f_version_name").setValue(version)
        if nuke.ask("is this a WIP? If you select no it will be send as FINAL"):
            netflixSlate.knob("f_submitting_for").setValue("WIP")
        else:
            netflixSlate.knob("f_submitting_for").setValue("FINAL")
        netflixSlate.knob("f_shot_name").setValue(entityName)
        netflixSlate.knob("f_shot_types").setValue("2D Comp")
        netflixSlate.knob("f_show").setValue("RACER")
        netflixSlate.knob("f_vendor").setValue("GLASSWORKS")
        netflixSlate.knob("f_media_color").setValue("GLASSWORKS")
        netflixSlate.knob("file").setValue("/barcelonafs/2d_share/shotgunPipelineConfigurations/shotguntest_9999/config/icons/gwlogo_640x640.png")


        # Create the output node
        output_node = nuke.createNode("Write")
        output_node.setInput(0, netflixSlate)
        output_node.knob("file").setValue(qtRenderPath)
        output_node.knob("file_type").setValue("mov")
        output_node.knob("colorspace").setValue("rec709")
        output_node.knob("mov64_codec").setValue("appr")
        output_node.knob("mov64_fps").setValue(24)
        output_node.knob("mov_prores_codec_profile").setValue(2)
    finally:
        group.end()

    if output_node:
        # Make sure the output folder exists
        #output_folder = os.path.dirname(output_path)
        #self.__app.ensure_folder_exists(output_folder)

        # Render the outputs, first view only
        nuke.executeMultiple(
            [output_node], ([first_frame - 1, last_frame, 1],), [nuke.views()[0]]
        )

    # Cleanup after ourselves
    output_path = qtRenderPath
    nuke.delete(group)
    return output_path
