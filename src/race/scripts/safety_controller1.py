#!/usr/bin/env python
import rospy
from ackermann_msgs.msg import AckermannDriveStamped
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Point
from visualization_msgs.msg import Marker
from visualization_msgs.msg import MarkerArray
import math
import numpy as np
from numpy import linalg as la
from tf.transformations import euler_from_quaternion, quaternion_from_euler
import csv
import os
import rospkg 

class pure_pursuit:

    def __init__(self,waypoint_file,display_goal=False):
        # initialize class fields 
        self.waypoint_file = waypoint_file
        self.display_goal = display_goal

        # pure pursuit parameters
        self.LOOKAHEAD_DISTANCE = 1.70#1.70 # meters
        self.distance_from_rear_wheel_to_front_wheel = 0.5
        self.VELOCITY = 3.2 # m/s
        self.read_waypoints()
       
        # Publisher for 'drive_parameters' (speed and steering angle)
        self.pub = rospy.Publisher('racecar/safety', AckermannDriveStamped, queue_size=100)
        rospy.Subscriber("racecar/odom", Odometry, self.callback, queue_size=100)

        if(self.display_goal):
            # Publisher for the goal point
            self.goal_pub = rospy.Publisher('/goal_point', MarkerArray, queue_size="1")
            self.considered_pub= rospy.Publisher('/considered_points', MarkerArray, queue_size="1")
            self.point_in_car_frame= rospy.Publisher('/goal_point_car_frame', MarkerArray, queue_size="1")
            # Subscriber to vehicle position 
        

    # Import waypoints.csv into a list (path_points)
    def read_waypoints(self):

        # get an instance of RosPack with the default search paths
        rospack = rospkg.RosPack()
        #get the path for this paackage
        package_path=rospack.get_path('pure_pursuit')
        filename=os.path.sep.join([package_path,'waypoints',waypoint_file])

        with open(filename) as f:
            path_points = [tuple(line) for line in csv.reader(f)]

        # Turn path_points into a list of floats to eliminate the need for casts in the code below.
        self.path_points_x   = np.asarray([float(point[0]) for point in path_points])
        self.path_points_y   = np.asarray([float(point[1]) for point in path_points])

        # list of xy pts 
        self.xy_points = np.hstack((self.path_points_x.reshape((-1,1)),self.path_points_y.reshape((-1,1)))).astype('double')
   
    def visualize_point(self,pts,publisher,frame='/map',r=1.0,g=0.0,b=1.0):
        # create a marker array
        markerArray = MarkerArray()

        idx = np.random.randint(0,len(pts))
        pt = pts[idx]

        x = float(pt[0])
        y = float(pt[1])
		
        marker = Marker()
        marker.header.frame_id = frame
        marker.type = marker.SPHERE
        marker.action = marker.ADD
        marker.scale.x = 0.2
        marker.scale.y = 0.2
        marker.scale.z = 0.2
        marker.color.a = 1.0
        marker.color.r = r
        marker.color.g = g
        marker.color.b = b
        marker.pose.orientation.w = 1.0
        marker.pose.position.x = x
        marker.pose.position.y = y
        marker.pose.position.z = 0
        markerArray.markers.append(marker)
        publisher.publish(markerArray)


    # Input data is PoseStamped message from topic racecar_name/odom.
    # Runs pure pursuit and publishes velocity and steering angle.
    def callback(self,data):

        qx=data.pose.pose.orientation.x
        qy=data.pose.pose.orientation.y
        qz=data.pose.pose.orientation.z
        qw=data.pose.pose.orientation.w

        quaternion = (qx,qy,qz,qw)
        euler = euler_from_quaternion(quaternion)
        yaw   = np.double(euler[2])

        x = data.pose.pose.position.x
        y = data.pose.pose.position.y

        ## finding the distance of each way point from the current position 
        curr_pos= np.asarray([x,y]).reshape((1,2))
        dist_arr = np.linalg.norm(self.xy_points-curr_pos,axis=-1)

        ##finding those points which are less than the look ahead distance (will be behind and ahead of the vehicle)
        goal_arr = np.where((dist_arr > self.LOOKAHEAD_DISTANCE) & (dist_arr<self.LOOKAHEAD_DISTANCE+0.3))[0]
        
        # finding the goal point which is within the goal points 
        pts = self.xy_points[goal_arr]

        # get all points in front of the car, using the orientation 
        # and the angle between the vectors
        pts_infrontofcar=[]
        for idx in range(len(pts)): 
            v1 = pts[idx] - curr_pos
            #since the euler was specified in the order x,y,z the angle is wrt to x axis
            v2 = [np.cos(yaw), np.sin(yaw)]

            angle= self.find_angle(v1,v2)
            if angle < np.pi/2:
                pts_infrontofcar.append(pts[idx])

        pts_infrontofcar =np.asarray(pts_infrontofcar)
        # compute new distances
        if(pts_infrontofcar.shape[0]>0): 
            dist_arr = np.linalg.norm(pts_infrontofcar-curr_pos,axis=-1)- self.LOOKAHEAD_DISTANCE
        
            # get the point closest to the lookahead distance
            idx = np.argmin(dist_arr)

            # goal point 
            goal_point = pts_infrontofcar[idx]
            if(self.display_goal):
                self.visualize_point([goal_point],self.goal_pub)

            # transform it into the vehicle coordinates
            v1 = (goal_point - curr_pos)[0].astype('double')
            xgv = (v1[0] * np.cos(yaw)) + (v1[1] * np.sin(yaw))
            ygv = (-v1[0] * np.sin(yaw)) + (v1[1] * np.cos(yaw))
        
            # calculate the steering angle
            angle = math.atan2(ygv,xgv)
            angle= np.clip(angle,-0.610865,0.610865)
            self.const_speed(angle)

        # right now just keep going straight but it will need to be more elegant
        # TODO: make elegant
        else:
            rospy.logwarn("no goal point")
            self.const_speed(0.0)
   
    # USE THIS FUNCTION IF CHANGEABLE SPEED IS NEEDED
    def set_speed(self,angle):
        msg = AckermannDriveStamped()
        msg.header.stamp=rospy.Time.now()
        msg.drive.steering_angle = angle
        speed= 1.5
        angle = abs(angle)
        if(angle <0.01):
            speed = 10.0#11.5
        elif(angle<0.0336332):
            speed = 9.0#11.1
        elif(angle < 0.0872665):
            speed = 7.0#7.6
        elif(angle<0.1309):
            speed = 6.5#6.5 
        elif(angle < 0.174533):
            speed = 4.8#6.0
        elif(angle < 0.261799):
            speed = 4.6#5.5
        elif(angle < 0.349066):
            speed = 4.3#3.2
        elif(angle < 0.436332):
            speed = 4.0#5.1
        else:
            print("more than 25 degrees",angle)
            speed = 3.0
        print(speed)

        msg.drive.speed = speed
        self.pub.publish(msg)

        


    # USE THIS FUNCTION IF CONSTANT SPEED IS NEEDED
    def const_speed(self,angle):
        msg = AckermannDriveStamped()
        msg.header.stamp=rospy.Time.now()
        msg.drive.steering_angle = angle
        msg.drive.speed = 0.7
        self.pub.publish(msg)

    # find the angle bewtween two vectors    
    def find_angle(self, v1, v2):
        cosang = np.dot(v1, v2).astype('double')
        sinang = la.norm(np.cross(v1, v2)).astype('double')
        return np.arctan2(sinang, cosang).astype('double')


if __name__ == '__main__':
    rospy.init_node('pure_pursuit')
    #get the arguments passed from the launch file
    args = rospy.myargv()[1:]
    # get the racecar name so we know what to subscribe to
    # get the path to the file containing the waypoints
    waypoint_file=args[0]
    C = pure_pursuit(waypoint_file)  

    rospy.spin()