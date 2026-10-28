# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Optional MuJoCo native physics runner and 3D visualizer."""

try:
    import mujoco
    import mujoco.viewer
    HAVE_MUJOCO = True
except ImportError:
    HAVE_MUJOCO = False


MUJOCO_ARENA_XML = """<mujoco model="shoe_store_arena_lightweight">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.01" integrator="implicitfast" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
    <headlight ambient=".45 .45 .45" diffuse=".7 .7 .7"/>
  </visual>

  <worldbody>
    <!-- Floor: 2.5m x 2.4m -->
    <geom name="floor" type="plane" size="1.5 1.5 .01"
          pos="1.25 1.20 0" rgba=".22 .24 .28 1"/>

    <!-- Central Dividing Wall: X: 1.20~1.30, Y: 0.67~2.40 -->
    <geom name="central_wall" type="box" pos="1.25 1.535 0.15"
          size="0.05 0.865 0.15" rgba=".65 .68 .72 1"/>

    <!-- 67cm Transfer Gate: Y: 0.00~0.67 (Visual indicator) -->
    <geom name="gate_indicator" type="box" pos="1.25 0.335 0.001"
          size="0.05 0.335 0.001" rgba=".2 .8 .4 .3"/>

    <!-- Arena Outer Borders -->
    <geom name="border_south" type="box" pos="1.25 -0.02 0.10"
          size="1.27 0.02 0.10" rgba=".4 .4 .45 1"/>
    <geom name="border_north" type="box" pos="1.25 2.42 0.10"
          size="1.27 0.02 0.10" rgba=".4 .4 .45 1"/>
    <geom name="border_west" type="box" pos="-0.02 1.20 0.10"
          size="0.02 1.22 0.10" rgba=".4 .4 .45 1"/>
    <geom name="border_east" type="box" pos="2.52 1.20 0.10"
          size="0.02 1.22 0.10" rgba=".4 .4 .45 1"/>

    <!-- Warehouse Top Rack -->
    <geom name="wh_top_rack" type="box" pos="1.91 2.27 0.20"
          size="0.49 0.13 0.20" rgba=".72 .52 .24 1"/>

    <!-- Warehouse Right Rack -->
    <geom name="wh_right_rack" type="box" pos="2.28 1.535 0.20"
          size="0.12 0.865 0.20" rgba=".72 .52 .24 1"/>

    <!-- Store Counter & Benches -->
    <geom name="store_counter" type="box" pos="0.59 2.24 0.20"
          size="0.45 0.10 0.20" rgba=".25 .48 .62 1"/>
    <geom name="store_display_a" type="box" pos="0.63 1.37 0.15"
          size="0.19 0.08 0.15" rgba=".25 .48 .62 1"/>
    <geom name="store_bench_b" type="box" pos="0.565 0.83 0.15"
          size="0.225 0.09 0.15" rgba=".25 .48 .62 1"/>

    <!-- Pinky 1 (Orange) -->
    <body name="P1" pos="1.41 2.05 0.028">
      <joint name="P1_x" type="slide" axis="1 0 0"/>
      <joint name="P1_y" type="slide" axis="0 1 0"/>
      <joint name="P1_yaw" type="hinge" axis="0 0 1"/>
      <geom name="P1_body" type="cylinder" size="0.07 0.025" rgba=".95 .55 .15 1"/>
      <geom name="P1_lidar" type="cylinder" pos="-0.017 0 0.05"
            size="0.025 0.015" rgba=".2 .2 .2 1"/>
      <geom name="P1_dir" type="box" pos="0.04 0 0.025"
            size="0.02 0.01 0.005" rgba="1 1 1 1"/>
    </body>

    <!-- Pinky 2 (Green) -->
    <body name="P2" pos="1.41 1.85 0.028">
      <joint name="P2_x" type="slide" axis="1 0 0"/>
      <joint name="P2_y" type="slide" axis="0 1 0"/>
      <joint name="P2_yaw" type="hinge" axis="0 0 1"/>
      <geom name="P2_body" type="cylinder" size="0.07 0.025" rgba=".25 .75 .35 1"/>
      <geom name="P2_lidar" type="cylinder" pos="-0.017 0 0.05"
            size="0.025 0.015" rgba=".2 .2 .2 1"/>
      <geom name="P2_dir" type="box" pos="0.04 0 0.025"
            size="0.02 0.01 0.005" rgba="1 1 1 1"/>
    </body>

    <!-- Pinky 3 (Blue) -->
    <body name="P3" pos="1.41 1.66 0.028">
      <joint name="P3_x" type="slide" axis="1 0 0"/>
      <joint name="P3_y" type="slide" axis="0 1 0"/>
      <joint name="P3_yaw" type="hinge" axis="0 0 1"/>
      <geom name="P3_body" type="cylinder" size="0.07 0.025" rgba=".35 .55 .95 1"/>
      <geom name="P3_lidar" type="cylinder" pos="-0.017 0 0.05"
            size="0.025 0.015" rgba=".2 .2 .2 1"/>
      <geom name="P3_dir" type="box" pos="0.04 0 0.025"
            size="0.02 0.01 0.005" rgba="1 1 1 1"/>
    </body>

    <!-- Warehouse OMX Arm 1 -->
    <body name="omx_1" pos="2.015 2.105 0.04">
      <geom name="omx1_stand" type="box" size="0.12 0.08 0.04" rgba=".5 .55 .6 1"/>
      <geom name="omx1_base" type="cylinder" pos="0 0 0.06" size="0.04 0.02" rgba=".2 .2 .2 1"/>
    </body>

    <!-- Warehouse OMX Arm 2 -->
    <body name="omx_2" pos="2.015 1.5375 0.04">
      <geom name="omx2_stand" type="box" size="0.12 0.08 0.04" rgba=".5 .55 .6 1"/>
      <geom name="omx2_base" type="cylinder" pos="0 0 0.06" size="0.04 0.02" rgba=".2 .2 .2 1"/>
    </body>

    <!-- Store OMX Arm 3 -->
    <body name="omx_3" pos="0.415 1.85 0.04">
      <geom name="omx3_stand" type="box" size="0.12 0.08 0.04" rgba=".5 .55 .6 1"/>
      <geom name="omx3_base" type="cylinder" pos="0 0 0.06" size="0.04 0.02" rgba=".2 .2 .2 1"/>
    </body>
  </worldbody>
</mujoco>"""


def launch_mujoco_viewer():
    """Launch native 3D viewer if MuJoCo is available."""
    if not HAVE_MUJOCO:
        print('[cobot_simulation] MuJoCo python package not found.')
        print('[cobot_simulation] To enable 3D native viewer: pip install mujoco')
        return None

    model = mujoco.MjModel.from_xml_string(MUJOCO_ARENA_XML)
    data = mujoco.MjData(model)
    viewer = mujoco.viewer.launch_passive(model, data)
    return viewer
