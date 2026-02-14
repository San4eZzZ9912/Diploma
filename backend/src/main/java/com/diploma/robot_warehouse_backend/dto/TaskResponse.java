package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class TaskResponse {
    private Integer taskId;
    private String sku;
    private String manufacturer;
    private String targetShelfCode;
    private String targetLevel;
    private String targetSide;
    private Integer targetApriltagId;
    private Double targetX;
    private Double targetY;
    private Double targetYaw;
}
