#!/usr/bin/env python
"""
File:   potential_field_controller.py
Author: Nathaniel Hamilton

Description: blah

Usage:  blah

Remaining Tasks:
        * Writing everything
"""
from numpy.core.multiarray import ndarray
from sensor_msgs.msg import LaserScan
import time
import rospy
import copy
import numpy as np
from race.msg import drive_param
import math


class PotentialFieldController(object):
    def __init__(self, car_width=0.5, scan_width=270.0, lidar_range=10.0, turn_clearance=0.35, max_turn_angle=34.0,
                 min_speed=-0.1, max_speed=2.77, min_dist=0.15, max_dist=3.0, no_obst_dist=6.0):
        """
        Todo: explanation of what is

        :param car_width:       (float) Half the car's width with tolerance used for calculating todo Default=0.5
        :param scan_width:      (float) The arc width of the full Lidar scan in degrees.
                                            Default=270.0 for Hokuyo UST-10LX
        :param lidar_range:     (float) Maximum range of the Lidar in meters. Default=10.0 for Hokuyo UST-10LX
        :param turn_clearance:  (float) This is the radius, in meters, to the left or right of the car that must be
                                            clear when the car is attempting to turn left or right. Default=0.35
        :param max_turn_angle:  (float) Maximum steering angle of the car, in degrees. Default=34.0
        :param min_speed:       (float) Slowest speed the car can go in m/s. Negative for backing up. Default=-0.1
        :param max_speed:       (float) Maximum speed the car can go in m/s. Default=2.77
        :param min_dist:        (float) The closest the car should be allowed to get to a wall in meters. Default=0.15
        :param max_dist:        (float) TODO
        :param no_obst_dist:    (float) The furthest distance, in meters, the car will care about obstacles in its way.
                                            Default=6.0
        """

        # Easily changeable parameters for tuning
        self.force_scale_x = 0.7
        self.force_scale_y = 0.7
        self.force_offset_x = 100.0
        self.force_offset_y = 0.0
        self.steering_p_gain = 1.0
        self.steering_d_gain = 0.1

        # Save input parameters
        self.car_width = car_width
        self.scan_width = scan_width
        self.lidar_range = lidar_range
        self.turn_clearance = turn_clearance
        self.max_turn_angle = max_turn_angle
        self.min_speed = min_speed
        self.max_speed = max_speed
        self.min_distance = min_dist
        self.max_distance = max_dist
        self.no_obstacles_distance = no_obst_dist

        # Initialize publisher for speed and angle commands
        self.pub_drive_param = rospy.Publisher('drive_parameters', drive_param, queue_size=5)

        # Initialize subscriber for the Lidar
        rospy.Subscriber('scan', LaserScan, self.lidar_callback)

        # Initialize angle forces in order to use a PD controller
        self.last_angle_force = 0.0

    def clip_ranges(self, ranges, min_angle, max_angle, angle_step):
        """
        TODO: write and explain what this do
        :param ranges:
        :param min_angle:
        :param max_angle:
        :param angle_step:
        :return:
        """

        # Create an array of the measured angles
        angles = np.asarray(range(int(min_angle), int(max_angle), int(angle_step)), dtype=np.float32)

        # Compute the indices of values within +/- 90 degrees
        indices = np.where(angles >= 0.0 and angles <= math.pi)[0]

        # Only use values within +/- 90 degrees
        clipped_ranges = ranges[indices]
        clipped_angles = angles[indices]

        #TODO: Other clipping and data manipulation to enforce bounds?

        return clipped_ranges, clipped_angles

    def compute_forces(self, ranges, angles):
        """
        TODO: write and explain what this do
        :param ranges:
        :param angles:
        :return:
        """

        # Compute useful values using the data
        neg_ranges_2 = -1 * np.square(ranges)
        angles_cos = np.cos(angles)
        angles_sin = np.sin(angles)

        # Compute the forces that are larger the closer to the car they are
        forces_x = np.divide(angles_cos, neg_ranges_2)
        forces_y = np.divide(angles_sin, neg_ranges_2)

        # Compute the net forces, including the offsets
        net_force_x = self.force_scale_x * float(np.sum(forces_x)) + self.force_offset_x
        net_force_y = self.force_scale_y * float(np.sum(forces_y)) + self.force_offset_y

        # Compute the angle force and speed force
        angle_force = np.arctan2(net_force_y, net_force_x)
        speed_force = net_force_x**2 - net_force_y**2 # Note: y forces are subtractive. If the car is close to a wall or turning, we want to go slower
        speed_force = (speed_force / speed_force) * math.sqrt(abs(speed_force))

        return speed_force, angle_force

    def lidar_callback(self, data):
        """
        TODO: write and explain what this do
        :param data:
        :return:
        """
        # Reduce the Lidar data to only scans between +/- 90 degrees
        ranges = np.asarray(data.ranges)
        min_angle = data.angle_min
        max_angle = data.angle_max
        angle_step = data.angle_increment
        clipped_ranges, clipped_angles = self.clip_ranges(ranges, min_angle, max_angle, angle_step)

        # Compute forces from the potential field acquired from the Lidar scan
        speed_force, angle_force = self.compute_forces(clipped_ranges, clipped_angles)

        # Compute speed and steering commands, then publish them
        self.publish_commands(speed_force, angle_force)

        return

    def publish_commands(self, speed_force, angle_force):
        """
        TODO: describe what do
        :param speed_force: (float)
        :param angle_force: (float)
        """

        # Convert angle_force to angle command
        angle_cmd = self.steering_p_gain * angle_force + self.steering_d_gain * (angle_force - self.last_angle_force)
        self.last_angle_force = angle_force

        # Make sure angle command is within steering settings
        if abs(angle_cmd) > self.max_turn_angle:
            angle_cmd = (angle_cmd / angle_cmd) * self.max_turn_angle

        # Convert speed_force to speed command
        if speed_force < 0: # In the case that the car needs to backup, flip the turning angle
            angle_cmd = -1 * angle_cmd
            speed_cmd = self.min_speed
        else:
            speed_percentage = (self.force_offset_x - speed_force) / self.force_offset_x
            speed_cmd = speed_percentage * self.max_speed

        # Publish the command
        msg = drive_param()
        msg.angle = angle_cmd
        msg.velocity = speed_cmd
        self.pub_drive_param.publish(msg)

        return


if __name__ == '__main__':
    rospy.init_node('potential_field_control', anonymous=True)
    extendObj = PotentialFieldController()
    rospy.Subscriber('scan', LaserScan, extendObj.lidar_callback)
    rospy.spin()