import bpy

import os
# import sys
import struct as sct

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

class ExportEBMF(Operator, ExportHelper):
   """Exports selected models in Ector Binary Model Format (.ebmf)"""
   bl_idname = "export_scene.ebmf"
   bl_label = "Ector Binary Model (.ebmf)"

   filename_ext = ".ebmf"

   filter_glob = StringProperty(default="*.ebmf", options={'HIDDEN'})

   transform = MU.Matrix.Rotation(-math.pi * 0.5, 4, 'X')

   node_count: int = 0
   mesh_count: int = 0
   material_count: int = 0

   objs_to_process: list[bpy.types.Object] = []
   mesh_node_pairs: list[tuple[bpy.types.Object, int]] = []
   empty_slot_materials: list[bpy.types.Material] = []
   material_ids: dict[str, int] = {}
   nodes: dict[str, NodeData] = {}

   export_materials: BoolProperty(name="Export Materials", default=True)

   def draw(self, context):
      layout = self.layout
      layout.use_property_split = True
      layout.use_property_decorate = False  # No animation.

      header, body = layout.panel("EBMF_export_materials", default_closed=False)
      header.label(text="Materials")
      if body:
          body.prop(self, "export_materials")

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
      self.material_ids.clear()
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

            self.report({'INFO'}, material.name)

            if material.name not in self.material_ids:
               self.material_ids[material.name] = len(self.material_ids)

         MeshUtil.PrepMesh(new_obj.data, self.transform)

         node: NodeData = NodeData(obj)

         self.node_count += 1
         self.nodes[node.name] = node
         node_id = list(self.nodes).index(obj.name)

         bpy.ops.object.editmode_toggle()
         bpy.ops.mesh.select_all(action='DESELECT')
         bpy.ops.mesh.separate(type='MATERIAL')
         bpy.ops.object.editmode_toggle()

         material_objs = bpy.context.selected_objects

         self.mesh_count += len(material_objs)

         for material_obj in material_objs:
            self.mesh_node_pairs.append((material_obj, node_id))

         bpy.ops.object.select_all(action='DESELECT')

      self.material_count = len(self.material_ids)

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
         material_id = self.material_ids[obj.material_slots[0].material.name] if has_material else 0
         self.report({'INFO'}, "{} has material {} with id {:d}".format(obj.name, obj.material_slots[0].material.name, material_id))
         MeshUtil.WriteEctorMeshToFile(file_model_out, obj, node_id, material_id)

      file_model_out.close()

      if self.export_materials:
         file_material_out = open(file_path + ".mat", "wt")

         for material_id, material_name in enumerate(self.material_ids):
            file_material_out.write("\n{0}\n{{\n\tid = {1};\n}}\n".format(material_name, material_id))

         file_material_out.close()

      self.CleanupObjects()

      view_layer.objects.active = obj_active

      for obj in selection:
         obj.select_set(True)

      print("Model Data Written to File:", file_path)

      return {'FINISHED'}

   def execute(self, context):
      return self.WriteModel(context, self.filepath)


# Only needed if you want to add into a dynamic menu
def menu_func_export(self, context):
   self.layout.operator(ExportEBMF.bl_idname, text = ExportEBMF.bl_label)

def register():
   bpy.utils.register_class(ExportEBMF)
   bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
   bpy.utils.unregister_class(ExportEBMF)
   bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == "__main__":
   register()

   bpy.ops.export_scene.ebmf('INVOKE_DEFAULT')
