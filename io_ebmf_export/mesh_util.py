import bpy
import struct as sct

from io import BufferedWriter
import math

import mathutils
import bmesh

import numpy as np # type: ignore

MESH_ATTRIBUTE_1_CHANNEL = 0
MESH_ATTRIBUTE_2_CHANNEL = 1
MESH_ATTRIBUTE_3_CHANNEL = 2
MESH_ATTRIBUTE_4_CHANNEL = 3
MESH_ATTRIBUTE_COLOR = 5

def SplitUVIslands(mesh: bpy.types.Mesh, uv_count: int = -1):
   if len(mesh.uv_layers) == 0:
      return

   previous_active_uv = mesh.uv_layers.active_index

   tmp_bm = bmesh.new()
   tmp_bm.from_mesh(mesh)

   normals = [loop.vert.normal for face in tmp_bm.faces for loop in face.loops]

   if uv_count <= -1:
      uv_count = len(mesh.uv_layers)

   bpy.ops.object.editmode_toggle()
   bm = bmesh.from_edit_mesh(mesh)
   
   for uv_layer_i in range(uv_count):
      uv_layer = mesh.uv_layers[uv_layer_i]
      uv_layer.active = True

      bpy.ops.mesh.select_all(action='SELECT')
      bpy.ops.uv.select_all(action='SELECT')
      bpy.ops.uv.seams_from_islands(mark_sharp=False)
      bpy.ops.mesh.select_all(action='DESELECT')

      seams = [edge for edge in bm.edges if edge.seam]
      bmesh.ops.split_edges(bm, edges=seams)
   
   bmesh.update_edit_mesh(mesh, loop_triangles=False)
   bpy.ops.object.editmode_toggle()
   
   mesh.normals_split_custom_set(normals)

   if uv_count > 0:
      mesh.calc_tangents(uvmap = mesh.uv_layers[0].name)

   mesh.uv_layers[previous_active_uv].active = True
   # mesh.split_faces()

def ProcessTriangles(tri_count: int, mesh: bpy.types.Mesh):
   indices = np.empty(tri_count * 3, dtype=np.uint16)

   for face_i, loop_tri in enumerate(mesh.loop_triangles):
      for i in range(3):
         indices[face_i * 3 + i] = mesh.loops[loop_tri.loops[i]].vertex_index
   
   return indices

def ProcessVertices(vertex_count: int, mesh: bpy.types.Mesh):
   num_vertices = vertex_count * 3
   num_normals = vertex_count * 3

   vertices = np.empty(num_vertices, dtype=np.float32)
   normals = np.empty(num_normals, dtype=np.float32)

   for vert_i, vertex in enumerate(mesh.vertices):
      for i in range(3):
         vertices[vert_i * 3 + i] = vertex.co[i]
   
   for loop in mesh.loops:
      for i in range(3):
         normals[loop.vertex_index * 3 + i] = loop.normal[i]
   
   return vertices, normals

def ProcessUVs(vertex_count: int, mesh: bpy.types.Mesh, uv_count: int = -1):
   
   if len(mesh.uv_layers) == 0:
      return []

   if uv_count <= -1:
      uv_count = len(mesh.uv_layers)

   texcoords = []
   
   for texcoord_i in range(uv_count):

      texcoords.append(np.empty(vertex_count * 2, dtype=np.float32))
      uv_layer_data = mesh.uv_layers[texcoord_i].data
      for loop_i, loop in enumerate(mesh.loops):
         u, v = uv_layer_data[loop_i].uv
         
         uv_i = loop.vertex_index * 2
         texcoords[texcoord_i][uv_i + 0] = u
         texcoords[texcoord_i][uv_i + 1] = 1.0 - v
   
   return texcoords

def ProcessTangents(vertex_count: int, mesh: bpy.types.Mesh, uv_count: int):
   if uv_count <= 0:
      return np.array([])

   num_tangents = vertex_count * 4
   tangents = np.empty(num_tangents, dtype=np.float32)

   for loop in mesh.loops:
      for i in range(4):
         tangents[loop.vertex_index * 4 + i] = loop.tangent[i] if i < 3 else loop.bitangent_sign
   
   return tangents

def WriteMeshHeader(file_out: BufferedWriter, index_count: int, vertex_count: int, attribute_count: int, node_id: int, material_id: int):
   # index count
   file_out.write(sct.pack("I", index_count))

   # vertex count
   file_out.write(sct.pack("I", vertex_count))

   # node id
   file_out.write(sct.pack("i", node_id))

   # material id
   file_out.write(sct.pack("H", material_id))

   # primitive
   file_out.write(sct.pack("B", 0))

   # attribute count
   file_out.write(sct.pack("B", attribute_count))

def WriteAttributes(file_out: BufferedWriter, extra_attributes: list[int]):
   file_out.write(sct.pack("B", MESH_ATTRIBUTE_3_CHANNEL))
   file_out.write(sct.pack("B", MESH_ATTRIBUTE_3_CHANNEL))
   for attribute in extra_attributes:
      file_out.write(sct.pack("B", attribute))

def PrepMesh(mesh: bpy.types.Mesh, matrix: mathutils.Matrix):

   bpy.ops.object.editmode_toggle()
   bm = bmesh.from_edit_mesh(mesh)

   bpy.ops.mesh.select_all(action='DESELECT')

   bmesh.ops.triangulate(bm)

   sharps = [edge for edge in bm.edges if not edge.smooth]
   sharps += [edge for face in bm.faces if not face.smooth for edge in face.edges]
   sharps = list(dict.fromkeys(sharps))
   bmesh.ops.split_edges(bm, edges=sharps)

   bmesh.update_edit_mesh(mesh)
   bpy.ops.object.editmode_toggle()

   #mesh.split_faces()
   mesh.calc_loop_triangles()
   mesh.transform(matrix)

   normals = [loop.normal for loop in mesh.loops]
   mesh.normals_split_custom_set(normals)

   mesh.update()

def WriteEctorMeshToFile(file_out: BufferedWriter, obj: bpy.types.Object, node_id: int, material_id: int):
   mesh = obj.data

   bpy.ops.object.select_all(action='DESELECT')
   obj.select_set(True)

   bpy.context.view_layer.objects.active = obj

   uv_count = min(len(mesh.uv_layers), 2)

   SplitUVIslands(mesh, uv_count)

   tri_count = len(mesh.loop_triangles)
   vertex_count = len(mesh.vertices)

   attribute_count = 2 + uv_count
   
   indices = ProcessTriangles(tri_count, mesh)
   vertices, normals = ProcessVertices(vertex_count, mesh)
   texcoords = ProcessUVs(vertex_count, mesh, uv_count)
   tangents = ProcessTangents(vertex_count, mesh, uv_count)

   extra_attributes = []
   for i in range(uv_count):
      extra_attributes.append(MESH_ATTRIBUTE_2_CHANNEL)

   if tangents.size != 0:
      attribute_count += 1
      extra_attributes.append(MESH_ATTRIBUTE_4_CHANNEL)
   
   WriteMeshHeader(file_out, tri_count * 3, vertex_count, attribute_count, node_id, material_id)
   WriteAttributes(file_out, extra_attributes)
   
   for index in indices:
      file_out.write(sct.pack("H", index))
   
   for vertex in vertices:
      file_out.write(sct.pack("f", vertex))
   
   for normal in normals:
      file_out.write(sct.pack("f", normal))
      
   for texcoord_i in range(uv_count):
      for texcoord in texcoords[texcoord_i]:
         file_out.write(sct.pack("f", texcoord))

   for tangent in tangents:
      file_out.write(sct.pack("f", tangent))
