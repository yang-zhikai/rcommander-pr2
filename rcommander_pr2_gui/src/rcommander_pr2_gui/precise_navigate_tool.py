#import roslib; roslib.load_manifest('rcommander_pr2')
import rcommander.tool_utils as tu
#import smach_ros
from PyQt4.QtGui import *
from PyQt4.QtCore import *
import rospy
import pypr2.tf_utils as tfu
import tf.transformations as tr
import simple_move_base.msg as smb
import math
import actionlib
import smach
from tf_broadcast_server.srv import GetTransforms
import pypr2.pr2_utils as p2u
import numpy as np
import re

def se2_from_se3(mat):
    #print 'mat\n', mat, mat.shape
    t, r = tfu.matrix_as_tf(mat)
    x = t[0]
    y = t[1]
    theta = tr.euler_from_quaternion(r)[2]
    return x,y,theta

ROBOT_FRAME_NAME = '/base_link'
#
# controller and view
# create and edits smach states
class PreciseNavigateTool(tu.ToolBase, p2u.SE3Tool):

    def __init__(self, rcommander):
        tu.ToolBase.__init__(self, rcommander, 'navigate_refined', 'Navigate (precise)', PreciseNavigateState)
        p2u.SE3Tool.__init__(self)
        self.tf_listener = rcommander.tf_listener

        self.frames_service = rospy.ServiceProxy('get_transforms', GetTransforms, persistent=False)
        gravity_aligned_frames = ['/map', '/base_link', '/task_frame']
        self.allowed_frames = []
        fourfour = re.compile('^/4x4_\d+')
        for f in self.frames_service().frames:
            mobj = fourfour.match(f)
            if f in gravity_aligned_frames or mobj != None:
                self.allowed_frames.append(f)


    def fill_property_box(self, pbox):
        formlayout = pbox.layout()

        #self.xline = tu.double_spin_box(pbox, -999., 999., .01) #QLineEdit(pbox)
        #self.yline = tu.double_spin_box(pbox, -999., 999., .01) #QLineEdit(pbox)
        #self.tline = tu.double_spin_box(pbox, -180., 180., .01) #QLineEdit(pbox)
        group_boxes = self.make_se3_boxes(pbox)
        self.time_out = tu.double_spin_box(pbox, 0., 60., 1.) #QLineEdit(pbox)

        self.pose_button = QPushButton(pbox)
        self.pose_button.setText('Current Pose')

        self.frame_box = QComboBox(pbox)
        for f in self.allowed_frames:
            self.frame_box.addItem(f)

        #formlayout.addRow("&X", self.xline)
        #formlayout.addRow("&Y", self.yline)
        #formlayout.addRow("&Theta", self.tline)

        formlayout.addRow(group_boxes[0])
        formlayout.addRow(group_boxes[1])
        formlayout.addRow("&Time Out", self.time_out)
        formlayout.addRow("&Frame", self.frame_box)

        formlayout.addRow(self.pose_button)
        self.rcommander.connect(self.pose_button, SIGNAL('clicked()'), self.get_current_pose)
        self.reset()

    def get_current_pose(self):
        frame = str(self.frame_box.currentText())
        self.tf_listener.waitForTransform(frame, ROBOT_FRAME_NAME,  rospy.Time(), rospy.Duration(2.))
        p_base = tfu.transform(frame, ROBOT_FRAME_NAME, self.tf_listener) \
                    * tfu.tf_as_matrix(([0., 0., 0., 1.], tr.quaternion_from_euler(0,0,0)))
        p_base_tf = tfu.matrix_as_tf(p_base)

        for value, vr in zip(p_base_tf[0], [self.xline, self.yline, self.zline]):
            vr.setValue(value)
        for value, vr in zip(tr.euler_from_quaternion(p_base_tf[1]), [self.phi_line, self.theta_line, self.psi_line]):
            vr.setValue(np.degrees(value))

    def new_node(self, name=None):
        if name == None:
            nname = self.name + str(self.counter)
        else:
            nname = name

        pose_stamped = self.get_posestamped()
        state = PreciseNavigateState(nname, pose_stamped, self.time_out.value())
        return state

    def set_node_properties(self, node):
        self.set_posestamped(node.pose_stamped)
        self.time_out.setValue(node.time_out)

    def reset(self):
        for vr in [self.xline, self.yline, self.zline, self.phi_line, self.theta_line, self.psi_line]:
            vr.setValue(0.0)
        self.frame_box.setCurrentIndex(self.frame_box.findText('/map'))
        self.time_out.setValue(30.)


class PreciseNavigateState(tu.StateBase): 

    def __init__(self, name, pose_stamped, time_out):
        tu.StateBase.__init__(self, name)
        self.pose_stamped = pose_stamped
        self.time_out = time_out

    def get_smach_state(self):
        return PreciseNavigateSmach(self.pose_stamped, self.time_out)


class PreciseNavigateSmach(smach.State): 

    def __init__(self, pose_stamped, time_out):
        smach.State.__init__(self, outcomes = ['succeeded', 'preempted', 'failed', 'timed_out'], input_keys = [], output_keys = [])
        self.go_angle_client = actionlib.SimpleActionClient('go_angle', smb.GoAngleAction)
        self.go_xy_client = actionlib.SimpleActionClient('go_xy', smb.GoXYAction)

        self.pose_stamped = pose_stamped
        self.time_out = time_out
        self.CONTROL_FRAME = '/base_footprint'

    def set_robot(self, pr2):
        if pr2 != None:
            self.tf_listener = pr2.tf_listener

    def execute(self, userdata):
        #Create goal and send it up here
        self.tf_listener.waitForTransform(self.CONTROL_FRAME, self.pose_stamped.header.frame_id,  rospy.Time(0), rospy.Duration(10.))
        bl_T_frame = tfu.tf_as_matrix(self.tf_listener.lookupTransform(self.CONTROL_FRAME, self.pose_stamped.header.frame_id, rospy.Time(0)))

        #print 'control_T_frame\n', bl_T_frame
        trans = np.array([self.pose_stamped.pose.position.x, self.pose_stamped.pose.position.y, self.pose_stamped.pose.position.z])
        quat = [self.pose_stamped.pose.orientation.x, self.pose_stamped.pose.orientation.y, 
                self.pose_stamped.pose.orientation.z, self.pose_stamped.pose.orientation.w]

        h_frame = tfu.tf_as_matrix((trans, quat))
                #([self.x, self.y, 0], tr.quaternion_from_euler(0, 0, self.t)))

        #print 'h_frame\n', h_frame

        #print 'bl_T_frame * h_frame\n', bl_T_frame * h_frame
        x, y, t = se2_from_se3(bl_T_frame * h_frame)

        #print 'GOAL', x, y, np.degrees(t)

        xy_goal = smb.GoXYGoal(x,y)
        self.go_xy_client.send_goal(xy_goal)
        result_xy = tu.monitor_goals(self, [self.go_xy_client], 'PreciseNavigateSmach', self.time_out)
        if result_xy != 'succeeded':
            return result_xy

        ang_goal = smb.GoAngleGoal(t)
        self.go_angle_client.send_goal(ang_goal)
        result_ang = tu.monitor_goals(self, [self.go_angle_client], 'PreciseNavigateSmach', self.time_out)

        return result_ang
















    
    
    
    
    
    
    
    
    
    
    
    
    
    #def execute_goal(self, goal, action):
    #    action.send_goal(goal)

    #    succeeded = False
    #    preempted = False
    #    start_time = rospy.get_time()

    #    r = rospy.Rate(30)
    #    while not rospy.is_shutdown():
    #        #we have been preempted
    #        if self.preempt_requested():
    #            rospy.loginfo('PreciseNavigateSmach: preempt requested')
    #            self.service_preempt()
    #            action.cancel_goal()
    #            preempted = True
    #            break


    #        if (rospy.get_time() - start_time) > trajectory_time_out:
    #            action.cancel_goal() 
    #            rospy.loginfo('PreciseNavigateSmach: timed out!')
    #            succeeded = False
    #            break


##
## name maps to tool used to create it
## model
## is a state that can be stuffed into a state machine
#class PreciseNavigateTool(tu.SimpleStateBase): # smach_ros.SimpleActionState):
#
#    def __init__(self, name, xy, theta, frame): #, frame):
#        tu.SimpleStateBase.__init__(self, name, \
#                'go_xy', smb.GoXYAction, 
#                goal_cb_str = 'ros_goal') 
#        self.xy = xy
#        self.theta = theta 
#        self.frame = frame
#
#    def ros_goal(self, userdata, default_goal):
#        g = smb.GoXYGoal()
#        g.x
#        g.y
#
#        #p = g.target_pose
#        #
#        #p.header.frame_id = 'map'
#        #p.header.stamp = rospy.get_rostime()
#        #p.pose.position.x = self.xy[0]
#        #p.pose.position.y = self.xy[1]
#        #p.pose.position.z = 0
#        #
#        #r = tr.quaternion_from_euler(0, 0, self.theta)
#        #p.pose.orientation.x = r[0]
#        #p.pose.orientation.y = r[1]
#        #p.pose.orientation.z = r[2]
#        #p.pose.orientation.w = r[3]
#        return g




