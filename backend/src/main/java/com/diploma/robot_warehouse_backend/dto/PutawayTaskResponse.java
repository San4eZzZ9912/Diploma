package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import com.diploma.robot_warehouse_backend.enums.Type;
import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class PutawayTaskResponse {
    private Integer taskId;
    private Type type;

    private String sku;
    private String manufacturer;

    private String targetShelfCode;
    private Level targetLevel;
    private Side targetSide;
    private Integer targetApriltagId;

    private Double targetX;
    private Double targetY;
    private Double targetYaw;
}
