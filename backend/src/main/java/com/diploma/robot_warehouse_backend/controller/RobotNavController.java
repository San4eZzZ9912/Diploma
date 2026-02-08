package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.NavPoseResponse;
import com.diploma.robot_warehouse_backend.service.RobotNavService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/robot/nav")
public class RobotNavController {
    private final RobotNavService robotNavService;

    public RobotNavController(RobotNavService robotNavService) {
        this.robotNavService = robotNavService;
    }

    @GetMapping("/pick")
    public NavPoseResponse pick(@RequestParam String robotId) {
        return robotNavService.getPickPose(robotId);
    }

    @GetMapping("/place")
    public ResponseEntity<NavPoseResponse> place(@RequestParam String robotId) {
        return robotNavService.getPlacePose(robotId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }
}

