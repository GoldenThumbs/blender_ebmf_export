import bpy

import os
import sys
import struct as sct

import math
import mathutils as MU

from . import mesh_util as MeshUtil

from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
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
   origin: MU.Vector = MU.Vector((0, 0, 0))
   rotation: MU.Quaternion = MU.Quaternion((1, 0, 0, 0))
   scale: MU.Vector = MU.Vector((1, 1, 1))

   child_count: int = 0
   parent_id: int = -1
   last_id: int = -1
   next_id: int = -1
   root_child_id: int = -1

class ExportEBMF(Operator, ExportHelper):
   """Exports selected models in Ector Binary Model Format (.ebmf)"""
   bl_idname = "export_scene.ebmf"
   bl_label = "Ector Binary Model (.ebmf)"

   filename_ext = ".ebmf"

   filter_glob = StringProperty(default="*.ebmf", options={'HIDDEN'})

   transform = MU.Matrix.Rotation(-math.pi * 0.5, 4, 'X')

   def WriteModel(self, context: bpy.types.Context, filepath: str):
      print("Writing Ector Model...")

      view_layer = context.view_layer

      obj_active = view_layer.objects.active
      selection = context.selected_objects

      objs_to_process: list[bpy.types.Object] = []
      mesh_node_pairs: list[tuple[bpy.types.Object, int]] = []

      def CleanupObjects():
         bpy.ops.object.select_all(action='DESELECT')

         for mesh_node_pair in mesh_node_pairs:
            mesh_node_pair[0].select_set(True)

         bpy.ops.object.delete(confirm=False)

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
         
         objs_to_process.append(obj)

      if len(objs_to_process) == 0:
         self.report({'ERROR'}, "None of the selected objects were a mesh")
         return {'CANCELLED'}

      if obj_active.type != 'MESH':
         obj_active = objs_to_process[0]

      view_layer.objects.active = obj_active

      name = os.path.splitext(os.path.basename(filepath))[0]
      basedir = os.path.dirname(filepath)
      file_path = os.path.join(basedir, name)
      file_model_out = open(file_path + ".ebmf", "wb")
      file_material_out = open(file_path + ".mat", "wt")

      nodes: dict[str, NodeData] = {}
      materials: dict[str, int] = {}

      node_count: int = 0
      mesh_count: int = 0
      material_count: int = 0
      
      bpy.ops.object.select_all(action='DESELECT')
      for obj in objs_to_process:
         obj.select_set(True)
         
         bpy.ops.object.duplicate()
         new_obj = bpy.context.selected_objects[0]

         node: NodeData = NodeData()
         node.origin = obj.location.copy()
         node.scale = new_obj.scale.copy()
         
         if obj.rotation_mode == 'QUATERNION':
            node.rotation = obj.rotation_quaternion.copy()
         elif obj.rotation_mode == 'AXIS_ANGLE':
            node.rotation = MU.Quaternion(obj.rotation_axis_angle.xyz, obj.rotation_axis_angle.w)
         else:
            node.rotation = obj.rotation_euler.to_quaternion()

         nodes[obj.name] = node
         node_id = list(nodes).index(obj.name)

         node_count += 1

         MeshUtil.PrepMesh(new_obj.data, self.transform)

         bpy.ops.object.editmode_toggle()
         bpy.ops.mesh.select_all(action='DESELECT')
         bpy.ops.mesh.separate(type='MATERIAL')
         bpy.ops.object.editmode_toggle()

         material_objs = bpy.context.selected_objects
         bpy.ops.object.select_all(action='DESELECT')

         mesh_count += len(material_objs)
         material_count += len(obj.material_slots)

         for material_obj in material_objs:
            mesh_node_pairs.append((material_obj, node_id))

         for material_id, material_slot in enumerate(obj.material_slots):
            material = material_slot.material
            materials[material.name] = material_id

      file_model_out.write(sct.pack("4s", b"EBMF"))
      file_model_out.write(sct.pack("H", 1))
      file_model_out.write(sct.pack("h", -1))
      file_model_out.write(sct.pack("I", node_count))
      file_model_out.write(sct.pack("I", mesh_count))
      file_model_out.write(sct.pack("I", material_count))

      for mesh_node_pair in mesh_node_pairs:
         node_id: int = mesh_node_pair[1]
         node_name: str = list(nodes.keys())[node_id]
         node: NodeData = nodes[node_name]

         for letter in node_name:
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

      for mesh_node_pair in mesh_node_pairs:
         obj = mesh_node_pair[0]
         node_id = mesh_node_pair[1]

         has_material = len(obj.material_slots) != 0
         material_id = materials[obj.active_material.name] if has_material else 0
         MeshUtil.WriteEctorMeshToFile(file_model_out, obj, node_id, material_id)

      file_model_out.close()

      for material_id, material_name in enumerate(materials):
         file_material_out.write("\n{0}\n{{\n\tid {1};\n}}\n".format(material_name, material_id))

      file_material_out.close()

      CleanupObjects()

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