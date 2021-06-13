#! /usr/bin/env python

from stretch_body.device import Device
import importlib
import urdfpy
import numpy as np
import os

# #######################################################################

class RobotCollisionModel(Device):
    """
    The RobotCollisionModel  is a base class to provide simple self-collision avoidance
    Derived (custom) classes should implement the collision logic
    It works by defining acceptible joint ranges for a defined 'workspace' of the robot
    It tests the current kinematic state of the robot, determines which of the defined
    workspaces apply, and then returns that workspace.
    A joint limit of None denotes the factory hard limit

    A custom RobotCollisionModel can be instantiated by declaring the class name / Python module name
    in the User YAML file
    """
    def __init__(self,collision_manager, name):
        Device.__init__(self, name=name)
        self.collision_manager=collision_manager

    def step(self, status):
        return {'head_pan': [None, None],'head_tilt': [None, None],'lift': [None, None],'arm': [None, None],'wrist_yaw': [None, None]}

# #######################################################################

class RobotCollision(Device):
    """
    The RobotCollisionManager manages a set of collision models, as defined in YAML.
    It is called periodically by the Robot thread.
    Each model computes the acceptible joint range given the current kinematic state of the robot.
    The RobotCollisionManager then sets the joint limits for each joint to the most restrive set of ranges
    given all models.
    """
    def __init__(self,robot):
        Device.__init__(self, name='robot_collision')
        #urdf_file = os.path.join(os.environ['HELLO_FLEET_PATH'], os.environ['HELLO_FLEET_ID'],'exported_urdf/stretch.urdf')
        #self.robot_model = urdfpy.URDF.load(urdf_file) #Kinematic model available if needed
        self.robot=robot
        self.models=[]

    def startup(self):

        model_names = []
        if self.params.get('models'):
            model_names=model_names+self.params.get('models')
            if self.robot.end_of_arm.params.get('collision_models'):
                model_names = model_names + self.robot.end_of_arm.params.get('collision_models')
        for m in model_names:
            if self.robot_params[m]['enabled']:
                module_name = self.robot_params[m]['py_module_name']
                class_name = self.robot_params[m]['py_class_name']
                self.models.append(getattr(importlib.import_module(module_name), class_name)(self))

    def step(self):
        #Compile the list of joints that may be limited
        #Then compute the limits for each from each model
        #Take the most conservative limit for each and pass it to the controller
        status=self.robot.get_status()
        limits= { 'head_pan': [None, None],'head_tilt': [None, None],'lift': [None, None],'arm': [None, None]}
        for j in self.robot.end_of_arm.joints:
            limits[j]=[None,None]

        for m in self.models:
            new_limits=m.step(status)
            for joint in new_limits.keys():
                if new_limits[joint][0] is not None:
                    if limits[joint][0] is None or new_limits[joint][0]>limits[joint][0]:
                        limits[joint][0]=new_limits[joint][0]
                if new_limits[joint][1] is not None:
                    if limits[joint][1] is None or new_limits[joint][1]<limits[joint][1]:
                        limits[joint][1]=new_limits[joint][1]


        self.robot.lift.set_soft_motion_limits(limits['lift'][0], limits['lift'][1])
        self.robot.arm.set_soft_motion_limits(limits['arm'][0], limits['arm'][1])
        self.robot.head.motors['head_tilt'].set_soft_motion_limits(limits['head_tilt'][0], limits['head_tilt'][1])
        self.robot.head.motors['head_pan'].set_soft_motion_limits(limits['head_pan'][0], limits['head_pan'][1])
        for j in self.robot.end_of_arm.joints:
            self.robot.end_of_arm.motors[j].set_soft_motion_limits(limits[j][0], limits[j][1])

# #######################################################################
"""
Helper Classes: Example for EndOfArmForwardKinematics
            cfg = {
                'joint_lift': status['lift']['pos'],
                'joint_arm_l0': status['arm']['pos']*0.25,
                'joint_arm_l1': status['arm']['pos']*0.25,
                'joint_arm_l2': status['arm']['pos']*0.25,
                'joint_arm_l3': status['arm']['pos']*0.25,
                'joint_wrist_yaw': status['end_of_arm']['wrist_yaw']['pos']
            }
            pose = self.collision_manager.robot_model.link_fk(cfg, 'link_gripper_fingertip_right',use_names=True)
            tx = pose[0][3]  # Forward
            ty = pose[1][3]  # Height
            tz = pose[2][3]  # Extension direction
            print('Height', tz)
            print('Extension', -1*ty)
            print('Forward', tx)
"""

class EndOfArmForwardKinematics():
    # Compute the FK for a tool link wrt to the fixed end_of_arm frame (link_arm_l0)
    def __init__(self):
        urdf_file = os.path.join(os.environ['HELLO_FLEET_PATH'], os.environ['HELLO_FLEET_ID'],'exported_urdf/stretch.urdf')
        np.seterr(divide='ignore', invalid='ignore')
        self.robot_model = urdfpy.URDF.load(urdf_file)

    def tool_fk(self,cfg,link):
        # returns the 4x4 transform from <link> to link_arm_l0
        #cfg: dictionary of joint positions of tool (including wrist yaw). Eg: {'joint_wrist_yaw': 0.1, 'joint_gripper_finger_right': 0.1}
        #link: name of link that is after wrist_yaw in the kinematic chain.Eg 'link_gripper_fingertip_right'
        #For reference, link_arm_l0:
        # Origin Center of first cuff
        # X: parallel to ground, points towards wrist
        # Y: Parallel to graviy, points up
        # Z:  Parallel to arm extension, points towards reach

        joint_cfg = self.robot_model._process_cfg(cfg)
        link_set = set()
        link_set.add(self.robot_model._link_map[link])

        # This is a modified version of link_fk of urdfpy
        # That stops FK at the 'link_arm_l0' of Stretch
        for lnk in self.robot_model._reverse_topo:
            if lnk not in link_set:
                continue
            pose = np.eye(4, dtype=np.float64)
            path = self.robot_model._paths_to_base[lnk]
            for i in range(len(path) - 1):
                child = path[i]
                parent = path[i + 1]
                joint = self.robot_model._G.get_edge_data(child, parent)['joint']
                cfg = None
                if joint in joint_cfg:
                    cfg = joint_cfg[joint]
                pose = joint.get_child_pose(cfg).dot(pose)
                if parent.name == 'link_arm_l0':
                    return pose
        return None