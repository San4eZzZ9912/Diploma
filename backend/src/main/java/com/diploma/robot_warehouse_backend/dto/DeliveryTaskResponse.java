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
public class DeliveryTaskResponse {
    private Integer taskId;
    private Type type;

    private String sku;
    private String manufacturer;

    private Integer sourceSlotId;
    private String sourceShelfCode;
    private Level sourceLevel;
    private Side sourceSide;
    private Integer sourceApriltagId;

    private Double sourceX;
    private Double sourceY;
    private Double sourceYaw;

    private String deliveryShelfCode;
    private Double targetX;
    private Double targetY;
    private Double targetYaw;
}
