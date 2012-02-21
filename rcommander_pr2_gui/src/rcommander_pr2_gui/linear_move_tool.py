#import roslib; roslib.load_manifest('rcommander_pr2_gui')
import rcommander.tool_utils as tu
#import smach_ros
from PyQt4.QtGui import *
from PyQt4.QtCore import *
import rospy
import tf_utils as tfu
import tf.transformations as tr
import numpy as np
from object_manipulator.convert_functions import *
import ptp_arm_action.msg as ptp
import math
import geometry_msgs.msg as geo
import actionlib 
import smach
import actionlib_msgs.msg as am

#import rcommander.point_tool as ptl

#import move_base_msgs.msg as mm
#import math
##
# Options: stopping criteria
#          relative or absolute
##

#
# controller and view
# create and edits smach states
class LinearMoveTool(tu.ToolBase):

    #LEFT_TIP = 'l_gripper_tool_frame'
    #RIGHT_TIP = 'r_gripper_tool_frame'
    LEFT_TIP = rospy.get_param('/l_cart/tip_name')
    RIGHT_TIP = rospy.get_param('/r_cart/tip_name')

    def __init__(self, rcommander):
        tu.ToolBase.__init__(self, rcommander, 'linear_move', 'Linear Move', LinearMoveState)
        self.default_frame = '/torso_lift_link'
        self.tf_listener = rcommander.tf_listener

    def fill_property_box(self, pbox):
        formlayout = pbox.layout()

        self.arm_box = QComboBox(pbox)
        self.arm_box.addItem('left')
        self.arm_box.addItem('right')

        self.motion_box_position = QComboBox(pbox)
        self.motion_box_position.addItem('relative')
        self.motion_box_position.addItem('absolute')

        self.motion_box_orientation = QComboBox(pbox)
        self.motion_box_orientation.addItem('relative')
        self.motion_box_orientation.addItem('absolute')

        self.source_box_position = QComboBox(pbox)
        self.source_box_orientation = QComboBox(pbox)
        self.source_box_position.addItem(' ')
        self.source_box_orientation.addItem(' ')
        #nodes = self.rcommander.outputs_of_type(ptl.Point3DState)
        nodes = self.rcommander.outputs_of_type(geo.PoseStamped)
        for n in nodes:
            self.source_box_position.addItem(n)
            self.source_box_orientation.addItem(n)
        self.rcommander.connect(self.source_box_position, SIGNAL('currentIndexChanged(int)'),    self.source_changed_position)
        self.rcommander.connect(self.source_box_orientation, SIGNAL('currentIndexChanged(int)'), self.source_changed_orientation)

        self.xline = QLineEdit(pbox)
        self.yline = QLineEdit(pbox)
        self.zline = QLineEdit(pbox)

        self.phi_line   = QLineEdit(pbox)
        self.theta_line = QLineEdit(pbox)
        self.psi_line   = QLineEdit(pbox)

        self.trans_vel_line = QLineEdit(pbox)
        self.rot_vel_line = QLineEdit(pbox)

        #Only keep a few good frames.
        self.frame_box = QComboBox(pbox)
        for f in self.tf_listener.getFrameStrings():
            self.frame_box.addItem(f)

        self.pose_button = QPushButton(pbox)
        self.pose_button.setText('Current Pose')
        self.rcommander.connect(self.pose_button, SIGNAL('clicked()'), self.get_current_pose)

        self.time_box = QDoubleSpinBox(pbox)
        self.time_box.setMinimum(0)
        self.time_box.setMaximum(1000.)
        self.time_box.setSingleStep(.2)

        #Group Global
        formlayout.addRow("&Arm", self.arm_box)
        formlayout.addRow("&Frame", self.frame_box)
        formlayout.addRow('&Time Out', self.time_box)

        #Group Position
        position_box = QGroupBox('Position', pbox)
        position_layout = QFormLayout(position_box)
        position_box.setLayout(position_layout)

        position_layout.addRow("&Mode", self.motion_box_position)
        position_layout.addRow("&Point Input", self.source_box_position)
        position_layout.addRow("&X", self.xline)
        position_layout.addRow("&Y", self.yline)
        position_layout.addRow("&Z", self.zline)
        position_layout.addRow('&Velocity', self.trans_vel_line)
        formlayout.addRow(position_box)

        #Group Orientation
        orientation_box = QGroupBox('Orientation', pbox)
        orientation_layout = QFormLayout(orientation_box)
        orientation_box.setLayout(orientation_layout)
        
        orientation_layout.addRow("&Mode", self.motion_box_orientation)
        orientation_layout.addRow("&Point Input", self.source_box_orientation)
        orientation_layout.addRow("&Phi",   self.phi_line)
        orientation_layout.addRow("&Theta", self.theta_line)
        orientation_layout.addRow("&Psi",   self.psi_line)
        orientation_layout.addRow('&Velocity', self.rot_vel_line)
        formlayout.addRow(orientation_box)

        formlayout.addRow(self.pose_button)
        self.reset()

    def source_changed_position(self, index):
        self.source_box_position.setCurrentIndex(index)
        if str(self.source_box_position.currentText()) != ' ':
            self.xline.setEnabled(False)
            self.yline.setEnabled(False)
            self.zline.setEnabled(False)
            self.motion_box_position.setCurrentIndex(self.motion_box_position.findText('absolute'))
            self.motion_box_position.setEnabled(False)
        else:
            self.xline.setEnabled(True)
            self.yline.setEnabled(True)
            self.zline.setEnabled(True)
            self.motion_box_position.setEnabled(True)

    def source_changed_orientation(self, index):
        self.source_box_orientation.setCurrentIndex(index)
        if str(self.source_box_orientation.currentText()) != ' ':
            self.phi_line.setEnabled(False)
            self.theta_line.setEnabled(False)
            self.psi_line.setEnabled(False)
            self.motion_box_orientation.setCurrentIndex(self.motion_box_orientation.findText('absolute'))
            self.motion_box_orientation.setEnabled(False)
        else:
            self.phi_line.setEnabled(True)
            self.theta_line.setEnabled(True)
            self.psi_line.setEnabled(True)
            self.motion_box_orientation.setEnabled(True) 

    def get_current_pose(self):
        frame_described_in = str(self.frame_box.currentText())
        left = ('left' == str(self.arm_box.currentText()))
        if not left:
            arm_tip_frame = LinearMoveTool.RIGHT_TIP
        else:
            arm_tip_frame = LinearMoveTool.LEFT_TIP
        
        #print 'getting pose for', arm_tip_frame, left, str(self.arm_box.currentText())
        self.tf_listener.waitForTransform(frame_described_in, arm_tip_frame, rospy.Time(), rospy.Duration(2.))
        p_arm = tfu.tf_as_matrix(self.tf_listener.lookupTransform(frame_described_in, arm_tip_frame, rospy.Time(0)))
        trans, rotation = tr.translation_from_matrix(p_arm), tr.quaternion_from_matrix(p_arm)

        for value, vr in zip(trans, [self.xline, self.yline, self.zline]):
            vr.setText("%.3f" % value)
        for value, vr in zip(tr.euler_from_quaternion(rotation), [self.phi_line, self.theta_line, self.psi_line]):
            vr.setText("%.3f" % np.degrees(value))

        self.motion_box_position.setCurrentIndex(self.motion_box_position.findText('absolute'))
        self.motion_box_orientation.setCurrentIndex(self.motion_box_orientation.findText('absolute'))

    def new_node(self, name=None):
        trans  = [float(vr.text()) for vr in [self.xline, self.yline, self.zline]]
        angles = [float(vr.text()) for vr in [self.phi_line, self.theta_line, self.psi_line]]
        frame  = str(self.frame_box.currentText())
        trans_vel = float(str(self.trans_vel_line.text()))
        rot_vel   = float(str(self.rot_vel_line.text()))
        source_name_orientation = str(self.source_box_orientation.currentText())
        source_name_position = str(self.source_box_position.currentText())
        timeout = self.time_box.value()

        if source_name_position == ' ':
            source_name_position = None
        if source_name_orientation == ' ':
            source_name_orientation = None

        if name == None:
            nname = self.name + str(self.counter)
        else:
            nname = name

        return LinearMoveState(nname, str(self.arm_box.currentText()),
                trans,  str(self.motion_box_position.currentText()), source_name_position,
                angles, str(self.motion_box_orientation.currentText()), source_name_orientation,
                [trans_vel, rot_vel], frame, timeout)
        #state = NavigateState(nname, xy, theta, frame)
        #return state


    def set_node_properties(self, node):
        for value, vr in zip(node.trans, [self.xline, self.yline, self.zline]):
            vr.setText(str(value))
        for value, vr in zip(node.get_angles(), [self.phi_line, self.theta_line, self.psi_line]):
            vr.setText(str(value))

        self.frame_box.setCurrentIndex(self.frame_box.findText(str(node.frame)))
        self.motion_box_position.setCurrentIndex(self.motion_box_position.findText(str(node.motion_type)))
        self.motion_box_orientation.setCurrentIndex(self.motion_box_orientation.findText(str(node.motion_type)))
        self.arm_box.setCurrentIndex(self.arm_box.findText(node.arm))

        self.trans_vel_line.setText(str(node.vels[0]))
        self.rot_vel_line.setText(str(node.vels[1]))
        self.time_box.setValue(node.timeout)

        source_name_position    = node.remapping_for('position')
        if source_name_position == None:
            source_name_position = ' '
            idx_position = self.source_box_position.findText(source_name_position)
        else:
            idx_position = self.source_box_position.findText(source_name_position)
            if idx_position == -1:
                self.source_box_position.addItem(source_name_position)
                idx_position = self.source_box_position.findText(source_name_position)
        self.source_changed_orientation(idx_position)

        source_name_orientation = node.remapping_for('orientation')
        if source_name_orientation == None:
            source_name_orientation = ' '
            idx_orientation = self.source_box_orientation.findText(source_name_orientation)
        else:
            idx_orientation = self.source_box_orientation.findText(source_name_orientation)
            if idx_orientation == -1:
                self.source_box_orientation.addItem(source_name_orientation)
                idx_orientation = self.source_box_orientation.findText(source_name_orientation)
        self.source_changed_orientation(idx_orientation)


    def reset(self):
        for vr in [self.xline, self.yline, self.zline]:
            vr.setText(str(0.0))
        for vr in [self.phi_line, self.theta_line, self.psi_line]:
            vr.setText(str(0.0))

        self.frame_box.setCurrentIndex(self.frame_box.findText(self.default_frame))
        self.motion_box_position.setCurrentIndex(self.motion_box_position.findText('relative'))
        self.motion_box_orientation.setCurrentIndex(self.motion_box_orientation.findText('relative'))
        self.trans_vel_line.setText(str(.02))
        self.rot_vel_line.setText(str(.16))
        self.time_box.setValue(20)
        self.source_box_orientation.setCurrentIndex(self.source_box_orientation.findText(' '))
        self.source_box_position.setCurrentIndex(self.source_box_position.findText(' '))
        self.arm_box.setCurrentIndex(self.arm_box.findText('left'))


class LinearMoveState(tu.StateBase): # smach_ros.SimpleActionState):

    ##
    # @param name
    # @param trans list of 3 floats
    # @param angles in euler list of 3 floats
    # @param frame 
    def __init__(self, name, arm,
        trans,  motion_type_trans,  source_trans,
        angles, motion_type_angles, source_angles,
        vels, frame, timeout):

        tu.StateBase.__init__(self, name)
        self.arm = arm

        self.trans = trans
        self.motion_type_trans = motion_type_trans
        self.set_remapping_for('position', source_trans)

        self.set_angles(angles)
        self.motion_type_angles = motion_type_angles
        self.set_remapping_for('orientation', source_angles)

        self.vels = vels
        self.frame = frame
        self.timeout = timeout
        #self.angles = angles #convert angles to _quat

    def set_angles(self, euler_angs):
        ang_rad = [np.radians(e) for e in euler_angs]
        self.quat = tr.quaternion_from_euler(*ang_rad)
        #self._quat = tr.quaternion_from_euler(euler_angs[0], euler_angs[1], euler_angs[2])
    
    def get_angles(self):
        return [np.degrees(e) for e in tr.euler_from_quaternion(self.quat)]
    #angles = property(_get_angles, _set_angles)

    def get_smach_state(self):
        return LinearMovementSmach(self.arm,
                  self.trans, self.motion_type_trans, self.remapping_for('position'),
                  self.quat, self.motion_type_angles, self.remapping_for('orientation'),
                  self.vels, self.frame, self.timeout)
        #return LinearMovementSmach(motion_type = self.motion_type, arm = self.arm, trans = self.trans, 
        #        quat = self.quat, frame = self.frame, vels = self.vels, 
        #        source_for_point = self.remapping_for('point'), timeout=self.timeout)

class LinearMovementSmach(smach.State):

    def __init__(self, arm, 
          trans, motion_type_trans, source_for_trans, 
          quat,  motion_type_angles, source_for_quat,
          vels, frame,  timeout):

        smach.State.__init__(self, outcomes = ['succeeded', 'preempted', 'failed'], 
                             input_keys = ['position', 'orientation'], output_keys = [])
        self.arm = arm
        self.trans = trans
        self.motion_type_trans = motion_type_trans
        self.source_for_trans = source_for_trans
        
        self.quat = quat
        self.motion_type_angles = motion_type_angles
        self.source_for_quat = source_for_quat

        self.vels = vels
        self.frame = frame
        self.timeout = timeout
        self.action_client = actionlib.SimpleActionClient(arm + '_ptp', ptp.LinearMovementAction)

    def set_robot(self, robot):
        self.pr2 = robot

    def ros_goal(self, userdata):
        goal = ptp.LinearMovementGoal()

        # Look up inputs if they exist and grab data
        trans = self.trans
        if self.source_for_trans != None:
            p = userdata.position.pose.position
            trans = [p.x, p.y, p.z]

        quat = self.quat
        if self.source_for_trans != None:
            q = userdata.orientation.pose.orientation
            quat = [q.x, q.y, q.z, q.w]

        # If data is relative, grab the frame and transform them
       #   Four cases:
        #    Relative position, relative orientation
        #    Absolute position, relative orientation
        #    Relative position, absolute orientation
        #    Absolute position, Absolute orientation

        if self.motion_type_trans == 'relative':

        if self.motion_type_trans == 'relative':

        if self.motion_type_angles == 'absolute':

        if self.motion_type_angles == 'relative':

        #if self.source_for_trans != None:
        #    p = userdata.point.pose.position
        #    q = userdata.point.pose.orientation
        #    trans = [p.x, p.y, p.z]
        #    quat = [q.x, q.y, q.z, q.w]
        #    frame = userdata.point.header.frame_id
        #    quat = self.pr2.tf_listener.lookupTransform(frame, tip, rospy.Time(0))[1]
        #else:
        #    trans = self.trans
        #    frame = self.frame
        #    quat = self.quat

        pose = mat_to_pose(np.matrix(tr.translation_matrix(trans)) * np.matrix(tr.quaternion_matrix(quat)))
        goal.goal = stamp_pose(pose, frame)
        goal.trans_vel = self.vels[0]
        goal.rot_vel = self.vels[1]
        return goal

        # Send goal with newly calculated points

            rospy.loginfo('Received relative motion.')

            #print 'tool frame is', self.tool_frame
            #print 'goal frame is', goal_ps.header.frame_id

            delta_ref  = pose_to_mat(goal_ps.pose)
            tll_R_ref = tfu.tf_as_matrix(self.tf.lookupTransform('torso_lift_link', goal_ps.header.frame_
            tll_R_ref[0:3,3] = 0
            delta_tll = tll_R_ref * delta_ref

            #print 'delta_tll\n', delta_tll
            tip_current_T_tll = tfu.tf_as_matrix(self.tf.lookupTransform('torso_lift_link', self.tool_fra
            #print 'tip_current_T_tll\n', tip_current_T_tll

            #Find translation
            delta_T = delta_tll.copy()
            delta_T[0:3,0:3] = np.eye(3)
            tip_T = delta_T * tip_current_T_tll

            #Find rotation
            tip_R = delta_tll[0:3, 0:3] * tip_current_T_tll[0:3, 0:3]


            tip_new = np.matrix(np.eye(4))
            tip_new[0:3, 0:3] = tip_R
            tip_new[0:3, 3] = tip_T[0:3,3]

            #print 'tip_new\n', tip_new
            goal_ps = stamp_pose(mat_to_pose(tip_new), 'torso_lift_link')

        #if self.motion_type == 'relative':
        #    #goal.relative = True
        #elif self.motion_type == 'absolute':
        #    #goal.relative = False
        #else:
        #    raise RuntimeError('Invalid motion type given.')


    #TODO abstract this out!
    def execute(self, userdata):
        goal = self.ros_goal(userdata)
        print 'goal sent is', goal
        self.action_client.send_goal(goal)
       
        succeeded = False
        preempted = False
        r = rospy.Rate(30)
        start_time = rospy.get_time()

        while True:
            #we have been preempted
            if self.preempt_requested():
                rospy.loginfo('LinearMoveStateSmach: preempt requested')
                self.action_client.cancel_goal()
                self.service_preempt()
                preempted = True
                break

            if (rospy.get_time() - start_time) > self.timeout:
                self.action_client.cancel_goal()
                rospy.loginfo('LinearMoveStateSmach: timed out!')
                succeeded = False
                break

            #print tu.goal_status_to_string(state)
            state = self.action_client.get_state()
            if (state not in [am.GoalStatus.ACTIVE, am.GoalStatus.PENDING]):
                if state == am.GoalStatus.SUCCEEDED:
                    rospy.loginfo('LinearMoveStateSmach: Succeeded!')
                    succeeded = True
                break

            r.sleep()

        if preempted:
            return 'preempted'

        if succeeded:
            return 'succeeded'

        return 'failed'

            #if self.arm == 'left':
            #    tip = rospy.get_param('/l_cart/tip_name')
            #    tool = 'l_gripper_tool_frame'
            #if self.arm == 'right':
            #    tip = rospy.get_param('/r_cart/tip_name')
            #    tool = 'r_gripper_tool_frame'

            #print 'point before', trans
            #tip_T_tool = tr.tf_as_matrix(self.pr2.tf_listener.lookupTransform(tip, wrist, rospy.Time(0)))
            #point_tip = tip_T_tool * tr.tf_as_matrix((trans,quat))
            #trans, quat = matrix_as_tf(point_tip)
            #print 'point after', trans

##
## name maps to tool used to create it
## model
## is a state that can be stuffed into a state machine
#class LinearMoveState(tu.SimpleStateBase): # smach_ros.SimpleActionState):
#    ##
#    #
#    # @param name
#    # @param trans list of 3 floats
#    # @param angles in euler list of 3 floats
#    # @param frame 
#    def __init__(self, name, trans, angles, arm, vels, motion_type, source, frame):
#        tu.SimpleStateBase.__init__(self, name, \
#                arm + '_ptp', ptp.LinearMovementAction, 
#                goal_cb_str = 'ros_goal', input_keys=['point']) 
#        self.set_remapping_for('point', source)
#        #self.register_input_keys(['point'])
#        #print 'registered input keys', self.get_registered_input_keys()
#
#        self.trans = trans
#        self.angles = angles #convert angles to _quat
#        self.arm = arm
#        self.vels = vels
#        self.motion_type = motion_type
#        self.frame = frame
#
#    def set_robot(self, pr2):
#        self.pr2 = pr2
#
#    def get_smach_state(self):
#        state = tu.SimpleStateBase.get_smach_state(self)
#        state.set_robot = self.
#
#    def ros_goal(self, userdata, default_goal):
#        #print 'LinearMoveState: rosgoal called!!!!!!!!!!!!!!1'
#        goal = ptp.LinearMovementGoal()
#        if self.motion_type == 'relative':
#            goal.relative = True
#        elif self.motion_type == 'absolute':
#            goal.relative = False
#        else:
#            raise RuntimeError('Invalid motion type given.')
#
#        quat = self._quat
#        if self.source_for('point') != None:
#            trans, frame = userdata.point
#            if self.arm == 'left':
#                tip = rospy.get_param('/l_cart/tip_name')
#            if self.arm == 'right':
#                tip = rospy.get_param('/r_cart/tip_name')
#            quat = self.pr2.tf_listener.lookupTransform(frame, tip, rospy.Time(0))[1]
#        else:
#            trans = self.trans
#            frame = self.frame
#
#        pose = mat_to_pose(np.matrix(tr.translation_matrix(trans)) * np.matrix(tr.quaternion_matrix(quat)))
#        goal.goal = stamp_pose(pose, frame)
#        goal.trans_vel = self.vels[0]
#        goal.rot_vel = self.vels[1]
#        #print 'returned goal'
#        return goal
#
#    def _set_angles(self, euler_angs):
#        ang_rad = [np.radians(e) for e in euler_angs]
#        #self._quat = tr.quaternion_from_euler(euler_angs[0], euler_angs[1], euler_angs[2])
#        self._quat = tr.quaternion_from_euler(*ang_rad)
#    
#    def _get_angles(self):
#        return [np.degrees(e) for e in tr.euler_from_quaternion(self._quat)]
#        
#    angles = property(_get_angles, _set_angles)
#
#    #def __getstate__(self):
#    #    state = tu.SimpleStateBase.__getstate__(self)
#    #    my_state = [self.trans, self._quat, self.arm, self.vels, self.motion_type, self.frame]
#    #    return {'simple_state': state, 'self': my_state}
#
#    #def __setstate__(self, state):
#    #    tu.SimpleStateBase.__setstate__(self, state['simple_state'])
#    #    self.trans, self._quat, self.arm, self.vels, self.motion_type, self.frame = state['self']
#
#class SimpleStateBaseSmach(smach_ros.SimpleActionState):
#
#    def __init__(self, action_name, action_type, goal_obj, goal_cb_str, input_keys, output_keys):
#        smach_ros.SimpleActionState.__init__(self, action_name, action_type, 
#                goal_cb = SimpleStateCB(eval('goal_obj.%s' % goal_cb_str), input_keys, output_keys))
#        self.goal_obj = goal_obj
#
#    def __call__(self, userdata, default_goal): 
#        f = eval('self.goal_obj.%s' % self.goal_cb_str)
#        return f(userdata, default_goal)
#
#===============================================================================
#===============================================================================
#===============================================================================
#===============================================================================
