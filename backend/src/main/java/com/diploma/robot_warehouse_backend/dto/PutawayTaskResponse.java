package com.diploma.robot_warehouse_backend.dto;

import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import com.diploma.robot_warehouse_backend.enums.Type;

public record PutawayTaskResponse(
        Integer taskId,
        Type type,
        String sku,
        String manufacturer,
        String targetShelfCode,
        Level targetLevel,
        Side targetSide,
        Integer targetApriltagId,
        Double targetX,
        Double targetY,
        Double targetYaw
) {
}
