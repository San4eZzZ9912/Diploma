package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@AllArgsConstructor
public class NavPoseResponse {
    private Double mapX;
    private Double mapY;
    private Double mapYaw;
    private Integer apriltagId;
}
