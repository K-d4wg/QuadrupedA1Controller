#!/usr/bin/env python3

import rospy
from tf import transformations
from gazebo_msgs.srv import ApplyJointEffort
from sensor_msgs.msg import JointState, Imu
from unitree_legged_msgs.msg import MotorCmd
import numpy as np
import A1_kinematics

Kp = 300
Kd = 5

th1_max = 4.18
th1_min = -1.05
th2_max = -0.92
th2_min = -2.69
max_eff = 55

leg_offset_y = 0.1805
leg_offset_x = 0.047

joint_names = ["FL_calf_joint","FL_hip_joint","FL_thigh_joint",
                "FR_calf_joint","FR_hip_joint","FR_thigh_joint",
                "RL_calf_joint","RL_hip_joint","RL_thigh_joint",
                "RR_calf_joint","RR_hip_joint","RR_thigh_joint"]

command_topics = ["/a1_gazebo/FL_calf_controller/command",
                  "/a1_gazebo/FL_hip_controller/command",
                  "/a1_gazebo/FL_thigh_controller/command",
                  "/a1_gazebo/FR_calf_controller/command",
                  "/a1_gazebo/FR_hip_controller/command",
                  "/a1_gazebo/FR_thigh_controller/command",
                  "/a1_gazebo/RL_calf_controller/command",
                  "/a1_gazebo/RL_hip_controller/command",
                  "/a1_gazebo/RL_thigh_controller/command",
                  "/a1_gazebo/RR_calf_controller/command",
                  "/a1_gazebo/RR_hip_controller/command",
                  "/a1_gazebo/RR_thigh_controller/command"]
                  
class Trajectory_Planner:
    def __init__(self) -> None:
        self.Rh = 0.30
    
    def step_trajectory(self, H, Sx, tgp, t):
        
        # schwungphase
        if t <= tgp/2:
            y = 10*np.sin(np.pi*(t/(tgp/2))) - (self.Rh)
            z = 3*t
        else:
            y = -(self.Rh)
        
        if t > tgp/2:
            z = (tgp/2)*3 + 3*((tgp/2)-t) 
            
        print(y,z)
        x = 8.38      
        return x,y,z
    
    def big_steppa(self, legIdx,position, step_height, step_length, T_period, t):
        # -positioon: current x,y,z coordinates
        # -step height: adjusts movement in Y direction (up/down)
        # -step_length: adjusts movement in Z direction (forward/backward)
        # -T_period: duration of one step
        # -T_stand: duration of stand phase
        # -t: current time
        x = position[0]
        y = position[1]
        z = position[2]
        T_swing = 1/6 * T_period
        T_stand = 3/6 * T_period
        global_t = t
        
        if legIdx == 2:
            t += 1/6 * T_period
            t %= T_period
            
        if legIdx == 0:
            t += 2/6* T_period
            t %= T_period
        
        if legIdx == 3:
            t += 4/6 * T_period
            t %= T_period 
            
        if legIdx == 1:
            t += 5/6 * T_period
            t %= T_period 
                         
        if 3/6 * T_period <= global_t < 4/6*T_period:
            x += 1.5*0.0048  
        elif global_t < 1/6*T_period:
            x -= 1.5*0.0048
            
        if t < T_stand:
                # no movement up, only back
            z = t*(step_length)/(T_stand) - step_length/2 + 0.05
                
            
        if T_stand <= t < T_stand + T_swing:
            u = t - T_stand
            # movement in y direction according to sin, + movement forward
            y = -step_height * np.sin(np.pi*u/(T_swing-1)) + 0.225 # <- base height!
            z = (step_length) - u*(step_length)/T_swing - step_length/2 + 0.05
                
        return [x, y, z]
    
    
def global_foot_pos(id, position):  # calculates the foot position in reference to the base link of the quadruped

    if id == 0:  # FL
        position[0] -= leg_offset_x
        position[2] -= leg_offset_y
    
    elif id == 1:  # FR
        position[0] += leg_offset_x
        position[2] -= leg_offset_y
    
    elif id == 2:  # RL
        position[0] -= leg_offset_x
        position[2] += leg_offset_y
    
    elif id == 3:  # RR
        position[0] += leg_offset_x
        position[2] += leg_offset_y

    return position

def local_foot_pos(id, position):  # does the inverse to the above function
    if id == 0:  # FL
        position[0] += leg_offset_x
        position[2] += leg_offset_y
    
    elif id == 1:  # FR
        position[0] -= leg_offset_x
        position[2] += leg_offset_y
    
    elif id == 2:  # RL
        position[0] += leg_offset_x
        position[2] -= leg_offset_y
    
    elif id == 3:  # RR
        position[0] -= leg_offset_x
        position[2] -= leg_offset_y

    return position
    
def apply_rpy(x,y,z,roll,pitch,yaw):
    """Function to rotate global positions according to desired base-rpy"""
    
    rotate_y = np.matrix([[np.cos(yaw), 0, np.sin(yaw)],
                          [0, 1, 0],
                          [-np.sin(yaw), 0, np.cos(yaw)]])
 
    rotate_x = np.matrix([[1, 0, 0],
                          [0, np.cos(pitch), -np.sin(pitch)],
                          [0, np.sin(pitch), np.cos(pitch)]])    
    
    rotate_z = np.matrix([[np.cos(roll), -np.sin(roll), 0],
                          [np.sin(roll), np.cos(roll), 0],
                          [0, 0, 1]])
    
    vector = rotate_z @ rotate_x @ rotate_y @ np.matrix([[x],[y],[z]])
    
    x_new = vector.item(0)
    y_new = vector.item(1)
    z_new = vector.item(2)
    return [x_new, y_new, z_new]
    
    
class EffortPublisher:
    def __init__(self):
        rospy.init_node('effort_publisher', anonymous=True)
        rospy.wait_for_service('/gazebo/apply_joint_effort')
        # self.apply_effort = rospy.ServiceProxy('/gazebo/apply_joint_effort', ApplyJointEffort)  # if you want to send torque directly to gazebo
        rospy.Subscriber("/a1_gazebo/joint_states", JointState, self.joint_states_callback)
        rospy.Subscriber("/trunk_imu", Imu, self.imu_callback)
        
        
        self.rate = rospy.Rate(15)
        self.positions = np.array([0,0,0,0,0,0,
                                   0,0,0,0,0,0])
        
        self.velocities = np.array([0,0,0,0,0,0,
                                    0,0,0,0,0,0])
                            

        self.goal_pos = np.array([-1.5708, 0, 0.785398, -1.5708, 0, 0.785398,
                                 -1.5708, 0, 0.785398, -1.5708, 0, 0.785398])  # standing position
        
        self.hip_to_toe_pos = [[-0.0838, 0.225, 0.0],  # FL
                               [0.0838, 0.225, 0.0],  # FR
                               [-0.0838, 0.225, 0.0],  # RL
                               [0.0838, 0.225, 0.0]]  # RR

        self.yaw = 0.0  # yaw rotation of body
        self.pitch = 0  # pitch rotation 
        self.roll = 0 # roll rotation
        
        self.x_shift = 0.06  # amount of leaning to compensate COM for moving a leg 
        
        self.global_positions = [[0,0,0],
                                 [0,0,0],
                                 [0,0,0],
                                 [0,0,0]]
        self.publishers = []
        for topic in command_topics:
            self.publishers.append(rospy.Publisher(topic,MotorCmd, queue_size=0))
                
    def publish_efforts(self):
        t = 0
        tp = Trajectory_Planner()
        step_period = 100
        
        while not rospy.is_shutdown():
            
            for legIdx in range(0,4):
                # calculate next step:
                self.hip_to_toe_pos[legIdx] = tp.big_steppa(legIdx, self.hip_to_toe_pos[legIdx], 0.05, 0.1, step_period, t)
                
                # calculate global positions (base to foot)
                self.global_positions[legIdx] = global_foot_pos(legIdx, self.hip_to_toe_pos[legIdx])
                
                # apply RPY via rotation matrix
                self.global_positions[legIdx] = apply_rpy(self.global_positions[legIdx][0], 
                                                          self.global_positions[legIdx][1], 
                                                          self.global_positions[legIdx][2], 
                                                          self.roll, self.pitch, self.yaw)
                
                # set new local position (hip to foot)
                self.hip_to_toe_pos[legIdx] = local_foot_pos(legIdx,self.global_positions[legIdx])
                
                # get current leg angles from robot
                current_ths = [self.positions[legIdx*3 + 1], 
                               self.positions[legIdx*3 + 2], 
                               self.positions[legIdx*3]]
                
                # calculate closest solution for next position
                goal_ths  = A1_kinematics.calc_correct_thetas([self.hip_to_toe_pos[legIdx][0] + self.x_shift, 
                                                               self.hip_to_toe_pos[legIdx][1], 
                                                               self.hip_to_toe_pos[legIdx][2]], current_ths, legIdx % 2 == 0)
                
                # set goal angles for corresponding leg
                self.goal_pos[legIdx*3] = goal_ths[2]
                self.goal_pos[legIdx*3 + 1] = goal_ths[0]
                self.goal_pos[legIdx*3 + 2] = goal_ths[1] + np.pi/2     
            
            #efforts = self.calculate_joint_effort()   
             
            # create and configure MotorCmd message 
            motor_command = MotorCmd()
            motor_command.mode = 10  
            motor_command.Kp = Kp
            motor_command.Kd = Kd 
                   
            for i in range(0, len(joint_names)):
                motor_command.q = self.goal_pos[i]
                self.publishers[i].publish(motor_command)  
            
            t+=1
            t %= step_period
            self.rate.sleep()
         
        
    def joint_states_callback(self, data):
        self.positions = data.position
        self.velocities = data.velocity
    
    def imu_callback(self, data):
        quaternion = [data.orientation.w,
                      data.orientation.x, 
                      data.orientation.y, 
                      data.orientation.z]
        
        euler_orientation = transformations.euler_from_quaternion(quaternion)
        
        self.current_roll = euler_orientation[2]
        self.current_pitch = euler_orientation[1]
        self.current_yaw = euler_orientation[0] + np.pi
        
        
        #self.pitch = -self.current_pitch/100
        #self.roll = self.current_roll/100
        #self.yaw = -self.current_yaw
        #print(f"Angles: \n {euler_orientation} \n_________________________________________________________")
        
        
    def calculate_joint_effort(self):
        position_error = np.subtract(self.goal_pos,self.positions)
        velocity_error = np.subtract(self.goal_vel,self.velocities)

        control_effort = np.add(Kp * position_error, Kd * velocity_error)
        return control_effort
    


if __name__ == '__main__':

    try:
        effort_publisher = EffortPublisher()
        effort_publisher.publish_efforts()
    except rospy.ROSInterruptException:
        pass