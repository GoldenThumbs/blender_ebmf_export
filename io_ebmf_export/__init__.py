import bpy

import os
# import sys
import struct as sct

from io import BufferedWriter

import math
import mathutils as MU

from . import mesh_util as MeshUtil

from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty
from bpy.types import Operator

# import importlib.util
#
# def import_from_path(module_name, file_path):
#     sys.path.append(os.path.dirname(file_path))
#     spec = importlib.util.spec_from_file_location(module_name, file_path)
#     module = importlib.util.module_from_spec(spec)
#     sys.modules[module_name] = module
#     spec.loader.exec_module(module)
#     return module
#
# MeshUtil = import_from_path("mesh_util", "/home/renny/Dev/dungeon/utility/blender_scripts/io_ebmf_export/mesh_util.py")

class NodeData():
   name: str = ""
   origin: MU.Vector = MU.Vector((0, 0, 0))
   rotation: MU.Quaternion = MU.Quaternion((1, 0, 0, 0))
   scale: MU.Vector = MU.Vector((1, 1, 1))

   child_count: int = 0
   parent_id: int = -1
   last_id: int = -1
   next_id: int = -1
   root_child_id: int = -1

   def __init__(self, object: bpy.types.Object):
      self.name = object.name
      self.origin = object.location.copy()
      self.scale = object.scale.copy()

      if object.rotation_mode == 'QUATERNION':
         self.rotation = object.rotation_quaternion.copy()
      elif object.rotation_mode == 'AXIS_ANGLE':
         self.rotation = MU.Quaternion(object.rotation_axis_angle.xyz, object.rotation_axis_angle.w)
      else:
         self.rotation = object.rotation_euler.to_quaternion()

class Color():
   red: float = 0.0
   green: float = 0.0
   blue: float = 0.0
   alpha: float = 1.0

   def __init__(self, color: list[float] = []):
      length = len(color)

      if length >= 1:
         self.red = color[0]

      if length >= 2:
         self.green = color[1]

      if length >= 3:
         self.blue = color[2]

      if length >= 4:
         self.alpha = color[3]

   def Pow(self, power: float):
      self.red = math.pow(self.red, power)
      self.green = math.pow(self.green, power)
      self.blue = math.pow(self.blue, power)

   @property
   def ByteColor(self) -> tuple[int, int, int, int]:
      r = math.floor(self.red * 255)
      g = math.floor(self.green * 255)
      b = math.floor(self.blue * 255)
      a = math.floor(self.alpha * 255)

      return (r, g, b, a)

class ExportEBMF(Operator, ExportHelper):
   """Exports selected models in Ector Binary Model Format (.ebmf)"""
   bl_idname = "export_scene.ebmf"
   bl_label = "Ector Binary Model (.ebmf)"

   filename_ext = ".ebmf"

   filter_glob = StringProperty(default="*.ebmf", options={'HIDDEN'})

   export_materials: BoolProperty(default=True)
   export_path: StringProperty()
   export_gamma_correct_colors: BoolProperty(default=False)

   transform = MU.Matrix.Rotation(-math.pi * 0.5, 4, 'X')

   _gamma = 2.2
   _inv_gamma = 1.0 / _gamma

   @property
   def gamma(self) -> float:
      return self._gamma

   @gamma.setter
   def gamma(self, value: float):
      self._gamma = value
      self._inv_gamma = 1.0 / value

   @property
   def inv_gamma(self) -> float:
      return self._inv_gamma

   node_count: int = 0
   mesh_count: int = 0
   material_count: int = 0

   objs_to_process: list[bpy.types.Object] = []
   mesh_node_pairs: list[tuple[bpy.types.Object, int]] = []
   empty_slot_materials: list[bpy.types.Material] = []
   materials: dict[str, tuple[int, bpy.types.Material]] = {}
   nodes: dict[str, NodeData] = {}

   def draw(self, context):
      layout = self.layout
      layout.use_property_split = True
      layout.use_property_decorate = False  # No animation.

      header, body = layout.panel("EBMF_export_materials", default_closed=False)
      header.label(text="Materials")
      if body:
          body.prop(self, 'export_materials', text="Export Materials")
          body.prop(self, 'export_path', text="Root Folder")
          body.prop(self, 'export_gamma_correct_colors', text="Gamma Correct Colors")

   def CleanupObjects(self):
      bpy.ops.object.select_all(action='DESELECT')

      for mesh_node_pair in self.mesh_node_pairs:
         mesh_node_pair[0].select_set(True)

      bpy.ops.object.delete(confirm=False)

      for material in self.empty_slot_materials:
         material.user_clear()
         bpy.data.materials.remove(material)

      self.node_count = 0
      self.mesh_count = 0
      self.material_count = 0

      self.objs_to_process.clear()
      self.mesh_node_pairs.clear()
      self.empty_slot_materials.clear()
      self.materials.clear()
      self.nodes.clear()

   def ProcessObjects(self):
      bpy.ops.object.select_all(action='DESELECT')

      for obj in self.objs_to_process:
         obj.select_set(True)

         bpy.ops.object.duplicate()
         new_obj = bpy.context.selected_objects[0]
         bpy.context.view_layer.objects.active = new_obj

         obj.select_set(False)

         for material_id, material_slot in enumerate(new_obj.material_slots):
            material = material_slot.material
            if material is None:
               material = bpy.data.materials.new("{}_Slot{:d}".format(obj.name, material_id))
               material_slot.material = material

               self.empty_slot_materials.append(material)

            if material.name not in self.materials:
               self.materials[material.name] = (len(self.materials), material)

         MeshUtil.PrepMesh(new_obj.data, self.transform)

         node: NodeData = NodeData(obj)

         self.node_count += 1
         self.nodes[node.name] = node
         node_id = list(self.nodes).index(obj.name)

         bpy.ops.object.editmode_toggle()
         bpy.ops.mesh.select_all(action='DESELECT')
         bpy.ops.mesh.separate(type='MATERIAL')
         bpy.ops.object.editmode_toggle()

         material_objs: list[bpy.types.Object] = bpy.context.selected_objects

         self.mesh_count += len(material_objs)

         material_obj_string = obj.name + ".Material"
         def sort_func(element):
            string = element.name.removeprefix(material_obj_string)
            return int(string)

         for material_obj in material_objs:
            material = material_obj.material_slots[0].material
            material_id = self.materials[material.name][0]
            material_obj.name = material_obj_string + str(material_id)

         material_objs.sort(key=sort_func)

         for material_obj in material_objs:
            self.mesh_node_pairs.append((material_obj, node_id))

         bpy.ops.object.select_all(action='DESELECT')

      self.material_count = len(self.materials)

   def WriteParam(self, node: bpy.types.ShaderNode, file_material_out: BufferedWriter):
      def WriteValue(as_ints: bool = False):
         if node.bl_idname == "ShaderNodeValue":
            if as_ints:
               file_material_out.write("\tparam = {}, i, {:d};\n".format(node.name, math.floor(node.outputs[0].default_value)))

            else:
               file_material_out.write("\tparam = {}, f, {:.5g};\n".format(node.name, node.outputs[0].default_value))

      def WriteColor(as_ints: bool = False):
         if node.bl_idname == "ShaderNodeRGB":
            color: Color = Color(node.outputs[0].default_value)

            if self.export_gamma_correct_colors:
               color.Pow(self.inv_gamma)

            if as_ints:
               rgba = color.ByteColor
               file_material_out.write("\tparam = {}, i, {:d}, {:d}, {:d}, {:d};\n".format(node.name, rgba[0], rgba[1], rgba[2], rgba[3]))

            else:
               rgba = color.ByteColor
               file_material_out.write("\tparam = {}, f, {:.5g}, {:.5g}, {:.5g}, {:.5g};\n".format(node.name, color.red, color.green, color.blue, color.alpha))


      if node.label == "Param":
         WriteValue()
         WriteColor()

      if node.label == "ParamI":
         WriteValue(True)
         WriteColor(True)

   def WriteTex(self, export_path: str , tex_count: int, node: bpy.types.ShaderNode, file_material_out: BufferedWriter) -> int:

      def IsInt(string: str) -> bool:
         try:
            int(string)
            return True
         except ValueError:
            return False

      if node.bl_idname == "ShaderNodeTexImage" and node.label.startswith("Tex", 0, 3):
         image: bpy.types.Image = node.image
         if image is None:
            return

         path = bpy.path.abspath(image.filepath_raw)
         path = os.path.relpath(path, export_path)

         slot_string: str = node.label.removeprefix("Tex")
         if len(path) != 0:
            has_slot = (len(slot_string) != 0 and IsInt(slot_string))
            tex_slot = int(slot_string) if has_slot else tex_count

            file_material_out.write("\ttex = {}, {};\n".format(tex_slot, path))
            tex_count += 1

      return tex_count

   def ExportMaterials(self, file_path: str):
      if self.export_materials:
         file_material_out = open(file_path + ".mat", "wt")

         addon_preferences = bpy.context.preferences.addons[__package__].preferences
         export_path = bpy.path.abspath(self.export_path)
         if len(export_path) == 0:
            export_path = bpy.path.abspath(addon_preferences.ebmf_base_path)

         for material_name in self.materials.keys():
            material_info = self.materials[material_name]
            material_id = material_info[0]
            material = material_info[1]

            file_material_out.write("\n{}\n{{\n\tid = {};\n".format(material_name, material_id))

            tex_count = 0
            for node in material.node_tree.nodes:

               if node.label == "Surf":
                  file_material_out.write("\tsurf = {};\n".format(node.name))

               self.WriteParam(node, file_material_out)
               tex_count = self.WriteTex(export_path, tex_count, node, file_material_out)

            file_material_out.write("}\n")


         file_material_out.close()

   def WriteModel(self, context: bpy.types.Context, filepath: str):
      print("Writing Ector Model...")

      view_layer = context.view_layer

      obj_active = view_layer.objects.active
      selection = context.selected_objects

      if not obj_active.select_get():
         self.report({'ERROR'}, "The active object must be selected to export")
         return {'CANCELLED'}

      bpy.ops.object.mode_set(mode='OBJECT')
      for obj in selection:
         view_layer.objects.active = obj

         if obj.type != 'MESH':
            obj.select_set(False)
            continue

         if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

         self.objs_to_process.append(obj)

      if len(self.objs_to_process) == 0:
         self.report({'ERROR'}, "None of the selected objects were a mesh")
         return {'CANCELLED'}

      if obj_active.type != 'MESH':
         obj_active = self.objs_to_process[0]

      view_layer.objects.active = obj_active

      self.ProcessObjects()

      name = os.path.splitext(os.path.basename(filepath))[0]
      basedir = os.path.dirname(filepath)
      file_path = os.path.join(basedir, name)
      file_model_out = open(file_path + ".ebmf", "wb")

      file_model_out.write(sct.pack("4s", b"EBMF"))
      file_model_out.write(sct.pack("H", 1))
      file_model_out.write(sct.pack("h", -1))
      file_model_out.write(sct.pack("I", self.node_count))
      file_model_out.write(sct.pack("I", self.mesh_count))
      file_model_out.write(sct.pack("I", self.material_count))

      for node in self.nodes.values():

         for letter in node.name:
            file_model_out.write(sct.pack("c", bytes(letter, "ascii")))

         file_model_out.write(sct.pack("c", b'\0'))

         file_model_out.write(sct.pack("f", node.origin.x))
         file_model_out.write(sct.pack("f", node.origin.z))
         file_model_out.write(sct.pack("f",-node.origin.y))

         file_model_out.write(sct.pack("f", node.rotation.x))
         file_model_out.write(sct.pack("f", node.rotation.z))
         file_model_out.write(sct.pack("f",-node.rotation.y))
         file_model_out.write(sct.pack("f",-node.rotation.w))

         file_model_out.write(sct.pack("f", node.scale.x))
         file_model_out.write(sct.pack("f", node.scale.z))
         file_model_out.write(sct.pack("f", node.scale.y))

         file_model_out.write(sct.pack("I", node.child_count))
         file_model_out.write(sct.pack("h", node.parent_id))
         file_model_out.write(sct.pack("h", node.last_id))
         file_model_out.write(sct.pack("h", node.next_id))
         file_model_out.write(sct.pack("h", node.root_child_id))

      for mesh_node_pair in self.mesh_node_pairs:
         obj = mesh_node_pair[0]
         node_id = mesh_node_pair[1]

         has_material = len(obj.material_slots) != 0
         material_id = self.materials[obj.material_slots[0].material.name][0] if has_material else -1
         MeshUtil.WriteEctorMeshToFile(file_model_out, obj, node_id, material_id)

      file_model_out.close()
      self.ExportMaterials(file_path)
      self.CleanupObjects()

      view_layer.objects.active = obj_active

      for obj in selection:
         obj.select_set(True)

      print("Model Data Written to File:", file_path)

      return {'FINISHED'}

   def execute(self, context):
      return self.WriteModel(context, self.filepath)

class ExportEBMFPrefs(bpy.types.AddonPreferences):
    bl_idname = __package__

    ebmf_base_path: StringProperty()

    def draw(self, context):
       layout = self.layout
       row = layout.row()
       row.prop(self, "ebmf_base_path", text="Ector Base Path")

# Only needed if you want to add into a dynamic menu
def menu_func_export(self, context):
   self.layout.operator(ExportEBMF.bl_idname, text = ExportEBMF.bl_label)

def register():
   bpy.utils.register_class(ExportEBMF)
   bpy.utils.register_class(ExportEBMFPrefs)
   bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
   bpy.utils.unregister_class(ExportEBMF)
   bpy.utils.unregister_class(ExportEBMFPrefs)
   bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

if __name__ == "__main__":
   register()

   bpy.ops.export_scene.ebmf('INVOKE_DEFAULT')
