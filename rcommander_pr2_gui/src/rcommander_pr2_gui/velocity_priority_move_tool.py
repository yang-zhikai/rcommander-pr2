import rcommander.tool_utils as tu
import pypr2.tf_utils as tfu
import pypr2.pr2_utils as p2u

from PyQt4.QtGui import *
from PyQt4.QtCore import *

import rospy
import tf
import geometry_msgs.msg as geo
import tf.transformations as tr
import smach
from object_manipulator.convert_functions import *

import numpy as np
import math
import threading
import time

def pose_distance(ps_a, ps_b, tflistener):
    #put both into the same frame
    ps_a_fb = change_pose_stamped_frame(tflistener, ps_a, ps_b.header.frame_id)
    g_T_a = pose_to_mat(ps_a_fb.pose)
    g_T_b = pose_to_mat(ps_b.pose)

    a_T_b = g_T_a**-1 * g_T_b

    desired_trans = a_T_b[0:3, 3].copy()
    a_T_b[0:3, 3] = 0
    desired_angle, desired_axis, _ = tf.transformations.rotation_from_matrix(a_T_b)
    return desired_trans, desired_angle, desired_axis

def interpolate_pose_stamped(pose_stamped_a, pose_stamped_b, frac):
    apose = pose_stamped_a.pose
    bpose = pose_stamped_b.pose
    ap = np.matrix([apose.position.x, apose.position.y, apose.position.z])
    bp = np.matrix([bpose.position.x, bpose.position.y, bpose.position.z])
    ip = ap + (bp - ap) * frac

    aq = [apose.orientation.x, apose.orientation.y, apose.orientation.z,\
            apose.orientation.w]
    bq = [bpose.orientation.x, bpose.orientation.y, bpose.orientation.z,\
            bpose.orientation.w]
    iq = tr.quaternion_slerp(aq, bq, frac)

    ps = geo.PoseStamped()
    ps.header = pose_stamped_b.header
    ps.pose.position.x = ip[0,0]
    ps.pose.position.y = ip[0,1]
    ps.pose.position.z = ip[0,2]
    ps.pose.orientation.x = iq[0]
    ps.pose.orientation.y = iq[1]
    ps.pose.orientation.z = iq[2]
    ps.pose.orientation.w = iq[3]
    return ps


class VelocityPriorityMoveTool(p2u.SE3Tool, p2u.LiveUpdateListTool):

    LEFT_CONTROL_FRAME = rospy.get_param('/l_cart/tip_name')
    RIGHT_CONTROL_FRAME = rospy.get_param('/r_cart/tip_name')
    LEFT_TIP = '/l_gripper_tool_frame'
    RIGHT_TIP = '/r_gripper_tool_frame'
    MIN_TIME = .01
    COMMAND_FRAME = '/torso_lift_link'

    def __init__(self, rcommander):
        p2u.SE3Tool.__init__(self)
        p2u.LiveUpdateListTool.__init__(self, rcommander, 'velocity_priority', 
                'Velocity Priority', VelocityPriorityState)
        self.default_frame = '/torso_lift_link'
        self.tf_listener = rcommander.tf_listener


    def fill_property_box(self, pbox):
        formlayout = pbox.layout()
        frame_box = self.make_task_frame_box(pbox)
        group_boxes = self.make_se3_boxes(pbox)
        self.arm_radio_boxes, self.arm_radio_buttons =\
                tu.make_radio_box(pbox, ['Left', 'Right'], 'arm')

        #self.list_manager = p2u.ListManager(self.get_current_data_cb, 
        #        self.set_current_data_cb, None, name_preffix='point')

        self.pose_buttons_holder = QWidget(pbox)
        self.lbb_hlayout = QHBoxLayout(self.pose_buttons_holder)

        self.list_manager = self.make_live_update_gui_elements(self.pose_buttons_holder, 
                                                                'point')
        list_widgets = self.list_manager.make_widgets(pbox, self.rcommander)

        self.time_box = QDoubleSpinBox(pbox)
        self.time_box.setMinimum(0)
        self.time_box.setMaximum(1000.)
        self.time_box.setSingleStep(.1)

        self.joint_angles_hidden = None

        formlayout.addRow('&Frame', frame_box)
        formlayout.addRow('&Arm', self.arm_radio_boxes)
        formlayout.addRow('&Duration', self.time_box)

        for gb in group_boxes:
            formlayout.addRow(gb)

        #self.lbb_hlayout.addWidget(self.pose_button)
        #self.lbb_hlayout.addWidget(self.add_pose_button)

        formlayout.addRow(self.pose_buttons_holder)

        for gb in list_widgets:
            formlayout.addRow(gb)

        items_to_monitor = [self.time_box]
        items_to_monitor += self.get_all_data_input_widgets()
        self.list_manager.monitor_changing_values_in(self.rcommander, 
                items_to_monitor)

        self.reset()

    def get_data_update_from_robot_cb(self):
        try:
            frame_described_in = str(self.frame_box.currentText())
            arm = tu.selected_radio_button(self.arm_radio_buttons).lower()
            if arm == 'right':
                arm_tip_frame = VelocityPriorityMoveTool.RIGHT_TIP
            else:
                arm_tip_frame = VelocityPriorityMoveTool.LEFT_TIP

            self.tf_listener.waitForTransform(frame_described_in, arm_tip_frame, 
                    rospy.Time(), rospy.Duration(2.))

            trans, quat = self.tf_listener.lookupTransform(frame_described_in, 
                                                            arm_tip_frame, 
                                                            rospy.Time(0))
            pose = geo.Pose()
            pose.position = geo.Point(*trans)
            pose.orientation = geo.Quaternion(*quat)
            
            return {'arm': arm, 'pose_stamped': stamp_pose(pose, frame_described_in),
                    'time': self.time_box.value()}

        except (tf.Exception, tf.LookupException, tf.ConnectivityException):
            self.set_update_mode(False)
            QMessageBox.information(self.rcommander, self.button_name, 
             'Error looking up frame named "%s".  If this is a task frame, is it highlighted red?' % str(self.frame_box.currentText()))
            return None

    ## Inherited.  Returns field names from p2u.SE3Tool for live updating purposes.
    def get_colorable_fields(self):
        return ['xline', 'yline', 'zline', 'phi_line', 'theta_line', 'psi_line']

    def get_current_data_from_gui_fields_cb(self):
        arm = tu.selected_radio_button(self.arm_radio_buttons).lower()
        posestamped = self.get_posestamped()
        t = self.time_box.value()
        return {'arm': arm, 'pose_stamped': posestamped, 'time': t}

    def set_current_data_to_gui_fields_cb(self, data):
        if 'left' == data['arm']:
            self.arm_radio_buttons[0].setChecked(True)
        if data['arm'] == 'right':
            self.arm_radio_buttons[1].setChecked(True)
        self.set_posestamped(data['pose_stamped'])
        self.time_box.setValue(data['time'])

    def new_node(self, name=None):
        p2u.LiveUpdateListTool.new_node(self, name)
        if name == None:
            nname = self.name + str(self.counter)
        else:
            nname = name
        data = self.list_manager.get_data()
        #name == None means that it's a throwaway node
        if len(data) == 0 and name != None:
            return None

        return VelocityPriorityState(nname, data)

    def set_node_properties(self, node):
        self.list_manager.set_data(node.pose_stamps_list)
        self.list_manager.select_default_item()

    def reset(self):
        self.arm_radio_buttons[1].setChecked(True)
        for vr in [self.xline, self.yline, self.zline, self.phi_line, \
                self.theta_line, self.psi_line]: 
            vr.setValue(0.0)
        self.frame_box.setCurrentIndex(self.frame_box.findText(\
                self.default_frame))
        self.time_box.setValue(0.5)
        p2u.LiveUpdateListTool.reset(self)


class VelocityPriorityState(tu.StateBase):

    def __init__(self, name, pose_stamps_list):
        tu.StateBase.__init__(self, name)
        self.pose_stamps_list = pose_stamps_list

    def get_smach_state(self):
        return VelocityPriorityStateSmach([p['data'] for p in \
                self.pose_stamps_list])


class PlayTrajectory(threading.Thread):

    def __init__(self, cart_pub, messages, controller_frame, 
            tip_frame, tf_listener):
        threading.Thread.__init__(self)
        self.cart_pub = cart_pub
        self.messages = messages
        self.stop = False
        self.controller_frame = controller_frame
        self.tip_frame = tip_frame
        self.tf_listener = tf_listener
        self.step_resolution = 1./100. #50hz
        self.exception = None

    def set_stop(self):
        self.stop = True

    def run(self):
        #Change duration to cumulative time.
        try:
            if len(self.messages) == 0:
                return

            #put in the current pose so that we'll interpolate there
            messages = []
            frame_described_in = self.messages[0]['pose_stamped'].header.frame_id
            if self.messages[0]['arm'] == 'left':
                arm_tip_frame = VelocityPriorityMoveTool.LEFT_TIP
            else:
                arm_tip_frame = VelocityPriorityMoveTool.RIGHT_TIP
            
            p_arm = tfu.tf_as_matrix(self.tf_listener.lookupTransform(\
                frame_described_in, arm_tip_frame, rospy.Time(0)))
            trans, rotation = tr.translation_from_matrix(p_arm), \
                    tr.quaternion_from_matrix(p_arm)
            initial_pose = geo.PoseStamped()
            initial_pose.pose.position.x = trans[0]
            initial_pose.pose.position.y = trans[1]
            initial_pose.pose.position.z = trans[2]
            initial_pose.pose.orientation.x = rotation[0]
            initial_pose.pose.orientation.y = rotation[1]
            initial_pose.pose.orientation.z = rotation[2]
            initial_pose.pose.orientation.w = rotation[3]
            initial_pose.header = self.messages[0]['pose_stamped'].header

            current_self_messages = [{'arm': self.messages[0]['arm'],
                                      'pose_stamped': initial_pose,
                                      'time': self.messages[0]['time']}]
            current_self_messages = current_self_messages + self.messages

            #interpolate
            for msg_a, msg_b, idx_a in zip(current_self_messages[:-1], \
                    current_self_messages[1:], 
                    range(len(current_self_messages[:-1]))):
                n_steps = int(np.floor(msg_b['time'] / self.step_resolution))
                if n_steps == 0:
                    messages.append(msg_a)
                else:
                    for i in range(n_steps):
                        ps    = interpolate_pose_stamped(
                                msg_a['pose_stamped'], 
                                msg_b['pose_stamped'], i/float(n_steps))
                        msg_i = {'arm': msg_a['arm'],
                                 'pose_stamped': ps,
                                 'time': self.step_resolution}
                        messages.append(msg_i)

            messages.append({'arm': self.messages[-1]['arm'],
                             'pose_stamped': self.messages[-1]['pose_stamped'],
                             'time': self.step_resolution})

            timeslp = [0.0]
            for idx, message in enumerate(messages[1:]):
                timeslp.append(message['time'] + timeslp[idx])

            current_pose = tfu.tf_as_matrix(
                    self.tf_listener.lookupTransform(
                        VelocityPriorityMoveTool.COMMAND_FRAME, 
                        self.controller_frame, rospy.Time(0)))

            wall_start_time = rospy.get_rostime().to_time()
            for t, el in zip(timeslp, messages):
                #Sleep if needed
                cur_time = rospy.get_rostime().to_time()
                wall_time_from_start = cur_time - wall_start_time
                sleep_time = (t - wall_time_from_start) - .005
                if sleep_time > 0:
                    time.sleep(sleep_time)

                if self.stop:
                    return

                #Our command is in tip frame, but controller is operating in
                #wrist frame
                tip_torso = change_pose_stamped_frame(self.tf_listener, 
                        el['pose_stamped'], 
                        VelocityPriorityMoveTool.COMMAND_FRAME)
                tll_T_tip = pose_to_mat(tip_torso.pose)
                tip_T_wrist = tfu.tf_as_matrix(
                        self.tf_listener.lookupTransform(
                            self.tip_frame, 
                            self.controller_frame, rospy.Time(0)))
                tll_T_wrist = tll_T_tip * tip_T_wrist
                wrist_torso = stamp_pose(mat_to_pose(tll_T_wrist), \
                                        'torso_lift_link')

                #Send
                self.cart_pub.publish(wrist_torso)
        except (tf.Exception, tf.LookupException, tf.ConnectivityException):
            if self.messages[0]['pose_stamped'].header.frame_id == '/task_frame':
                self.exception = tu.TaskFrameError(str(self.__class__), 
                        VelocityPriorityMoveTool.COMMAND_FRAME)
            else:
                self.exception = tu.FrameError(str(self.__class__), 
                        self.messages[0]['pose_stamped'].header.frame_id, 
                        VelocityPriorityMoveTool.COMMAND_FRAME)
        except Exception, e:
            self.exception = e



class VelocityPriorityStateSmach(smach.State):

    LEFT_CONTROL_FRAME  = rospy.get_param('/l_cart/tip_name')
    RIGHT_CONTROL_FRAME = rospy.get_param('/r_cart/tip_name')

    def __init__(self, poses_list):
        smach.State.__init__(self, 
                outcomes = ['succeeded', 'preempted', 'failed'], 
                input_keys = [], output_keys = [])
        self.poses_list = poses_list
        self.lcart = rospy.Publisher('/l_cart/command_pose', geo.PoseStamped)
        self.rcart = rospy.Publisher('/r_cart/command_pose', geo.PoseStamped)
        self.robot = None

    def set_robot(self, robot_obj):
        if robot_obj != None:
            self.controller_manager = robot_obj.controller_manager
            self.robot = robot_obj

    def execute(self, userdata):
        #Sort into two lists
        lp = []
        rp = []
        for p in self.poses_list:
            #print p
            #print p.keys()
            if p['arm'] == 'left':
                lp.append(p)
            else:
                rp.append(p)

        if len(lp) > 0 and len(rp) > 0:
            arm = 'both'
        elif len(lp) > 0:
            arm = 'left'
        elif len(rp) > 0:
            arm = 'right'
        else:
            raise RuntimeError('Don\'t know which arm to use!')

        status, started, stopped = self.controller_manager.cart_mode(arm)
        is_task_frame = False

        try:
            if len(lp) > 0:
                is_task_frame = lp[0]['pose_stamped'].header.frame_id == '/task_frame'
                self.robot.tf_listener.waitForTransform(lp[0]['pose_stamped'].header.frame_id,
                        VelocityPriorityMoveTool.LEFT_TIP,
                        rospy.Time(), rospy.Duration(5.))

            if len(rp) > 0:
                is_task_frame = rp[0]['pose_stamped'].header.frame_id == '/task_frame'
                self.robot.tf_listener.waitForTransform(rp[0]['pose_stamped'].header.frame_id,
                        VelocityPriorityMoveTool.RIGHT_TIP,
                        rospy.Time(), rospy.Duration(5.))

        except (tf.Exception, tf.LookupException, tf.ConnectivityException):
            if is_task_frame:
                raise tu.TaskFrameError(str(self.__class__), 
                        VelocityPriorityMoveTool.LEFT_TIP)
            else:
                raise tu.FrameError(str(self.__class__), 
                        lp[0]['pose_stamped'].header.frame_id, 
                        VelocityPriorityMoveTool.LEFT_TIP)

        lpthread = PlayTrajectory(self.lcart, lp, 
                VelocityPriorityMoveTool.LEFT_CONTROL_FRAME,
                VelocityPriorityMoveTool.LEFT_TIP, self.robot.tf_listener)
        rpthread = PlayTrajectory(self.rcart, rp, 
                VelocityPriorityMoveTool.RIGHT_CONTROL_FRAME,
                VelocityPriorityMoveTool.RIGHT_TIP, self.robot.tf_listener)

        lpthread.start()
        rpthread.start()

        r = rospy.Rate(100)
        preempted = False
        finished = False
        while not finished:
            #we have been preempted
            if self.preempt_requested():
                rospy.loginfo('VelocityPriorityStateSmach: preempt requested')
                #self.action_client.cancel_goal()
                lpthread.set_stop()
                rpthread.set_stop()
                self.service_preempt()
                preempted = True
                break

            if not lpthread.is_alive() and not rpthread.is_alive():
                finished = True
                if lpthread.exception != None:
                    raise lpthread.exception
                if rpthread.exception != None:
                    raise rpthread.exception
                #Check that
            r.sleep()

        if preempted:
            return 'preempted'

        if finished:
            return 'succeeded'

        return 'failed'














